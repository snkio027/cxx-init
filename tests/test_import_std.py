import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from test_cxx import CLI, run_cxx


def verify_import_std_project(test, project, environment):
    """Exercise the same artifact contract for checkout and installed-wheel tests."""
    project = project.resolve()
    test.assertTrue((project / "src/main.cpp").read_text().startswith("import std;\n"))
    def run(command):
        result = subprocess.run(command, cwd=project, env=environment,
                                capture_output=True, text=True)
        test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    name = project.name
    for preset in ("dev", "san", "release"):
        run(["cmake", "--workflow", "--preset", preset])
        build = project / "build" / preset
        output = run([str(build / name.replace("-", "_"))])
        test.assertEqual(output.stdout, f"Hello from {name}!\n")
        test.assertEqual(output.stderr, "")
        commands = json.loads((build / "compile_commands.json").read_text())
        app_commands = [entry for entry in commands
                        if Path(entry["file"]).resolve() == project / "src/main.cpp"]
        test.assertEqual(len(app_commands), 1)
        command = app_commands[0]["command"]
        test.assertIn("-std=c++23", command)
        test.assertEqual("-fsanitize=address,undefined" in command, preset == "san")
        test.assertEqual("-fno-sanitize-recover=undefined" in command, preset == "san")
        test.assertTrue(any(Path(entry["file"]).name == "std.cppm" for entry in commands))
        # CMake owns the BMI map, which must refer to a built std BMI.
        response = next(arg[1:] for arg in shlex.split(command) if arg.startswith("@"))
        module_flags = shlex.split((build / response).read_text())
        bmi = next(arg.split("=", 2)[2] for arg in module_flags
                   if arg.startswith("-fmodule-file=std="))
        test.assertTrue((build / bmi).is_file())

    run([environment.get("CLANG_FORMAT", "clang-format"), "--dry-run", "--Werror",
         "--style=file", "src/main.cpp"])
    run([environment.get("CLANGD", "clangd"), "--check=src/main.cpp",
         "--compile-commands-dir=build/dev", "--enable-config"])
    tidy = run([environment.get("CLANG_TIDY", "clang-tidy"), "src/main.cpp",
                "-p", "build/dev", "--config-file=.clang-tidy"])
    # Do not suppress checks: only the observed libc++ module diagnostic is allowed.
    warnings = re.findall(r"^.+:\d+:\d+: warning: .+$", tidy.stdout + tidy.stderr, re.M)
    for warning in warnings:
        test.assertIn("/std/cstdlib.inc:", warning, tidy.stdout + tidy.stderr)
        test.assertIn("'_Exit'", warning)
        test.assertIn("[bugprone-reserved-identifier]", warning)


class ImportStdTests(unittest.TestCase):
    def test_shared_fixture_and_explicit_experimental_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plain = run_cxx(root, "init", "headers-demo", "--no-git")
            std = run_cxx(root, "init", "std-demo", "--import-std", "--no-git")
            self.assertEqual(plain.returncode, 0, plain.stderr)
            self.assertEqual(std.returncode, 0, std.stderr)
            self.assertIn("import std [experimental]", std.stdout)
            self.assertIn("macOS + Homebrew LLVM", std.stdout)
            self.assertIn("CMAKE_CXX_STDLIB_MODULES_JSON", std.stdout)
            self.assertNotIn("experimental", plain.stdout)
            headers, modules = root / "headers-demo", root / "std-demo"
            fixture = CLI.parent / "fixtures/canonical-app"
            expected = {path.relative_to(fixture) for path in fixture.rglob("*") if path.is_file()}
            self.assertEqual({path.relative_to(headers) for path in headers.rglob("*")
                              if path.is_file()}, expected)
            self.assertEqual({path.relative_to(modules) for path in modules.rglob("*")
                              if path.is_file()}, expected | {Path("README.md")})
            for relative in expected:
                self.assertEqual((headers / relative).read_text(), (fixture / relative).read_text()
                                 .replace("robot-runtime", "headers-demo")
                                 .replace("robot_runtime", "headers_demo"))
            for relative in (".clangd", ".clang-tidy", ".clang-format", ".gitignore"):
                self.assertEqual((headers / relative).read_bytes(), (modules / relative).read_bytes())
            source = (modules / "src/main.cpp").read_text()
            self.assertTrue(source.startswith("import std;\n"))
            self.assertNotIn("#include", source)
            self.assertIn('stdlib = "import-std"', (modules / ".cxx.toml").read_text())
            for path in modules.rglob("*"):
                if path.is_file():
                    self.assertNotIn("/opt/homebrew", path.read_text())
            self.assertFalse((modules / ".git").exists())

    def test_no_toolchain_probe_at_generation_and_no_fallback_at_configure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {**os.environ, "PATH": "", "CXX": "/missing/compiler"}
            result = run_cxx(root, "init", "demo", "--import-std", "--no-git", env=environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            project = root / "demo"
            source = (project / "src/main.cpp").read_bytes()
            environment = {**os.environ, "CMAKE_CXX_STDLIB_MODULES_JSON": str(root / "missing.json")}
            result = subprocess.run(["cmake", "--preset", "dev"], cwd=project,
                                    env=environment, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("import std requires libc++.modules.json", result.stdout + result.stderr)
            self.assertEqual((project / "src/main.cpp").read_bytes(), source)

    def test_rejects_modules_and_unsafe_destinations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_cxx(root, "init", "demo", "--modules", "--no-git")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(root.iterdir()), [])
            result = run_cxx(root, "init", "edit-cache", "--import-std", "--no-git")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(root.iterdir()), [])
            (root / "demo").mkdir()
            (root / "demo/keep").write_text("keep")
            result = run_cxx(root, "init", "demo", "--import-std", "--no-git")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / "demo/keep").read_text(), "keep")

    def test_missing_mode_document_cleans_staging_and_preserves_empty_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            isolated = root / "package"
            shutil.copytree(CLI.parent, isolated)
            (isolated / "import_std.md").unlink()
            (root / "demo").mkdir()
            result = run_cxx(root, "init", "demo", "--import-std", "--no-git",
                             executable=isolated / "cli.py")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list((root / "demo").iterdir()), [])
            self.assertEqual(set(root.iterdir()), {root / "demo", isolated})

    @unittest.skipUnless(os.environ.get("CXX_TEST_IMPORT_STD") == "1",
                         "requires explicitly selected macOS LLVM import-std toolchain")
    def test_generated_import_std_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_cxx(root, "init", "std-demo", "--import-std")
            self.assertEqual(result.returncode, 0, result.stderr)
            project = root / "std-demo"
            self.assertTrue((project / ".git").is_dir())
            verify_import_std_project(self, project, os.environ.copy())

    @unittest.skipUnless(os.environ.get("CXX_TEST_IMPORT_STD") == "1",
                         "requires explicitly selected macOS LLVM import-std toolchain")
    def test_import_std_rejects_appleclang_and_runtime_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_cxx(root, "init", "failure-demo", "--import-std", "--no-git")
            self.assertEqual(result.returncode, 0, result.stderr)
            project = root / "failure-demo"
            rejected = subprocess.run(
                ["cmake", "-S", ".", "-B", "build/appleclang", "-G", "Ninja",
                 "-DCMAKE_CXX_COMPILER=/usr/bin/clang++",
                 "-DCMAKE_CXX_STDLIB_MODULES_JSON=" + os.environ["CMAKE_CXX_STDLIB_MODULES_JSON"]],
                cwd=project, capture_output=True, text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("requires macOS and upstream Clang/libc++",
                          rejected.stdout + rejected.stderr)
            source = project / "src/main.cpp"
            original = source.read_text()
            for preset, code, diagnostic in (
                ("dev", "return 42;", "Hello from failure-demo!"),
                ("san", "return 42;", "Hello from failure-demo!"),
                ("release", "return 42;", "Hello from failure-demo!"),
                ("san", "volatile int value = std::numeric_limits<int>::max();\n"
                 "    value = value + 1;\n    return 0;", "runtime error: signed integer overflow"),
            ):
                with self.subTest(preset=preset, code=code):
                    source.write_text(original.replace("return 0;", code))
                    environment = {key: value for key, value in os.environ.items()
                                   if key not in ("ASAN_OPTIONS", "UBSAN_OPTIONS")}
                    for command in (["cmake", "--preset", preset],
                                    ["cmake", "--build", "--preset", preset]):
                        result = subprocess.run(command, cwd=project, env=environment,
                                                capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    result = subprocess.run(["ctest", "--preset", preset], cwd=project,
                                            env=environment, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(diagnostic, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
