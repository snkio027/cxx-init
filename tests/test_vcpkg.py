"""Explicit integration only: offline generation, real opt-in artifact checks."""

import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from clangd_lsp import collect_diagnostics
from test_cxx import CLI, run_cxx


BASELINE = "434307da09bc05b2c86996dccc8b2351fc0d5d37"


def verify_vcpkg_project(test, project, environment, *, import_std=False):
    """Add a test-only compiled library; never bake it into the generator."""
    project = project.resolve()
    def run(command):
        result = subprocess.run(command, cwd=project, env=environment,
                                capture_output=True, text=True)
        test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    manifest_path = project / "vcpkg.json"
    manifest = json.loads(manifest_path.read_text())
    test.assertEqual(manifest, {"builtin-baseline": BASELINE, "dependencies": []})
    run(["cmake", "--workflow", "--preset", "dev"])
    target = project.name.replace("-", "_")
    test.assertEqual(run([str(project / "build/dev" / target)]).stdout,
                     f"Hello from {project.name}!\n")
    # toml++'s vcpkg target uses a real archive (TOML_HEADER_ONLY=0), not just -I.
    manifest["dependencies"] = ["tomlplusplus"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    cmake = project / "CMakeLists.txt"
    cmake.write_text(cmake.read_text() + "\nfind_package(tomlplusplus CONFIG REQUIRED)\n"
                     f"target_link_libraries({target} PRIVATE tomlplusplus::tomlplusplus)\n")
    source = ('#include <toml++/toml.hpp>\n'
              + ('import std;\n' if import_std else '#include <iostream>\n')
              + 'int main() {\n'
                '    const auto config = toml::parse("value = 42");\n'
                '    std::cout << config["value"].value_or(0) << "\\n";\n'
                '    return 0;\n}\n')
    (project / "src/main.cpp").write_text(source)
    for preset in ("dev", "san", "release"):
        run(["cmake", "--workflow", "--preset", preset])
        build = project / "build" / preset
        result = run([str(build / target)])
        test.assertEqual(result.stdout, "42\n")
        test.assertEqual(result.stderr, "")
        entries = json.loads((build / "compile_commands.json").read_text())
        entry, = [item for item in entries if Path(item["file"]).resolve() == project / "src/main.cpp"]
        command = entry["command"]
        test.assertIn("TOML_HEADER_ONLY=0", command)
        test.assertIn("vcpkg_installed", command)
        test.assertEqual("-fsanitize=address,undefined" in command, preset == "san")
        test.assertTrue(list((build / "vcpkg_installed").glob("*/lib/libtomlplusplus.a")))
        test.assertEqual(any(Path(item["file"]).name == "std.cppm" for item in entries), import_std)
    normal, broken, restored = collect_diagnostics(project, environment, [
        source, source.replace("return 0;", "return cxx_missing_symbol;"), source,
    ])
    test.assertFalse(any(item.get("severity") == 1 for item in normal + restored), normal + restored)
    test.assertTrue(any(item.get("severity") == 1 and "cxx_missing_symbol" in item["message"]
                        for item in broken), broken)


class VcpkgTests(unittest.TestCase):
    def test_offline_generation_and_composition(self):
        for module in (False, True):
            with self.subTest(import_std=module), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                flags = ["--import-std"] if module else []
                result = run_cxx(root, "init", "demo", "--vcpkg", "--no-git", *flags,
                                 env={**os.environ, "VCPKG_ROOT": "/missing-vcpkg"})
                self.assertEqual(result.returncode, 0, result.stderr)
                project = root / "demo"
                self.assertIn("explicit vcpkg", result.stdout)
                self.assertEqual(json.loads((project / "vcpkg.json").read_text()),
                                 {"builtin-baseline": BASELINE, "dependencies": []})
                presets = json.loads((project / "CMakePresets.json").read_text())
                cache = presets["configurePresets"][0]["cacheVariables"]
                self.assertEqual(cache["CMAKE_TOOLCHAIN_FILE"],
                                 "$env{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake")
                self.assertEqual("CMAKE_CXX_STDLIB_MODULES_JSON" in cache, module)
                cmake = (project / "CMakeLists.txt").read_text()
                self.assertLess(cmake.index("vcpkg toolchain missing"), cmake.index("project(demo"))
                self.assertEqual("CXX_MODULE_STD ON" in cmake, module)
                self.assertIn('dependency_manager = "vcpkg"', (project / ".cxx.toml").read_text())
                self.assertIn("Creation was offline", (project / "README.md").read_text())
                self.assertFalse((project / "build").exists())
                self.assertNotIn(str(root), cmake)

        # Default output is exactly the canonical fixture, not a new vcpkg base.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_cxx(root, "init", "robot-runtime", "--no-git")
            self.assertEqual(result.returncode, 0, result.stderr)
            fixture = CLI.parent / "fixtures/canonical-app"
            expected = {path.relative_to(fixture): path.read_bytes()
                        for path in fixture.rglob("*") if path.is_file()}
            generated = {path.relative_to(root / "robot-runtime"): path.read_bytes()
                         for path in (root / "robot-runtime").rglob("*") if path.is_file()}
            self.assertEqual(generated, expected)

    def test_generation_does_not_probe_tools(self):
        namespace = runpy.run_path(str(CLI))
        cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                os.chdir(temporary)
                with patch("subprocess.run", side_effect=AssertionError("host process during generation")), \
                        patch("shutil.which", side_effect=AssertionError("host probe during generation")):
                    namespace["create_app"]("demo", use_git=False, import_std=True, vcpkg=True)
            finally:
                os.chdir(cwd)

    def test_missing_toolchain_fails_before_compiler_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_cxx(root, "init", "demo", "--vcpkg", "--no-git")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(["cmake", "--preset", "dev"], cwd=root / "demo",
                                    env={**os.environ, "VCPKG_ROOT": str(root / "missing")},
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("vcpkg toolchain missing", result.stderr)
            self.assertNotIn("compiler identification", result.stdout)
            self.assertFalse((root / "demo/build/dev/compile_commands.json").exists())

    def test_failed_specialization_preserves_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"
            shutil.copytree(CLI.parent, package)
            (package / "vcpkg.md").unlink()
            (root / "demo").mkdir()
            result = run_cxx(root, "init", "demo", "--vcpkg", "--no-git", executable=package / "cli.py")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list((root / "demo").iterdir()), [])
            self.assertEqual(set(root.iterdir()), {package, root / "demo"})

    @unittest.skipUnless(os.environ.get("CXX_TEST_VCPKG") == "1", "requires existing vcpkg and LLVM tools")
    def test_generated_vcpkg_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_cxx(root, "init", "deps-demo", "--vcpkg", "--no-git")
            self.assertEqual(result.returncode, 0, result.stderr)
            verify_vcpkg_project(self, root / "deps-demo", os.environ.copy())
