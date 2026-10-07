"""A presentation layer for one native CMake workflow, never a preset interpreter."""

import codecs
from collections import deque
import os
from pathlib import Path
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time


STAGE = re.compile(r'Executing workflow step (\d+) of (\d+): (\w+) preset "(.*)"')
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
DIAGNOSTIC = re.compile(r"\b(warning|error|fatal|note)\b|警告|错误", re.IGNORECASE)
TEST_RESULT = re.compile(r"(\d+)% tests passed(?:, (\d+) tests failed)? out of (\d+)")


class _Display:
    def __init__(self, verbose, preset):
        self.verbose = verbose
        self.preset = preset
        self.color = sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.getenv("TERM") != "dumb"
        self.dynamic = self.color and not verbose
        self.live = False
        self.last_tick = 0
        self.frame = 0
        self.stage = None
        self.started = time.monotonic()
        self.detail = ""
        self.tail = deque(maxlen=40)
        self.warning_context = 0

    def paint(self, message, color):
        if self.color and color:
            return f"\x1b[{color}m{message}\x1b[0m"
        return message

    def clear(self):
        if self.live:
            print("\r\x1b[2K", end="", flush=True)
            self.live = False

    def say(self, message, color=""):
        self.clear()
        print(self.paint(message, color), flush=True)

    def tick(self):
        now = time.monotonic()
        if not self.dynamic or not self.stage or now - self.last_tick < 0.1:
            return
        spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[self.frame % 10]
        # Only ASCII stage/progress text goes into the replaceable row. Keep it
        # on one physical line even in a narrow terminal; completed rows are full.
        text = f" {self.stage[0]:<11} {now - self.started:>6.1f}s  [{self.stage[2]}]"
        width = shutil.get_terminal_size().columns
        row = ("  " + spinner + text.encode("ascii", "replace").decode())[:max(0, width - 1)]
        print("\r\x1b[2K" + self.paint(row, "36"), end="", flush=True)
        self.live, self.last_tick, self.frame = True, now, self.frame + 1

    def finish_stage(self, success, cancelled=False):
        if self.stage:
            mark, color = ("✓", "32") if success else ("✗", "31")
            if cancelled:
                mark, color = "−", "33"
            kind, preset, _ = self.stage
            detail = f"  {self.detail}" if self.detail else ""
            if preset != self.preset:
                detail += f"  ({preset})"
            self.say(f"  {self.paint(mark, color)} {kind:<11}"
                     + self.paint(f" {time.monotonic() - self.started:>6.1f}s{detail}", "90"))
            self.stage = None

    def line(self, text, stream):
        clean = ANSI.sub("", text).strip()
        self.tail.append(text)
        stage = STAGE.fullmatch(clean) if stream == "stdout" else None
        if stage:
            # Only a later CMake stage marker implies that the previous step finished.
            self.finish_stage(True)
            index, count, kind, preset = stage.groups()
            self.stage = (kind.capitalize(), preset, f"{index}/{count}")
            self.started, self.detail = time.monotonic(), ""
            self.warning_context = 0
            if self.dynamic:
                self.tick()
            else:
                self.say(f"  > {kind.capitalize()} [{index}/{count}]", "90")
        elif clean == "ninja: no work to do.":
            self.detail = "up to date"
        elif result := TEST_RESULT.fullmatch(clean):
            percent, failed, total = result.groups()
            # New CTest omits the failed count on success. Don't infer a count
            # from a rounded percentage for an unfamiliar failure summary.
            self.detail = (f"{int(total) - int(failed or 0)}/{total} passed"
                           if failed is not None or percent == "100" else clean)
        # stderr is never filtered. Common stdout diagnostics keep following
        # source/caret/note lines; unfamiliar output is always available in logs.
        diagnostic = bool(DIAGNOSTIC.search(clean))
        if diagnostic:
            self.warning_context = 8
        if self.verbose or stream == "stderr" or diagnostic or (self.warning_context and not stage):
            self.say(text.rstrip("\r\n"))
        if self.warning_context and not diagnostic:
            self.warning_context -= 1


def _read(stream, name, messages):
    try:
        while chunk := stream.read1(8192):
            messages.put((name, chunk))
    except OSError as error:
        messages.put((name, error))
    finally:
        messages.put((name, None))


def _send(process, signum):
    try:
        if os.name == "posix":
            os.killpg(process.pid, signum)
        elif process.poll() is None:
            process.terminate()
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin can report EPERM for an empty/zombie-only process group after
        # SIGKILL. Reap/check our child before treating this as completed cleanup.
        if sys.platform != "darwin" or process.poll() is None:
            raise


def _stop(process):
    """Bound cleanup after a presentation/I/O failure, including descendants."""
    _send(process, signal.SIGTERM)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    if os.name == "posix":
        _send(process, signal.SIGKILL)


def run_workflow(preset, *, verbose=False):
    display = _Display(verbose, preset)
    started = time.monotonic()
    command = ["cmake", "--workflow", "--preset", preset]
    process = None
    cancelled = None
    previous_handlers = {}
    # A private, unique directory avoids overwriting project files or old logs.
    try:
        log_dir = Path(tempfile.mkdtemp(prefix="cxx-workflow-"))
    except OSError as error:
        print(f"cxx: cannot create logs: {error}", file=sys.stderr)
        return 1
    display.say("\n  " + display.paint(Path.cwd().name, "1") + display.paint(f" / {preset}\n", "90"))

    def cancel(signum, _frame):
        nonlocal cancelled
        cancelled = cancelled or signum

    try:
        with (log_dir / "stdout.log").open("wb") as stdout_log, (log_dir / "stderr.log").open("wb") as stderr_log:
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[sig] = signal.signal(sig, cancel)
            # No shell, environment overrides, preset reads or synthetic build steps.
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=os.name == "posix")
            messages = queue.Queue(maxsize=32)
            for name in ("stdout", "stderr"):
                threading.Thread(target=_read, args=(getattr(process, name), name, messages), daemon=True).start()
            logs = {"stdout": stdout_log, "stderr": stderr_log}
            decoders = {name: codecs.getincrementaldecoder("utf-8")("replace") for name in logs}
            pending = {name: "" for name in logs}
            remaining = 2
            cancel_deadline = None
            while remaining or process.poll() is None:
                if cancelled:
                    if cancel_deadline is None:
                        _send(process, cancelled)
                        cancel_deadline = time.monotonic() + 3
                        display.say("  Cancelling…", "33")
                        display.dynamic = False
                    elif time.monotonic() >= cancel_deadline:
                        if os.name == "posix":
                            _send(process, signal.SIGKILL)
                        elif process.poll() is None:
                            process.kill()
                        cancel_deadline = float("inf")
                display.tick()
                try:
                    name, chunk = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                if isinstance(chunk, OSError):
                    raise chunk
                if chunk is None:
                    remaining -= 1
                else:
                    logs[name].write(chunk)
                    logs[name].flush()
                pending[name] += decoders[name].decode(chunk or b"", final=chunk is None)
                # Bound memory even for enormous/no-newline compiler output.
                while pending[name]:
                    newline = pending[name].find("\n")
                    if newline < 0 and len(pending[name]) < 8192 and chunk is not None:
                        break
                    end = min(newline + 1, 8192) if newline >= 0 else min(len(pending[name]), 8192)
                    display.line(pending[name][:end], name)
                    pending[name] = pending[name][end:]
            result = process.wait()
            result = result if result >= 0 else 128 - result
            if cancelled:
                if os.name == "posix":
                    _send(process, signal.SIGKILL)
                result = 128 + cancelled
    except OSError as error:
        if process is not None:
            _stop(process)
        display.say(f"cxx: workflow could not complete: {error}", "31")
        result = 127 if isinstance(error, FileNotFoundError) and process is None else 1
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        if process is not None:
            process.stdout.close()
            process.stderr.close()

    display.finish_stage(result == 0, cancelled=bool(cancelled))
    if result != 0 and not cancelled and not verbose and display.tail:
        display.say("\n  Recent output (last 40 lines/fragments; full output in logs):", "33")
        for line in display.tail:
            display.say(line.rstrip("\r\n"))
    label, color = ("PASS", "32") if result == 0 else ("FAIL", "31")
    if cancelled:
        label, color = "CANCELLED", "33"
    detail = f"  {time.monotonic() - started:.1f}s" + (f" · exit {result}" if result else "")
    display.say("\n  " + display.paint(label, "1;" + color) + display.paint(detail, "90"))
    if verbose or result:
        command_text = shlex.join(command) if os.name == "posix" else subprocess.list2cmdline(command)
        display.say(f"  Command  {command_text}", "90")
    display.say(f"  Logs     {log_dir}\n", "90")
    return result
