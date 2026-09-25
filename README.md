# cxx-init

A small personal tool for creating clean, modern C++ projects without repeating the same setup work.

## Install

```bash
uv tool install cxx-init
```

Alternatively, use pipx:

```bash
pipx install cxx-init
```

## Create a project

```bash
cxx init hello
cd hello
cmake --workflow --preset dev
```

The generated project uses normal C++ tooling directly and does not depend on `cxx` after creation.

Upgrade or uninstall the tool with:

```bash
uv tool upgrade cxx-init
uv tool uninstall cxx-init
```

## Requirements

`cxx` requires Python 3.10 or newer. Generated projects require CMake 3.25 or newer,
Ninja, and a C++23 compiler.

## Experimental standard-library import

```bash
cxx init demo --import-std
cd demo
export CXX="$(brew --prefix llvm)/bin/clang++"
export CMAKE_CXX_STDLIB_MODULES_JSON="$(brew --prefix llvm)/lib/c++/libc++.modules.json"
cmake --workflow --preset dev
```

This opt-in replaces standard headers with C++23 `import std;`; the ordinary command
and its generated files are unchanged. It is **experimental**, currently verified only
on Apple Silicon macOS with Homebrew LLVM/libc++ 23.1.2, CMake 4.4.3 and Ninja 1.13.2.
Verified versions are not a blanket compatibility promise. The opt-in project's CMake
minimum is 4.4 and its experimental gate must be rechecked when upgrading CMake.

The shared dev/san/release workflows, CTest and clang configs remain in use. Supply
metadata through the environment for each workflow; machine paths are not embedded in
the generated project. Creation stays offline and does not probe or install toolchains.
Unsupported tools or missing metadata fail at configure/build, with no headers fallback.

clangd may suggest redundant standard-library includes. Do not enable
`--experimental-modules-support` for the verified setup; its generated PCM showed a
configuration mismatch. clang-tidy may diagnose libc++ module sources. The generated
[mode README](src/cxx_init/import_std.md) records setup and limitations. There is no
global editor change, general `--modules` option or custom module/partition generation.

## Generated project workflows

Each workflow configures, builds, and runs CTest:

| Command | Build type | ASan / UBSan | Directory |
| --- | --- | --- | --- |
| `cmake --workflow --preset dev` | Debug | Off | `build/dev` |
| `cmake --workflow --preset san` | Debug | On | `build/san` |
| `cmake --workflow --preset release` | Release | Off | `build/release` |

The configure step restores the preset's sanitizer setting even after a manual cache override.
`release` is a local optimized build, not a packaging or publishing command.

The template fixes the project's editing baseline, including direct-include diagnostics.
clangd always uses `build/dev/compile_commands.json`; running `san` or `release` does not switch it.
Configure `dev` before editing C++ files.

Choose a compiler before the first configure of each build directory. For example, on macOS:

```bash
CXX=/opt/homebrew/opt/llvm/bin/clang++ cmake --workflow --preset dev
```

CMake caches that choice; changing `CXX` later does not switch an already configured directory.
Use a separate build directory when comparing compilers. Machine-specific paths or SDK overrides
can be recorded in the ignored `CMakeUserPresets.json`; no extra config is needed for normal use.
If an explicit compiler experiment uses another compilation database, select it explicitly in
clangd as well. Project style and diagnostic preferences remain fixed in the template.

## Design priorities

1. Personal developer experience first.
2. Small, readable implementation.
3. Minimal generated files.
4. No hidden host mutation.
5. No build-system wrapper.
6. No network requirement during project creation.
7. Prefer boring, inspectable code over framework-heavy abstractions.

## Scope

The current product creates one canonical `app` project. Additional artifact types remain deferred
until real usage demonstrates a need for them:

```text
lib
header-only
```

Initial generated projects use:

```text
C++23
Modern target-centric CMake
CMake Presets / Workflow Presets
Ninja
clangd
clang-format
clang-tidy
CTest
ASan / UBSan where supported
compile_commands.json
```

Dependency managers, C++26, custom Modules, ROS, CUDA, benchmarking and fuzzing remain deferred.

## Repository documents

- `AGENTS.md` — rules for Codex and other coding agents.
- `docs/architecture.md` — architecture and boundaries.
- `docs/implementation-plan.md` — current implementation sequence.

## Development

Build the wheel and source distribution with:

```bash
uv build
```

Run the black-box test suite with:

```bash
python3 -m unittest discover -s tests -v
```

For the v0.2.0 release gate on the verified Mac toolchain, explicitly enable the
import-std artifact tests (otherwise they are reported as skipped, not verified):

```bash
export CXX="$(brew --prefix llvm)/bin/clang++"
export CMAKE_CXX_STDLIB_MODULES_JSON="$(brew --prefix llvm)/lib/c++/libc++.modules.json"
export CLANG_FORMAT="$(brew --prefix llvm)/bin/clang-format"
export CLANGD="$(brew --prefix llvm)/bin/clangd"
export CLANG_TIDY="$(brew --prefix llvm)/bin/clang-tidy"
uv build --no-sources
CXX_TEST_IMPORT_STD=1 CXX_TEST_DIST="$PWD/dist" CXX_RELEASE_TAG=v0.2.0 \
  python3 -m unittest discover -s tests -v
```

This tests the supplied wheel without rebuilding it. Both modes run all three
workflows with exact application output and real compilation database checks.
The import-std path also checks formatting, clangd and clang-tidy; only the observed
libc++ `_Exit` reserved-identifier warning is accepted. Application warnings still fail.
The unchanged Ubuntu publishing workflow verifies the headers path; it does not
claim Linux import-std support. Do not release without the separate Mac gate.

### House-style regression

The [canonical formatter configuration](src/cxx_init/fixtures/canonical-app/.clang-format)
is the single source of house-style rules; documentation does not keep a second copy.
Check the [formatting sample](tests/format/house_style.cpp) against its reviewed
[expected output](tests/format/house_style.expected.cpp) with the fixed clang-format 23.1.x baseline:

```bash
CLANG_FORMAT=/opt/homebrew/opt/llvm/bin/clang-format python3 tests/check_format.py
```

`CLANG_FORMAT` selects the executable; it defaults to `clang-format` on PATH. The check reports
the actual version, reads the canonical config explicitly, and fails on errors or output differences.
It never rewrites the sample or golden output. Review intentional style changes before updating either.

The sample covers include grouping, pointers/references, access labels, concepts/requires,
wrapped parameters/arguments, control flow, lambdas, namespaces, and long string literals.
It is formatting-only: the header names are not build dependencies. This explicit check is separate
from Python test discovery and wheel acceptance, which do not require a formatter.
