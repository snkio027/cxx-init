"""Compare one formatting-only sample with its reviewed golden output."""

import difflib
import os
from pathlib import Path
import subprocess
import sys


root = Path(__file__).resolve().parents[1]
formatter = os.environ.get("CLANG_FORMAT", "clang-format")
config = root / "src/cxx_init/fixtures/canonical-app/.clang-format"
source = root / "tests/format/house_style.cpp"
golden = root / "tests/format/house_style.expected.cpp"

subprocess.run([formatter, "--version"], check=True)
result = subprocess.run(
    [formatter, f"--style=file:{config}", "--Werror", "--fail-on-incomplete-format", str(source)],
    capture_output=True, text=True,
)
if result.returncode:
    sys.stderr.write(result.stderr)
    sys.exit(result.returncode)

expected = golden.read_text()
if result.stdout != expected:
    sys.stderr.writelines(difflib.unified_diff(
        expected.splitlines(keepends=True), result.stdout.splitlines(keepends=True),
        fromfile=str(golden), tofile="clang-format output",
    ))
    sys.exit(1)

print("House style: PASS")
