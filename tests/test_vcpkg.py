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
from urllib.parse import unquote, urlparse

from clangd_lsp import collect_diagnostics, collect_evidence
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
              + 'static_assert(sizeof(toml::optional<int>) > 0);\n'
                'int main() {\n'
                '    const toml::table config = toml::parse("value = 42");\n'
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
    # The alias header is self-contained; table/parser rely on the umbrella's
    # include order. Exercise both boundaries through actual goto-definition.
    definitions = (("optional", 2, "impl/std_optional.hpp"),
                   ("table", 4, "impl/table.hpp"), ("parse", 4, "impl/parser.hpp"))
    evidence = collect_evidence(project, environment, [
        source, source.replace("return 0;", "return cxx_missing_symbol;"), source,
    ], definition_positions=[{"line": line, "character": source.splitlines()[line].index(f"toml::{symbol}") + 6}
                             for symbol, line, _ in definitions])
    normal, broken, restored = evidence["diagnostics"]
    test.assertFalse(any(item.get("severity") == 1 for item in normal + restored), normal + restored)
    test.assertTrue(any(item.get("severity") == 1 and "cxx_missing_symbol" in item["message"]
                        for item in broken), broken)
    include_roots = list((project / "build/dev/vcpkg_installed").glob("*/include/toml++"))
    test.assertEqual(len(include_roots), 1, include_roots)
    include_root = include_roots[0].resolve()
    test.assertEqual(len(evidence["definitions"]), len(definitions))
    for (symbol, _, header), locations in zip(definitions, evidence["definitions"]):
        test.assertTrue(locations, f"no definition for toml::{symbol}")
        for location in locations:
            target = Path(unquote(urlparse(location["uri"]).path)).resolve()
            test.assertEqual(target, include_root / header, location)
            start, end = location["range"]["start"], location["range"]["end"]
            test.assertEqual(start["line"], end["line"], location)
            text = target.read_text().splitlines()[start["line"]]
            test.assertEqual(text[start["character"]:end["character"]], symbol, location)
    test.assertEqual({Path(unquote(urlparse(uri).path)).resolve() for uri in evidence["headers"]},
                     {include_root / header for _, _, header in definitions})
    for uri, diagnostics in evidence["headers"].items():
        header = Path(unquote(urlparse(uri).path))
        with test.subTest(library_header=header.name):
            errors = [item for item in diagnostics if item.get("severity") == 1]
            if header.name == "std_optional.hpp":
                test.assertEqual(errors, [], (uri, diagnostics))
            else:
                # Pinned toml++ 3.4.0's date_time.hpp uses toml::optional without
                # including std_optional.hpp. Record this exact limitation, not
                # a blanket exemption for dependency errors or failed jumps.
                test.assertEqual(len(errors), 1, (uri, diagnostics))
                test.assertEqual(errors[0].get("code"), "no_template_suggest", errors)
                test.assertEqual(errors[0]["message"].splitlines()[0],
                                 "In included file: no template named 'optional'; did you mean 'std::optional'?")
                test.assertIn(f"{include_root}/impl/date_time.hpp:337:3:\n", errors[0]["message"])
            # Keep the actual installed files untouched. A fresh session avoids
            # treating stale include-preamble diagnostics as final evidence.
            content = header.read_text()
            normal, broken, restored = collect_diagnostics(project, environment, [
                content, content + "\nint cxx_header_probe = cxx_missing_header_symbol;\n", content,
            ], path=header)
            test.assertEqual([item for item in normal if item.get("severity") == 1], errors)
            test.assertEqual([item for item in restored if item.get("severity") == 1], errors)
            injected = [item for item in broken if item.get("severity") == 1
                        and item.get("code") == "undeclared_var_use"]
            test.assertEqual(len(injected), 1, broken)
            test.assertEqual(injected[0]["message"], "Use of undeclared identifier 'cxx_missing_header_symbol'")
            test.assertEqual([item for item in broken if item.get("severity") == 1 and item not in injected], errors)
            test.assertEqual(header.read_text(), content, "LSP probes must not modify dependency files")


class VcpkgTests(unittest.TestCase):
    def test_next_commands_preserve_vcpkg_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture_bin = root / "bin"
            fixture_bin.mkdir()
            cmake = fixture_bin / "cmake"
            cmake.write_text('#!/bin/sh\n'
                             'printf "%s\\n" "$VCPKG_ROOT"\n'
                             'test -f "$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake"\n')
            cmake.chmod(0o755)
            toolchain = root / "existing vcpkg/scripts/buildsystems/vcpkg.cmake"
            toolchain.parent.mkdir(parents=True)
            toolchain.touch()
            for index, value in enumerate((str(root / "existing vcpkg"), "/missing-vcpkg", None)):
                with self.subTest(vcpkg_root=value):
                    environment = {**os.environ, "PATH": str(fixture_bin) + os.pathsep + os.environ["PATH"]}
                    environment.pop("VCPKG_ROOT", None)
                    if value is not None:
                        environment["VCPKG_ROOT"] = value
                    result = run_cxx(root, "init", f"demo-{index}", "--vcpkg", "--no-git",
                                     env=environment)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    next_commands = result.stdout.split("Next:\n", 1)[1]
                    copied = subprocess.run(["/bin/sh", "-c", next_commands], cwd=root,
                                            env=environment, capture_output=True, text=True)
                    self.assertEqual(copied.stdout, (value or "") + "\n")
                    self.assertEqual(copied.returncode, 0 if index == 0 else 1, copied.stderr)
                    readme = (root / f"demo-{index}/README.md").read_text()
                    self.assertNotIn("/path/to/existing/vcpkg", result.stdout + readme)

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
                base = next(item for item in presets["configurePresets"] if item["name"] == "base")
                self.assertTrue(base["hidden"])
                cache = base["cacheVariables"]
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
