import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from test_import_std import verify_import_std_project


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
UV = shutil.which("uv")


class WheelReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if UV is None:
            raise RuntimeError("uv is required for the installed-wheel release test")
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        root = Path(temporary.name)
        supplied_dist = os.environ.get("CXX_TEST_DIST")
        cls.tag = os.environ["CXX_RELEASE_TAG"] if supplied_dist is not None else "v0.2.0"
        cls.dist = Path(supplied_dist).resolve() if supplied_dist is not None else root / "dist"
        if supplied_dist is None:
            # Requires uv with a bundled backend compatible with pyproject.toml.
            result = subprocess.run(
                [UV, "build", "--no-sources", "--out-dir", str(cls.dist)],
                cwd=REPOSITORY_ROOT,
                env={**os.environ, "UV_CACHE_DIR": str(root / "cache"), "UV_OFFLINE": "1"},
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stdout + result.stderr)
        wheels = list(cls.dist.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"expected exactly one wheel in {cls.dist}, found {len(wheels)}")
        cls.wheel = wheels[0]

    def run_checked(self, command, *, cwd, env=None):
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def verify_wheel(self, wheel, tag, *, import_std=False):
        self.assertTrue(tag.startswith("v") and len(tag) > 1, "release tag must start with v")
        expected_version = tag[1:]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            environment = os.environ.copy()
            # The installed entry point must not import Python code from the checkout.
            for variable in ("PYTHONPATH", "PYTHONHOME"):
                environment.pop(variable, None)
            environment.update(
                {
                    "UV_CACHE_DIR": str(root / "uv-cache"),
                    "UV_NO_PROGRESS": "1",
                    "UV_OFFLINE": "1",
                    "UV_TOOL_BIN_DIR": str(root / "bin"),
                    "UV_TOOL_DIR": str(root / "tools"),
                }
            )

            self.run_checked(
                [UV, "tool", "install", "--python", sys.executable, str(wheel)],
                cwd=root,
                env=environment,
            )

            executable = root / "bin" / ("cxx.exe" if os.name == "nt" else "cxx")
            python = root / "tools" / "cxx-init" / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            metadata_version = self.run_checked(
                [str(python), "-I", "-c",
                 'from importlib.metadata import version; print(version("cxx-init"))'],
                cwd=root, env=environment,
            ).stdout.strip()
            self.assertEqual(metadata_version, expected_version, "distribution version differs from tag")
            version = self.run_checked([str(executable), "--version"], cwd=root, env=environment)
            self.assertEqual(version.stdout, f"cxx {expected_version}\n", "CLI version differs from tag")

            workspace = root / "workspace"
            workspace.mkdir()
            generation = self.run_checked(
                [str(executable), "init", "release-smoke", *(["--import-std"] if import_std else [])],
                cwd=workspace,
                env=environment,
            )
            self.assertIn("Created C++ project: release-smoke", generation.stdout)

            project = workspace / "release-smoke"
            self.assertTrue((project / ".git").is_dir())
            self.assertEqual(
                (project / ".cxx.toml").read_text(),
                'schema = 1\ntemplate = "app"\nlanguage = "c++23"\n'
                + ('stdlib = "import-std"\n' if import_std else ''),
            )

            if import_std:
                self.assertIn("import std [experimental]", generation.stdout)
                self.assertTrue((project / "README.md").is_file())
                verify_import_std_project(self, project, environment)
                return

            for preset in ("dev", "san", "release"):
                self.run_checked(["cmake", "--workflow", "--preset", preset], cwd=project)
                app = project / "build" / preset / (
                    "release_smoke.exe" if os.name == "nt" else "release_smoke"
                )
                output = self.run_checked([str(app)], cwd=project)
                self.assertEqual(output.stdout, "Hello from release-smoke!\n", "unexpected app output")
                commands = json.loads(
                    (project / "build" / preset / "compile_commands.json").read_text()
                )
                compiled_sources = {Path(command["file"]).resolve() for command in commands}
                self.assertEqual(compiled_sources, set((project / "src").resolve().rglob("*.cpp")))

    def test_installed_wheel_generates_a_working_project(self):
        self.verify_wheel(self.wheel, self.tag)

    @unittest.skipUnless(os.environ.get("CXX_TEST_IMPORT_STD") == "1",
                         "requires explicitly selected macOS LLVM import-std toolchain")
    def test_installed_wheel_generates_import_std_project(self):
        self.verify_wheel(self.wheel, self.tag, import_std=True)

    def test_distribution_contents(self):
        version = self.tag[1:]
        source_distribution = self.dist / f"cxx_init-{version}.tar.gz"
        fixture_root = REPOSITORY_ROOT / "src" / "cxx_init" / "fixtures" / "canonical-app"
        expected_fixture_files = {
            str(Path("cxx_init/fixtures/canonical-app") / path.relative_to(fixture_root))
            for path in fixture_root.rglob("*") if path.is_file()
        }
        dist_info = f"cxx_init-{version}.dist-info/"
        with zipfile.ZipFile(self.wheel) as archive:
            wheel_files = {item.filename for item in archive.infolist() if not item.is_dir()}
            metadata = archive.read(dist_info + "METADATA").decode()
            entry_points = archive.read(dist_info + "entry_points.txt").decode()
        self.assertEqual(expected_fixture_files, {
            path for path in wheel_files if path.startswith("cxx_init/fixtures/canonical-app/")
        })
        self.assertIn(dist_info + "licenses/LICENSE", wheel_files)
        self.assertIn("cxx_init/import_std.md", wheel_files)
        self.assertIn("License-Expression: MIT\n", metadata)
        self.assertIn("Requires-Python: >=3.10\n", metadata)
        self.assertNotIn("Requires-Dist:", metadata)
        self.assertEqual(entry_points.rstrip(), "[console_scripts]\ncxx = cxx_init.cli:main")
        with tarfile.open(source_distribution, "r:gz") as archive:
            source_files = {item.name for item in archive.getmembers() if item.isfile()}
        source_prefix = f"cxx_init-{version}/"
        self.assertEqual(
            {source_prefix + "src/" + path for path in expected_fixture_files},
            {path for path in source_files
             if path.startswith(source_prefix + "src/cxx_init/fixtures/canonical-app/")},
        )
        self.assertIn(source_prefix + "LICENSE", source_files)
        self.assertIn(source_prefix + "pyproject.toml", source_files)
        self.assertIn(source_prefix + "src/cxx_init/import_std.md", source_files)

    def test_gate_rejects_tags_without_v_and_mismatched_versions(self):
        for tag, message in (("0.2.0", "must start with v"),
                             ("v9.9.9", "distribution version differs from tag")):
            with self.subTest(tag=tag), self.assertRaisesRegex(AssertionError, message):
                self.verify_wheel(self.wheel, tag)

    def test_gate_rejects_broken_wheels(self):
        fixture = "cxx_init/fixtures/canonical-app/src/main.cpp"
        with zipfile.ZipFile(self.wheel) as archive:
            original = {name: archive.read(name) for name in archive.namelist()}
        metadata_path = next(name for name in original if name.endswith(".dist-info/METADATA"))
        source = original[fixture].decode()
        overflow = "#include <limits>\n" + source.replace(
            "return 0;", "volatile int value = std::numeric_limits<int>::max();\n"
            "    value = value + 1;\n    return 0;",
        )
        cases = (
            ("metadata", metadata_path, f"Version: {self.tag[1:]}\n", "Version: 9.9.9\n",
             "distribution version differs from tag"),
            ("cli", "cxx_init/cli.py", f'VERSION = "{self.tag[1:]}"', 'VERSION = "9.9.9"',
             "CLI version differs from tag"),
            ("exit", fixture, "return 0;", "return 42;", r"release_smoke\.smoke[^\n]*\*\*\*Failed"),
            ("output", fixture, "Hello from", "Goodbye from", "unexpected app output"),
            ("undefined", fixture, source, overflow, "runtime error: signed integer overflow"),
        )
        for case, path, old, new, message in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                contents = original.copy()
                self.assertIn(old.encode(), contents[path])
                contents[path] = contents[path].replace(old.encode(), new.encode())
                filename = self.wheel.name
                if case == "metadata":
                    # Keep the mutated wheel structurally valid, with matching dist-info and RECORD.
                    contents = {name.replace(f"cxx_init-{self.tag[1:]}.dist-info/",
                                             "cxx_init-9.9.9.dist-info/"): data
                                for name, data in contents.items()}
                    filename = filename.replace(f"cxx_init-{self.tag[1:]}-", "cxx_init-9.9.9-")
                record = next(name for name in contents if name.endswith(".dist-info/RECORD"))
                rows = io.StringIO()
                writer = csv.writer(rows)
                for name, data in contents.items():
                    if name != record:
                        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
                        writer.writerow((name, "sha256=" + digest.decode(), len(data)))
                writer.writerow((record, "", ""))
                contents[record] = rows.getvalue().encode()
                wheel = Path(temporary) / filename
                with zipfile.ZipFile(wheel, "w") as archive:
                    for name, data in contents.items():
                        archive.writestr(name, data)
                with self.assertRaisesRegex(AssertionError, message):
                    self.verify_wheel(wheel, self.tag)


if __name__ == "__main__":
    unittest.main()
