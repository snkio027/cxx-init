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
Its starter uses `<print>` and `std::println("Hello from hello!")`; the output
still ends with exactly one newline. `--import-std` uses the same call via `import std;`.

Upgrade or uninstall the tool with:

```bash
uv tool upgrade cxx-init
uv tool uninstall cxx-init
```

## Requirements

`cxx` requires Python 3.10 or newer. Newly generated projects require CMake 4.4.4 or newer,
Ninja, and a C++23 compiler/standard library providing `<print>` and `std::println`.
For example, [libc++ 18+](https://libcxx.llvm.org/Status/Cxx23.html) and
[libstdc++ 14+](https://gcc.gnu.org/gcc-14/changes.html) provide formatted output;
selecting `-std=c++23` alone does not add missing standard-library features.
The Ubuntu release gate explicitly selects CMake 4.4.4 and the runner's preinstalled `g++-14`.
Older standard libraries are not given an iostream fallback. Windows toolchains
remain unverified; GCC 14 on Windows additionally requires `-lstdc++exp`.

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
on Apple Silicon macOS with Homebrew LLVM/libc++ 23.1.2, CMake 4.4.4 and Ninja 1.13.2.
Verified versions are not a blanket compatibility promise. The opt-in shares the
CMake 4.4.4 minimum; its experimental gate must be rechecked when upgrading CMake.

The shared dev/san/release workflows, CTest and clang configs remain in use, with one
project-local exception: import-std sets `Diagnostics.MissingIncludes: None` because
Include Cleaner can falsely require textual standard-library headers. Headers projects
keep `Strict`; ordinary semantic diagnostics and clang-tidy remain enabled. Supply
metadata through the environment for each workflow; machine paths are not embedded in
the generated project. Creation stays offline and does not probe or install toolchains.
Unsupported tools or missing metadata fail at configure/build, with no headers fallback.

clangd may suggest redundant standard-library includes. Do not enable
`--experimental-modules-support` for the verified setup; its generated PCM showed a
configuration mismatch. clang-tidy may diagnose libc++ module sources; an exception-escape
warning for `main()` using `std::println` also occurs with headers and is not a module bug.
Neither mode changes exception semantics to silence that policy. The generated
[mode README](src/cxx_init/import_std.md) records setup and limitations. There is no
global editor change, general `--modules` option or custom module/partition generation.

The published **v0.2.0** artifact still generates `MissingIncludes: Strict` in both modes.
The project-local override is a v0.2.1 correction, not a
retroactive change to that release. Existing import-std projects can set `None` manually;
upgrading the generator never rewrites existing projects.

## Optional vcpkg integration

```sh
cxx init demo --vcpkg
# Or: cxx init demo --import-std --vcpkg
cd demo
# VCPKG_ROOT must point to your existing vcpkg checkout; keep it if already configured.
cmake --workflow --preset dev
```

If `VCPKG_ROOT` is not configured, export it to the **actual absolute path** of your
existing vcpkg checkout before running CMake. Do not replace a working value with
a placeholder path. The checkout must contain `scripts/buildsystems/vcpkg.cmake`.

This explicit option generates an empty manifest with a fixed builtin-registry
snapshot `434307da09bc05b2c86996dccc8b2351fc0d5d37`, a toolchain preset and a
configure-time guard. Add the libraries you need using their CMake targets.
No vcpkg installation, dependency acquisition or toolchain probing happens during
generation. CMake configure may download/build manifest dependencies; a missing
toolchain is an error, not an unmanaged fallback. The ordinary command's generated
files remain byte-for-byte unchanged. Existing projects are never rewritten.

The generated [vcpkg instructions](src/cxx_init/vcpkg.md) describe dependency,
baseline and compiler/ABI ownership. Combining this option with `--import-std`
retains the latter's platform and tooling restrictions; it is not broad library
or Modules portability certification.

## Generated project workflows

Each workflow configures, builds, and runs CTest:

| Command | Build type | ASan / UBSan | Directory |
| --- | --- | --- | --- |
| `cmake --workflow --preset dev` | Debug | Off | `build/dev` |
| `cmake --workflow --preset san` | Debug | On | `build/san` |
| `cmake --workflow --preset release` | Release | Off | `build/release` |

The configure step restores the preset's sanitizer setting even after a manual cache override.
`release` is a local optimized build, not a packaging or publishing command.

### CMake 4.4 structure

New projects use [CMake 4.4.4](https://cmake.org/cmake/help/v4.4/release/4.4.html)
and preset schema 12. This replaces the previous 3.25 minimum; older CMake versions
are no longer supported for new projects. Upgrading cxx-init does not migrate existing projects.

- A hidden configure `base` owns Ninja, compilation databases, SDK and shared options.
  `dev` and `release` inherit it independently; `san` specializes `dev`.
- `build/${presetName}` keeps each configuration (including inherited user presets)
  in its own directory. Toolchain and module metadata opt-ins extend `base`, not `dev`.
- C++23, warnings and sanitizers remain target-local. Header projects do not run
  module dependency scanning; only `--import-std` enables it and `CXX_MODULE_STD`.
- A hidden test `base` owns failure output, stop-on-failure and empty-suite failure.
  CTest chooses parallelism automatically; use `ctest --preset dev -j 4` or a
  user test preset's `execution.jobs` to override it (this field takes precedence
  over `CTEST_PARALLEL_LEVEL`).
- CMake 4.4's native Ninja test-preparation targets are enabled. To build only the
  dependencies of registered tests, then run them:

  ```sh
  cmake --preset dev
  cmake --build --preset dev --target test_prep/all
  ctest --preset dev
  ```

  `ctest` alone still does not build. The normal three-step workflows are unchanged.
  A fresh build directory configured with testing disabled remains buildable, but
  its test preset fails rather than reporting a false success for an empty suite.

### Terminal summary (v0.4.0)

Run from an existing project root:

```sh
cxx workflow dev
cxx workflow san
cxx workflow dev --verbose
```

This optional view executes exactly one `cmake --workflow --preset <preset>`.
CMake still owns presets, compilers, dependency installation, step ordering and
failure stopping. It does not rewrite projects or replace the native command.
Available starting with 0.4.0; earlier releases do not include this entry.

Example of the completed terminal view (timings vary):

```text
  demo / dev

  ✓ Configure      2.9s
  ✓ Build          0.0s  up to date
  ✓ Test           0.0s  1/1 passed

  PASS  3.0s
```

- The English UI uses a single live progress row and one permanent row per completed
  stage. Color is limited to status; timing and log paths are secondary. Different
  step preset names remain visible. Raw tool output is not translated.
- Redirected output, `NO_COLOR`, and `TERM=dumb` use append-only start/finish lines,
  without presentation escape sequences. `--verbose` also uses append-only output.
- Stderr is always shown; common stdout warnings/errors/notes retain nearby context.
  Unrecognized localized diagnostics may appear only in logs; use `--verbose` to
  stream all output. Diagnostics are never overwritten by the live progress row.
- Each run keeps complete raw bytes in separate `stdout.log` and `stderr.log` files.
  Successful summary runs omit the log path; failures, cancellation and `--verbose`
  show it. To locate a successful run's retained logs without rerunning the workflow,
  look under the system temporary directory for `cxx-workflow-*`.
  The OS may clean temporary directories; copy logs if needed and inspect them
  before sharing, as they may contain paths or program data. Failures also show the
  last 40 lines/fragments, the exact command and the native nonzero exit code.
- Ctrl-C returns 130 and cleans up the workflow's POSIX process group. Windows
  guarantees only direct-child termination.
- Stage times use received output boundaries and can be affected by child buffering;
  total time is measured directly. Unknown output formats do not change execution
  or exit status, and full output remains available in logs.
- This is not `cxx run`: CTest still controls successful test output. Run application
  executables directly or use Neovim's build/run entries for normal application use.

For source-only edits, use `cmake --build --preset dev`, followed by `ctest --preset dev`
when needed. A full workflow still configures; this view does not skip dependency
checks to appear faster.

The template fixes the project's editing baseline, including direct-include diagnostics
for headers projects and the documented import-std exception above.
Strict missing-include checking applies to `src/`, `include/`, `tests/`, and C/C++ files
directly in the project root. Other paths (including `build/`, `vendor/`, `third_party/`,
and `vcpkg_installed/`) do not opt into this check. Extend `.clangd`'s `PathMatch` if
your own sources live elsewhere; keep dependencies outside those owned-source paths.
This scopes the file being edited, not diagnostics originating from a library used by
your source. Library-specific public/internal-header issues still need library annotations
or a precise project-local workaround. Semantic diagnostics and clang-tidy remain active;
this policy neither suppresses all third-party errors nor makes internal headers self-contained.
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
5. No duplicate build policy; optional native-workflow presentation only.
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

Conan, C++26, custom Modules, ROS, CUDA, benchmarking and fuzzing remain deferred.

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

For the v0.5.0 release gate on the verified Mac toolchain, explicitly enable the
import-std and vcpkg artifact tests (otherwise they are reported as skipped, not verified).
`VCPKG_ROOT` must point to the existing tested vcpkg checkout:

```bash
export CXX="$(brew --prefix llvm)/bin/clang++"
export CMAKE_CXX_STDLIB_MODULES_JSON="$(brew --prefix llvm)/lib/c++/libc++.modules.json"
export CLANG_FORMAT="$(brew --prefix llvm)/bin/clang-format"
export CLANGD="$(brew --prefix llvm)/bin/clangd"
export CLANG_TIDY="$(brew --prefix llvm)/bin/clang-tidy"
uv build --no-sources
CXX_TEST_CLANGD=1 CXX_TEST_IMPORT_STD=1 CXX_TEST_VCPKG=1 \
CXX_TEST_DIST="$PWD/dist" CXX_RELEASE_TAG=v0.5.0 \
  python3 -m unittest discover -s tests -v
```

This tests the supplied wheel without rebuilding it. Both modes run all three
workflows with exact application output and real compilation database checks.
`CXX_TEST_CLANGD=1` additionally checks owned/third-party missing-include scope,
direct-include repair, and unsuppressed semantic errors through real LSP diagnostics
for both checkout-generated and installed-wheel headers projects.
The import-std path also checks formatting, static `clangd --check`, real LSP diagnostics
and clang-tidy. The import-std starter retains the existing `bugprone-exception-escape`
warning on `main`; no catch-all or suppression is generated. Its gate requires that
specific warning (and the LSP call-site note), rejects unrelated diagnostics and separately
classifies the observed libc++ `_Exit` reserved-identifier warning. Real LSP tests cover
the generated source, semantic-error injection and recovery in both source forms; the
headers LSP path is checked independently and produces no diagnostics in this environment.
The Ubuntu publishing workflow verifies the headers path with GCC 14; it does not
claim Linux import-std support. Do not release without the separate Mac gate.

### Tooling acceptance boundaries

The import-std capability remains **Forward-ready / experimental**, not a blanket
"tooling PASS". On the verified Mac toolchain, distinguish these layers:

| Layer | Evidence / gate | Boundary |
| --- | --- | --- |
| Build and runtime | Installed wheel, both modes, dev/san/release, exact output, compilation databases | No import-std portability claim |
| Static tooling | clang-format, `clangd --check`, classified clang-tidy diagnostics | Not an interactive LSP session |
| Real LSP diagnostics | `didOpen` / `didChange` / versioned `publishDiagnostics`, including failure and recovery | Strict has a known import-std false positive; project-local None mitigates it |
| Exception policy | `std::println` warns with both `import std` and `<print>` | Not module-specific; no generated catch-all |
| Hover / member completion / background index | Earlier exploratory observations, not covered by this diagnostics regression | Not a comprehensive or current release gate |
| Goto definition / rename | Not formally gated | No PASS claim |

The v0.2.0 static check result did not establish an editor-wide diagnostics PASS.
The real LSP regression is added after that release; it runs for both checkout and
installed-wheel import-std projects when `CXX_TEST_IMPORT_STD=1`.

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
