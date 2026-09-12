# Implementation Plan

This plan intentionally starts small.

Do not implement future extensibility before the basic developer experience is proven.

## Milestone 0 — Repository baseline

Keep only the minimum project documentation and source/test structure required by the chosen implementation language.

Do not add CI, release automation or packaging until there is executable behavior worth validating.

Exit condition:

- architecture is readable;
- first implementation task is unambiguous.

## Milestone 1 — Canonical app template

Build one C++ application template manually before writing general generator logic.

Expected project shape should stay small, roughly:

```text
CMakeLists.txt
CMakePresets.json
.clangd
.clang-format
.clang-tidy
.gitignore
.cxx.toml
src/main.cpp
```

CTest runs the app directly with a short timeout; no placeholder test executable is needed.
Add a `tests/` directory when there is real test code, not as an initial empty directory.
Avoid helper CMake modules unless they remove real duplication or isolate compiler-specific logic.

Required validation:

```bash
cmake --workflow --preset dev
```

Where supported:

```bash
cmake --workflow --preset san
```

Also verify:

```text
compile_commands.json exists
CTest runs the app and rejects nonzero exits
san rejects undefined behavior instead of reporting it and continuing
clangd can consume the development compilation database
```

Do not implement `lib` or `header-only` yet.

## Milestone 2 — Minimal generator

Implement only what is needed to instantiate the proven app template:

```text
parse command
validate project name
derive canonical identifier
check destination
copy/render files
write provenance
optionally git init
report next command
```

Generation must be offline.

Prefer simple token replacement over a template framework.

Required command:

```bash
cxx init <name>
```

Optional:

```bash
--no-git
```

Nothing else is required.

Generator tests must cover invalid names, unsafe or occupied destinations, missing fixture data and
failure cleanup. A failed generation must not overwrite existing user files.

## Milestone 3 — Packaging and v0.1.0

Package the proven generator as a standard pure-Python distribution:

```text
PyPI package: cxx-init
CLI command:  cxx
version:      0.1.0
runtime deps: none
```

The wheel must bundle the canonical fixture under the Python module. Add `cxx --version`, an MIT
license and installation documentation without changing generator behavior.

Required release validation:

```text
uv build
 -> install the built wheel into an isolated tool environment
 -> cxx --version
 -> cxx init release-smoke
 -> configure
 -> build
 -> test
```

The first packaging change stops after the installed-wheel gate passes. PyPI project creation,
Trusted Publishing and the GitHub release workflow require a separate approved step.

## Milestone 4 — Add library template

Only after the app flow is stable.

The command shape for creating a library is intentionally undecided until real usage demonstrates
the need.

The library must have real library semantics:

```text
public headers
compiled implementation
namespaced CMake alias
consumer test
```

Do not redesign the generator unless the library exposes a concrete problem in the existing implementation.

## Milestone 5 — Add header-only template

The command shape for creating a header-only library is also intentionally undecided.

Use CMake interface-library semantics.

Again, extend the existing implementation narrowly.

## After v0.1

Evaluate actual personal usage before adding features.

Potential next additions, only if they solve observed friction:

```text
vcpkg profile
Conan profile
better inspect command
release packaging
```

C++26, Modules, ROS and CUDA remain separate decisions.

## v0.1 Definition of Done

The project is successful when:

```bash
uv tool install cxx-init
cxx --version
cxx init demo
cd demo
cmake --workflow --preset dev
```

works predictably, the generated project is pleasant to edit, and the implementation is small enough to understand in one sitting.

The goal is not feature count.

The goal is removing repetitive C++ project setup without creating a new layer of tooling complexity.
