"""A presentation layer for one native CMake workflow, never a preset interpreter."""

import codecs
from collections import deque
import os
from pathlib import Path
import queue
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time


STAGE = re.compile(r'Executing workflow step (\d+) of (\d+): (\w+) preset "(.*)"')
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
DIAGNOSTIC = re.compile(r"\b(warning|error|fatal|note)\b|警告|错误", re.IGNORECASE)
NAMES = {"configure": "配置", "build": "构建", "test": "测试", "package": "打包"}


class _Display:
    def __init__(self, verbose):
        self.verbose = verbose
        self.color = sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.getenv("TERM") != "dumb"
        self.stage = None
        self.started = time.monotonic()
        self.detail = ""
        self.tail = deque(maxlen=40)
        self.warning_context = 0

    def say(self, message, color=""):
        if self.color and color:
            message = f"\x1b[{color}m{message}\x1b[0m"
        print(message, flush=True)

    def finish_stage(self, success):
        if self.stage:
            mark = "✓" if success else "✗"
            detail = f" · {self.detail}" if self.detail else ""
            self.say(f"  {mark} {self.stage}  {time.monotonic() - self.started:.1f}s{detail}",
                     "32" if success else "31")
            self.stage = None

    def line(self, text, stream):
        clean = ANSI.sub("", text).strip()
        self.tail.append(text)
        stage = STAGE.fullmatch(clean) if stream == "stdout" else None
        if stage:
            # Only a later CMake stage marker implies that the previous step finished.
            self.finish_stage(True)
            index, count, kind, preset = stage.groups()
            self.stage = f"[{index}/{count}] {NAMES.get(kind, kind)} · {preset}"
            self.started, self.detail = time.monotonic(), ""
            self.warning_context = 0
            self.say(f"  → {self.stage}", "36")
        elif clean == "ninja: no work to do.":
            self.detail = "无需重新编译"
        elif re.fullmatch(r"\d+% tests passed(?:, \d+ tests failed)? out of \d+", clean):
            self.detail = clean
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
    display = _Display(verbose)
    started = time.monotonic()
    command = ["cmake", "--workflow", "--preset", preset]
    process = None
    cancelled = None
    previous_handlers = {}
    # A private, unique directory avoids overwriting project files or old logs.
    try:
        log_dir = Path(tempfile.mkdtemp(prefix="cxx-workflow-"))
    except OSError as error:
        print(f"cxx: 无法创建日志：{error}", file=sys.stderr)
        return 1
    display.say(f"\n{Path.cwd().name} · {preset}", "1")
    display.say("命令：" + (shlex.join(command) if os.name == "posix" else subprocess.list2cmdline(command)))
    display.say(f"日志：{log_dir}\n", "90")

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
                        display.say("\n正在取消工作流…", "33")
                    elif time.monotonic() >= cancel_deadline:
                        if os.name == "posix":
                            _send(process, signal.SIGKILL)
                        elif process.poll() is None:
                            process.kill()
                        cancel_deadline = float("inf")
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
        display.say(f"cxx: 工作流无法完成：{error}", "31")
        result = 127 if isinstance(error, FileNotFoundError) and process is None else 1
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        if process is not None:
            process.stdout.close()
            process.stderr.close()

    display.finish_stage(result == 0)
    if result != 0 and not verbose and display.tail:
        display.say("\n失败前的输出（末 40 行/片段；完整内容见日志）：", "33")
        for line in display.tail:
            display.say(line.rstrip("\r\n"))
    display.say(f"\n{'通过' if result == 0 else '未完成'} · {time.monotonic() - started:.1f}s · exit {result}",
                "32" if result == 0 else "31")
    display.say(f"日志：{log_dir}", "90")
    return result
