import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from test_cxx import CLI, run_cxx


FAKE_CMAKE = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
print(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "probe": os.getenv("CXX_PROBE")}), flush=True)
mode = os.getenv("CXX_FAKE_MODE", "success")
if mode == "cancel":
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"])
    Path("child.pid").write_text(str(child.pid))
    print("ready", flush=True)
    time.sleep(30)
if mode == "unknown":
    print("unrecognized native progress")
    sys.exit(0)
if mode == "large":
    os.write(1, b"x" * 200000 + b"\xff\npartial")
    os.write(2, b"stderr without newline")
    sys.exit(0)
print('Executing workflow step 1 of 3: configure preset "custom"', flush=True)
time.sleep(0.12)
print("routine dependency usage instructions")
print("stderr notice without a diagnostic keyword", file=sys.stderr, flush=True)
print('Executing workflow step 2 of 3: build preset "custom"', flush=True)
time.sleep(0.12)
print("source.cpp:1: warning: important warning")
print("  source context")
print("  ^")
print("ninja: no work to do.")
if mode == "failure":
    print("failure context")
    sys.exit(47)
if mode == "signal":
    os.kill(os.getpid(), signal.SIGTERM)
print('Executing workflow step 3 of 3: test preset "custom"', flush=True)
time.sleep(0.12)
print("100% tests passed, 0 tests failed out of 1")
'''


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        executable = self.bin / "cmake"
        executable.write_text(f"#!{sys.executable}\n" + FAKE_CMAKE)
        executable.chmod(0o755)
        self.env = {**os.environ, "PATH": str(self.bin), "TMPDIR": str(self.root), "NO_COLOR": "1",
                    "CXX_PROBE": "unchanged environment"}

    def run_workflow(self, mode="success", *extra, preset="custom"):
        return run_cxx(self.root, "workflow", preset, *extra,
                       env={**self.env, "CXX_FAKE_MODE": mode})

    def log(self, stream):
        logs = list(self.root.glob(f"cxx-workflow-*/{stream}.log"))
        self.assertEqual(len(logs), 1, logs)
        self.assertEqual(logs[0].parent.stat().st_mode & 0o077, 0)
        return logs[0].read_bytes()

    def test_native_invocation_summary_stderr_and_warning_context(self):
        preset = "custom ; $(touch unexpected)"
        result = self.run_workflow(preset=preset)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)
        self.assertIn("> Configure [1/3]", result.stdout)
        self.assertIn("up to date", result.stdout)
        self.assertIn("1/1 passed", result.stdout)
        self.assertIn("important warning\n  source context\n  ^", result.stdout)
        self.assertIn("stderr notice without a diagnostic keyword", result.stdout)
        self.assertNotIn("routine dependency usage", result.stdout)
        self.assertNotIn("\x1b", result.stdout)
        self.assertNotIn("Command", result.stdout)
        self.assertNotIn("exit 0", result.stdout)
        self.assertNotIn("Logs     ", result.stdout)
        raw = self.log("stdout").decode()
        self.assertIn("routine dependency usage", raw)
        invocation = json.loads(raw.splitlines()[0])
        self.assertEqual(invocation, {"argv": ["--workflow", "--preset", preset],
                                     "cwd": str(self.root), "probe": "unchanged environment"})
        self.assertFalse((self.root / "unexpected").exists())
        self.assertIn(b"stderr notice", self.log("stderr"))

    def test_verbose_streams_routine_output_too(self):
        result = self.run_workflow("success", "--verbose", preset="custom ; $(touch unexpected)")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("routine dependency usage", result.stdout)
        self.assertNotIn("Recent output", result.stdout)
        self.assertIn("Command  cmake --workflow --preset 'custom ; $(touch unexpected)'", result.stdout)
        self.assertEqual(result.stdout.count("Logs     "), 1)
        self.assertFalse((self.root / "unexpected").exists())

    def test_failure_preserves_exit_and_context_without_success(self):
        result = self.run_workflow("failure")
        self.assertEqual(result.returncode, 47, result.stderr)
        self.assertIn("exit 47", result.stdout)
        self.assertIn("✗ Build", result.stdout)
        self.assertIn("failure context", result.stdout)
        self.assertNotIn("PASS", result.stdout)
        self.assertIn("FAIL", result.stdout)
        self.assertIn("Recent output", result.stdout)
        self.assertEqual(result.stdout.count("Logs     "), 1)
        self.assertNotIn("[3/3]", result.stdout)
        self.assertIn(b"failure context", self.log("stdout"))

    def test_unknown_progress_does_not_invent_steps(self):
        result = self.run_workflow("unknown")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)
        self.assertNotIn("exit 0", result.stdout)
        self.assertNotIn("[1/", result.stdout)
        self.assertIn(b"unrecognized native progress", self.log("stdout"))

    def test_large_partial_and_non_utf8_output_keeps_raw_bytes(self):
        result = self.run_workflow("large")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stderr without newline", result.stdout)
        self.assertTrue(self.log("stdout").endswith(b"x" * 200000 + b"\xff\npartial"))
        self.assertEqual(self.log("stderr"), b"stderr without newline")

    def test_missing_cmake_fails_without_success(self):
        (self.bin / "cmake").unlink()
        result = self.run_workflow()
        self.assertEqual(result.returncode, 127, result.stderr)
        self.assertIn("exit 127", result.stdout)
        self.assertNotIn("PASS", result.stdout)

    def test_init_workflow_composes_options_without_changing_generated_files(self):
        for index, flags in enumerate(((), ("--vcpkg",), ("--import-std",),
                                        ("--vcpkg", "--import-std"))):
            with self.subTest(flags=flags):
                case = self.root / str(index)
                plain = case / "plain"
                plain.mkdir(parents=True)
                environment = {**self.env, "TMPDIR": str(case)}
                baseline = run_cxx(plain, "init", "demo", "--no-git", *flags, env=environment)
                self.assertEqual(baseline.returncode, 0, baseline.stderr)
                self.assertEqual(list(case.glob("cxx-workflow-*")), [])
                result = run_cxx(case, "init", "demo", "--no-git", *flags,
                                 "--workflow", "san", env=environment)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("demo / san", result.stdout)
                self.assertIn("PASS", result.stdout)
                self.assertNotIn("Next:", result.stdout)
                self.assertNotIn("cd demo", result.stdout)
                self.assertNotIn("cmake --workflow --preset dev", result.stdout)
                logs = list(case.glob("cxx-workflow-*/stdout.log"))
                self.assertEqual(len(logs), 1, "must launch exactly one native workflow")
                invocation = json.loads(logs[0].read_text().splitlines()[0])
                self.assertEqual(invocation, {"argv": ["--workflow", "--preset", "san"],
                                             "cwd": str(case / "demo"),
                                             "probe": "unchanged environment"})
                expected = {p.relative_to(plain / "demo"): p.read_bytes()
                            for p in (plain / "demo").rglob("*") if p.is_file()}
                actual = {p.relative_to(case / "demo"): p.read_bytes()
                          for p in (case / "demo").rglob("*") if p.is_file()}
                self.assertEqual(actual, expected)

    def test_init_workflow_failure_keeps_project_and_prints_retry(self):
        for mode, expected in (("failure", 47), ("missing", 127)):
            with self.subTest(mode=mode):
                if mode == "missing":
                    (self.bin / "cmake").unlink()
                result = run_cxx(self.root, "init", mode, "--no-git", "--workflow", "release",
                                 env={**self.env, "CXX_FAKE_MODE": mode})
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertIn(f"Project kept: {self.root / mode}", result.stderr)
                self.assertIn(f"cd {mode} && cxx workflow release", result.stderr)
                self.assertNotIn("PASS", result.stdout)
                self.assertNotIn("Next:", result.stdout)
                self.assertTrue((self.root / mode / "src/main.cpp").is_file())

    def test_init_errors_never_launch_workflow(self):
        occupied = self.root / "occupied"
        occupied.mkdir()
        sentinel = occupied / "keep.txt"
        sentinel.write_text("user content")
        for args in (("demo", "--workflow"), ("demo", "--workflow", "unknown"),
                     ("../outside", "--workflow", "dev"),
                     ("occupied", "--workflow", "dev"),
                     ("git-fails", "--workflow", "dev")):
            with self.subTest(args=args):
                # PATH contains only fake CMake: the last case fails during git init.
                result = run_cxx(self.root, "init", *args, env=self.env)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn("Created C++ project:", result.stdout)
                self.assertEqual(list(self.root.glob("cxx-workflow-*")), [])
                self.assertFalse((self.root / "demo").exists())
                self.assertFalse((self.root / "git-fails").exists())
                self.assertEqual(sentinel.read_text(), "user content")

    @unittest.skipUnless(os.name == "posix", "POSIX signal exit convention")
    def test_child_signal_is_not_a_success(self):
        result = self.run_workflow("signal")
        self.assertEqual(result.returncode, 128 + signal.SIGTERM, result.stderr)
        self.assertNotIn("PASS", result.stdout)

    @unittest.skipUnless(os.name == "posix", "POSIX process-group cleanup")
    def test_cancel_reaps_even_signal_ignoring_descendants(self):
        for sig, init in ((signal.SIGINT, False), (signal.SIGTERM, False),
                          (signal.SIGINT, True), (signal.SIGTERM, True)):
            with self.subTest(signal=sig, init=init):
                name = f"cancel-{sig}"
                project = self.root / name if init else self.root
                pid_file = project / "child.pid"
                pid_file.unlink(missing_ok=True)
                args = ["init", name, "--no-git", "--workflow", "dev"] if init else ["workflow", "custom"]
                process = subprocess.Popen([sys.executable, str(CLI), *args],
                                           cwd=self.root, env={**self.env, "CXX_FAKE_MODE": "cancel"},
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    deadline = time.monotonic() + 5
                    while not pid_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(pid_file.exists(), "fake CMake failed to start")
                    child = int(pid_file.read_text())
                    process.send_signal(sig)
                    stdout, stderr = process.communicate(timeout=8)
                    self.assertEqual(process.returncode, 128 + sig, stdout + stderr)
                    self.assertIn("CANCELLED", stdout)
                    self.assertEqual(stdout.count("Logs     "), 1)
                    self.assertNotIn("PASS", stdout)
                    if init:
                        self.assertTrue((project / "src/main.cpp").is_file())
                        self.assertIn(f"cd {name} && cxx workflow dev", stderr)
                    # A killed orphan can briefly remain a zombie on Linux.
                    observed = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(child)],
                                              capture_output=True, text=True)
                    self.assertIn(observed.returncode, (0, 1), observed.stderr)
                    self.assertEqual(observed.stderr, "")
                    state = observed.stdout.strip()
                    self.assertTrue(not state or state.startswith("Z"), f"descendant still running: {state}")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=3)
                    if pid_file.exists():
                        try:
                            os.kill(int(pid_file.read_text()), signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_help_has_no_side_effects(self):
        result = run_cxx(self.root, "workflow", "--help", env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--verbose", result.stdout)
        self.assertIn("not an interactive application", " ".join(result.stdout.split()))
        self.assertEqual(list(self.root.glob("cxx-workflow-*")), [])

    @unittest.skipUnless(os.name == "posix", "PTY display contract")
    def test_real_tty_colors_and_no_color(self):
        import errno
        import fcntl
        import pty
        import select
        import struct
        import termios
        for no_color, term, width, verbose in ((False, "xterm-256color", 80, False),
                                               (False, "xterm-256color", 20, False),
                                               (True, "xterm-256color", 80, False),
                                               (False, "dumb", 80, False),
                                               (False, "xterm-256color", 80, True)):
            with self.subTest(no_color=no_color, term=term, width=width, verbose=verbose):
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, width, 0, 0))
                environment = {**self.env, "TERM": term, "COLUMNS": str(width)}
                if not no_color:
                    environment.pop("NO_COLOR", None)
                command = [sys.executable, str(CLI), "workflow", "custom"] + (["--verbose"] if verbose else [])
                process = subprocess.Popen(command,
                                           cwd=self.root, env=environment, stdout=slave, stderr=slave)
                os.close(slave)
                output = bytearray()
                try:
                    deadline = time.monotonic() + 5
                    while True:
                        self.assertLess(time.monotonic(), deadline, "PTY output did not complete")
                        if not select.select([master], [], [], 0.1)[0]:
                            continue
                        try:
                            chunk = os.read(master, 8192)
                        except OSError as error:
                            if error.errno == errno.EIO:
                                break
                            raise
                        if not chunk:
                            break
                        output.extend(chunk)
                    process.wait(timeout=5)
                finally:
                    os.close(master)
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                self.assertEqual(process.returncode, 0, output.decode())
                color = not no_color and term != "dumb"
                dynamic = color and not verbose
                self.assertEqual(b"\x1b[32m" in output, color)
                self.assertEqual(b"\x1b[2K" in output, dynamic)
                if not color:
                    self.assertNotIn(b"\x1b", output)
                # Replay only the emitted line-edit controls to inspect the final
                # scrollback, not just the presence of ANSI bytes in a recording.
                plain = re.sub(r"\x1b\[[0-9;]*m", "", output.decode())
                rows, row = [], ""
                for part in re.split(r"(\r\x1b\[2K|\r\n)", plain):
                    if part == "\r\x1b[2K":
                        self.assertLess(len(row), width, "transient row would wrap")
                        row = ""
                    elif part == "\r\n":
                        rows.append(row)
                        row = ""
                    else:
                        row += part
                screen = "\n".join(rows)
                for stage in ("Configure", "Build", "Test"):
                    self.assertEqual(screen.count(f"✓ {stage}"), 1, screen)
                self.assertEqual("> Configure" in screen, not dynamic)
                self.assertIn("important warning\n  source context\n  ^", screen)
                self.assertIn("stderr notice", screen)
                self.assertIn("1/1 passed", screen)
                self.assertIn("PASS", screen)
                self.assertEqual("Logs     " in screen, verbose)
                self.assertNotIn("exit 0", screen)
                self.assertNotRegex(screen, r"[\u4e00-\u9fff]")


@unittest.skipUnless(shutil.which("cmake") and shutil.which("ninja"), "requires native CMake/Ninja")
class NativeWorkflowTests(unittest.TestCase):
    def test_real_project_success_noop_and_failure_parity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = run_cxx(root, "init", "probe", "--no-git")
            self.assertEqual(generated.returncode, 0, generated.stderr)
            project = root / "probe"
            environment = {**os.environ, "TMPDIR": str(root)}
            # Inheritance, user presets and an environment macro are resolved
            # by CMake, never by cxx. No .cxx.toml is required at runtime.
            (project / ".cxx.toml").unlink()
            (project / "CMakeUserPresets.json").write_text(json.dumps({
                "version": 6,
                "configurePresets": [{"name": "local", "inherits": "dev",
                                      "environment": {"WORKFLOW_PROBE": "from-preset"},
                                      "cacheVariables": {"WORKFLOW_PROBE": "$env{WORKFLOW_PROBE}"}}],
                "buildPresets": [{"name": "local", "configurePreset": "local"}],
                "testPresets": [{"name": "local", "inherits": "dev", "configurePreset": "local"}],
                "workflowPresets": [{"name": "local", "steps": [
                    {"type": "configure", "name": "local"},
                    {"type": "build", "name": "local"}, {"type": "test", "name": "local"}]}],
            }))
            source = project / "src/main.cpp"
            source.write_text('#warning visible-compiler-warning\nint main() { return 0; }\n')
            cmake_file = project / "CMakeLists.txt"
            original = cmake_file.read_text()
            cmake_file.write_text(original + '\nmessage(STATUS "probe=${WORKFLOW_PROBE}")\n')
            result = run_cxx(project, "workflow", "local", env=environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("visible-compiler-warning", result.stdout)
            self.assertIn("1/1 passed", result.stdout)
            cache = (project / "build/local/CMakeCache.txt").read_text()
            self.assertIn("WORKFLOW_PROBE:UNINITIALIZED=from-preset", cache)
            self.assertTrue((project / "build/local/compile_commands.json").is_file())
            self.assertFalse((project / "build/dev").exists())
            result = run_cxx(project, "workflow", "local", env=environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("up to date", result.stdout)
            for kind, content in (("build", "this cannot compile"), ("test", "int main() { return 47; }"),
                                  ("configure", "int main() { return 0; }")):
                with self.subTest(kind=kind):
                    source.write_text(content)
                    if kind == "configure":
                        cmake_file.write_text(original + '\nmessage(FATAL_ERROR "configure-failure")\n')
                    native = subprocess.run(["cmake", "--workflow", "--preset", "local"], cwd=project,
                                            capture_output=True, text=True, env=environment)
                    displayed = run_cxx(project, "workflow", "local", env=environment)
                    self.assertNotEqual(native.returncode, 0)
                    self.assertEqual(displayed.returncode, native.returncode, displayed.stdout)
                    self.assertNotIn("PASS", displayed.stdout)
                    self.assertIn("FAIL", displayed.stdout)
            missing = run_cxx(project, "workflow", "does-not-exist", env=environment)
            self.assertNotEqual(missing.returncode, 0)
            self.assertNotIn("PASS", missing.stdout)


if __name__ == "__main__":
    unittest.main()
