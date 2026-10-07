"""Opt-in real LSP checks; the same assertions also exercise an installed wheel."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from clangd_lsp import collect_diagnostics
from test_cxx import run_cxx


def verify_headers_diagnostics(test, project, environment):
    project = project.resolve()
    config = project / ".clangd"
    original = config.read_text()
    test.assertTrue(original.startswith("CompileFlags:\n  CompilationDatabase: build/dev\n\n---\n"))
    source = (project / "src/main.cpp").read_text()
    normal, broken, restored = collect_diagnostics(project, environment, [
        source, source.replace("return 0;", "return cxx_missing_symbol;"), source,
    ])
    for diagnostics in (normal, restored):
        test.assertEqual(diagnostics, [])
    test.assertTrue(any(item.get("severity") == 1 and "cxx_missing_symbol" in item["message"]
                        for item in broken), broken)
    indirect = '#include "bridge.hpp"\nProbeValue probe_value;\n'
    direct = '#include "value.hpp"\nProbeValue probe_value;\n'
    cases = (
        ("src/probe.cpp", True), ("include/probe.hpp", True),
        ("tests/probe.cpp", True), ("probe.cpp", True),
        ("vendor/probe.hpp", False), ("third_party/probe.hpp", False),
        ("vcpkg_installed/include/probe.hpp", False),
        ("build/dev/vcpkg_installed/include/probe.hpp", False),
    )
    for relative, strict in cases:
        with test.subTest(path=relative):
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            (path.parent / "value.hpp").write_text("#pragma once\nstruct ProbeValue {};\n")
            (path.parent / "bridge.hpp").write_text('#pragma once\n#include "value.hpp"\n')
            path.write_text(indirect)
            missing, fixed, broken = collect_diagnostics(
                project, environment,
                [indirect, direct, direct + "int broken = cxx_missing_symbol;\n"], path=relative,
            )
            test.assertEqual("missing-includes" in {item.get("code") for item in missing}, strict, missing)
            test.assertNotIn("missing-includes", {item.get("code") for item in fixed})
            test.assertFalse(any(item.get("severity") == 1 for item in missing + fixed), missing + fixed)
            test.assertTrue(any(item.get("severity") == 1 and "cxx_missing_symbol" in item["message"]
                                for item in broken), broken)
            # Prove an excluded header can trigger Include Cleaner: absence above
            # must come from the scope, not from failure to parse the header.
            if not strict:
                try:
                    config.write_text("CompileFlags:\n  CompilationDatabase: build/dev\n\n"
                                      "Diagnostics:\n  MissingIncludes: Strict\n")
                    control, = collect_diagnostics(project, environment, [indirect], path=relative)
                    test.assertIn("missing-includes", {item.get("code") for item in control}, control)
                finally:
                    config.write_text(original)
    test.assertEqual(config.read_text(), original)


class ClangdScopeTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("CXX_TEST_CLANGD") == "1",
                         "requires explicitly selected clangd diagnostics toolchain")
    def test_generated_headers_diagnostic_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = run_cxx(root, "init", "scope-demo", "--no-git")
            self.assertEqual(generated.returncode, 0, generated.stderr)
            project = root / "scope-demo"
            configured = subprocess.run(["cmake", "--preset", "dev"], cwd=project,
                                        capture_output=True, text=True)
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
            verify_headers_diagnostics(self, project, os.environ.copy())
