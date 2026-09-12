import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CLI = REPOSITORY_ROOT / "src" / "cxx_init" / "cli.py"


def run_cxx(working_directory, *arguments, executable=CLI, env=None):
    return subprocess.run(
        [sys.executable, str(executable), *arguments],
        cwd=working_directory,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


class CxxTests(unittest.TestCase):
    def test_reports_version(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = run_cxx(Path(temporary_directory), "--version")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "cxx 0.1.1\n")

    def test_rejects_the_previous_app_command(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)

            result = run_cxx(workspace, "app", "demo", "--no-git")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid choice: 'app'", result.stderr)
            self.assertFalse((workspace / "demo").exists())

    def test_generates_app_with_replaced_name_and_identifier(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)

            result = run_cxx(workspace, "init", "sensor-hub", "--no-git")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                "Created C++ project: sensor-hub\n\n"
                "Next:\n"
                "  cd sensor-hub\n"
                "  cmake --workflow --preset dev\n",
            )
            project = workspace / "sensor-hub"
            self.assertTrue((project / "CMakeLists.txt").is_file())
            self.assertFalse((project / "tests").exists())
            self.assertFalse((project / ".git").exists())
            self.assertIn("project(sensor_hub LANGUAGES CXX)", (project / "CMakeLists.txt").read_text())
            self.assertIn("Hello from sensor-hub!", (project / "src" / "main.cpp").read_text())
            self.assertEqual(
                (project / ".cxx.toml").read_text(),
                'schema = 1\ntemplate = "app"\nlanguage = "c++23"\n',
            )

            generated_text = "\n".join(
                generated_file.read_text()
                for generated_file in project.rglob("*")
                if generated_file.is_file()
            )
            self.assertNotIn("robot-runtime", generated_text)
            self.assertNotIn("robot_runtime", generated_text)

    def test_initializes_git_by_default(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)

            result = run_cxx(workspace, "init", "demo")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((workspace / "demo" / ".git").is_dir())

    def test_accepts_an_existing_empty_destination(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "demo").mkdir()

            result = run_cxx(workspace, "init", "demo", "--no-git")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((workspace / "demo" / "CMakeLists.txt").is_file())

    def test_git_repository_environment_cannot_redirect_initialization(self):
        variables = (
            "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        )
        for selected in (*((key,) for key in variables), variables):
            with self.subTest(variables=selected), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = root / "workspace"
                workspace.mkdir()
                outside = root / "outside"
                outside.mkdir()
                sentinel = outside / "keep.txt"
                sentinel.write_text("keep\n")
                config = root / "gitconfig"
                config.write_text('[init]\n\tdefaultBranch = personal\n[user]\n\tname = Test User\n')
                environment = {
                    key: value for key, value in os.environ.items() if not key.startswith("GIT_")
                }
                environment.update(GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM="1")
                environment.update({key: str(outside / key.lower()) for key in selected})

                result = run_cxx(workspace, "init", "demo", env=environment)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(list(outside.iterdir()), [sentinel])
                self.assertEqual(sentinel.read_text(), "keep\n")
                git_directory = workspace / "demo" / ".git"
                self.assertTrue((git_directory / "config").is_file())
                self.assertTrue((git_directory / "objects").is_dir())
                self.assertEqual((git_directory / "HEAD").read_text(), "ref: refs/heads/personal\n")
                self.assertNotIn("worktree", (git_directory / "config").read_text())
                self.assertFalse((git_directory / "commondir").exists())
                self.assertFalse((git_directory / "objects" / "info" / "alternates").exists())

    def test_rejects_reserved_cmake_identifiers_before_writing(self):
        for name in ("all", "help", "clean", "install", "preinstall", "test",
                     "rebuild-cache", "edit-cache"):
            for existing in (False, True):
                with self.subTest(name=name, existing=existing), tempfile.TemporaryDirectory() as tmp:
                    workspace = Path(tmp)
                    destination = workspace / name
                    if existing:
                        destination.mkdir()

                    result = run_cxx(workspace, "init", name, "--no-git")

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("reserved CMake target", result.stderr)
                    self.assertIn(name.replace("-", "_"), result.stderr)
                    self.assertEqual(list(workspace.iterdir()), [destination] if existing else [])
                    if existing:
                        self.assertEqual(list(destination.iterdir()), [])

    def test_rejects_invalid_names_without_creating_a_destination(self):
        invalid_names = ("Demo", "demo_app", "1demo", "demo/app", ".")

        for invalid_name in invalid_names:
            with self.subTest(name=invalid_name), tempfile.TemporaryDirectory() as temporary_directory:
                workspace = Path(temporary_directory)

                result = run_cxx(workspace, "init", invalid_name, "--no-git")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid project name", result.stderr)
                self.assertEqual(list(workspace.iterdir()), [])

    def test_rejects_a_nonempty_destination_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            destination = workspace / "demo"
            destination.mkdir()
            sentinel = destination / "keep.txt"
            sentinel.write_text("keep\n")

            result = run_cxx(workspace, "init", "demo", "--no-git")

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_text(), "keep\n")
            self.assertEqual(list(destination.iterdir()), [sentinel])

    def test_rejects_an_existing_file_destination(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            destination = workspace / "demo"
            destination.write_text("keep\n")

            result = run_cxx(workspace, "init", "demo", "--no-git")

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(destination.read_text(), "keep\n")

    def test_rejects_a_symbolic_link_destination(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            target = workspace / "target"
            target.mkdir()
            (workspace / "demo").symlink_to(target, target_is_directory=True)

            result = run_cxx(workspace, "init", "demo", "--no-git")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symbolic link", result.stderr)
            self.assertEqual(list(target.iterdir()), [])

    def test_reports_a_missing_bundled_fixture_without_creating_a_destination(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            isolated_executable = workspace / "cli.py"
            shutil.copy2(CLI, isolated_executable)

            result = run_cxx(workspace, "init", "demo", executable=isolated_executable)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("bundled app fixture is missing", result.stderr)
            self.assertFalse((workspace / "demo").exists())

    def test_generated_app_configures_builds_and_tests(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            generation = run_cxx(workspace, "init", "e2e-demo", "--no-git")
            self.assertEqual(generation.returncode, 0, generation.stderr)

            project = workspace / "e2e-demo"
            workflow = subprocess.run(
                ["cmake", "--workflow", "--preset", "dev"],
                cwd=project,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(workflow.returncode, 0, workflow.stdout + workflow.stderr)
            compilation_database = project / "build" / "dev" / "compile_commands.json"
            commands = json.loads(compilation_database.read_text())
            compiled_sources = {Path(command["file"]).resolve() for command in commands}
            self.assertEqual(compiled_sources, set((project / "src").resolve().rglob("*.cpp")))

            listing = subprocess.run(
                ["ctest", "--preset", "dev", "--show-only=json-v1"],
                cwd=project, capture_output=True, text=True,
            )
            self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
            tests = json.loads(listing.stdout)["tests"]
            self.assertEqual([test["name"] for test in tests], ["e2e_demo.smoke"])
            app = project / "build" / "dev" / ("e2e_demo.exe" if os.name == "nt" else "e2e_demo")
            self.assertEqual(Path(tests[0]["command"][0]).resolve(), app.resolve())
            properties = {item["name"]: item["value"] for item in tests[0]["properties"]}
            self.assertEqual(properties["TIMEOUT"], 10)

    def test_ctest_rejects_application_failures(self):
        overflow = (
            "volatile int value = std::numeric_limits<int>::max();\n"
            "    value = value + 1;\n"
            "    return 0;"
        )
        cases = (
            ("dev", "return 42;", "Hello from failure-demo!"),
            ("san", "return 42;", "Hello from failure-demo!"),
            ("release", "return 42;", "Hello from failure-demo!"),
            ("san", overflow, "runtime error: signed integer overflow"),
        )
        # Check the generated flags, not a caller's sanitizer runtime overrides.
        environment = {key: value for key, value in os.environ.items()
                       if key not in ("ASAN_OPTIONS", "UBSAN_OPTIONS")}
        for preset, replacement, diagnostic in cases:
            with self.subTest(preset=preset, replacement=replacement), tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp)
                generation = run_cxx(workspace, "init", "failure-demo", "--no-git")
                self.assertEqual(generation.returncode, 0, generation.stderr)
                project = workspace / "failure-demo"
                source = project / "src" / "main.cpp"
                source.write_text(
                    "#include <limits>\n" + source.read_text().replace("return 0;", replacement)
                )
                for command in (["cmake", "--preset", preset],
                                ["cmake", "--build", "--preset", preset]):
                    result = subprocess.run(command, cwd=project, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

                app = project / "build" / preset / (
                    "failure_demo.exe" if os.name == "nt" else "failure_demo"
                )
                execution = subprocess.run(
                    [str(app)], cwd=project, env=environment, capture_output=True, text=True,
                )
                self.assertNotEqual(execution.returncode, 0, execution.stdout + execution.stderr)
                self.assertIn(diagnostic, execution.stdout + execution.stderr)
                result = subprocess.run(
                    ["ctest", "--preset", preset], cwd=project, env=environment,
                    capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("failure_demo.smoke", result.stdout)
                self.assertIn(diagnostic, result.stdout + result.stderr)

    def test_workflows_restore_their_build_scenario(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            generation = run_cxx(workspace, "init", "preset-demo", "--no-git")
            self.assertEqual(generation.returncode, 0, generation.stderr)
            project = workspace / "preset-demo"
            clangd_config = (project / ".clangd").read_bytes()

            for preset, build_type, sanitizers in (
                ("dev", "Debug", False), ("san", "Debug", True), ("release", "Release", False),
            ):
                with self.subTest(preset=preset):
                    # A prior manual cache override must not change the next workflow's meaning.
                    seed = subprocess.run(
                        ["cmake", "--preset", preset,
                         f"-DENABLE_SANITIZERS={'OFF' if sanitizers else 'ON'}"],
                        cwd=project, capture_output=True, text=True,
                    )
                    self.assertEqual(seed.returncode, 0, seed.stdout + seed.stderr)
                    workflow = subprocess.run(
                        ["cmake", "--workflow", "--preset", preset],
                        cwd=project, capture_output=True, text=True,
                    )
                    self.assertEqual(workflow.returncode, 0, workflow.stdout + workflow.stderr)
                    build = project / "build" / preset
                    cache = dict(line.split("=", 1) for line in
                                 (build / "CMakeCache.txt").read_text().splitlines()
                                 if line.startswith(("CMAKE_BUILD_TYPE:", "ENABLE_SANITIZERS:")))
                    self.assertEqual(cache["CMAKE_BUILD_TYPE:STRING"], build_type)
                    self.assertIn(cache["ENABLE_SANITIZERS:BOOL"],
                                  ("ON", "TRUE", "1") if sanitizers else ("OFF", "FALSE", "0"))
                    commands = json.loads((build / "compile_commands.json").read_text())
                    for command in commands:
                        self.assertEqual(Path(command["directory"]).resolve(), build.resolve())
                        self.assertEqual("-fsanitize=address,undefined" in command["command"], sanitizers)
                        self.assertEqual("-fno-sanitize-recover=undefined" in command["command"], sanitizers)
                    self.assertEqual((project / ".clangd").read_bytes(), clangd_config)
                    self.assertFalse((project / "compile_commands.json").exists())


if __name__ == "__main__":
    unittest.main()
