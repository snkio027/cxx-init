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

Dependency managers, C++26, Modules, ROS, CUDA, benchmarking and fuzzing are intentionally deferred.

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
