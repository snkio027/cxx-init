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
Conan profile
better inspect command
release packaging
```

C++26, custom Modules, ROS and CUDA remain separate decisions.

## v0.2.0 — Experimental standard-library import

The approved addition is `cxx init <name> --import-std`, not `--modules`.
Preserve the default generated files byte-for-byte; reuse their fixture for the opt-in
path. It must fail clearly on unavailable metadata or unsupported toolchains, without
falling back, installing tools, changing host/editor configuration or introducing profiles.

Before release, run source regressions and install the candidate wheel into an isolated
tool environment. Validate both headers and import-std projects through dev/san/release,
CTest, exact output and compilation databases. For import-std, also run formatting,
clangd static checking and classified clang-tidy diagnostics with the verified Mac toolchain.
Keep a separate real LSP diagnostics regression in the installed-wheel gate: generated
import-std projects use project-local `MissingIncludes: None`, while headers retain `Strict`.
Check the Strict false positive, its disappearance with None, ordinary semantic errors,
diagnostic recovery after buffer repair, and the exception warning in both source forms.
Do not change source exception semantics or interpret static checking as full LSP coverage.
Keep existing version, fault-wheel, Ubuntu and Trusted Publishing gates. A successful
Ubuntu headers run must not be described as import-std portability verification.

## Approved DX increment — explicit vcpkg

Implement `--vcpkg` as a fixed specialization of the canonical app fixture, independently
composable with `--import-std`. Do not change default output, dependency ownership or the
side-effect boundary. The manifest begins empty with the architecture's tested baseline.
Generation must succeed without vcpkg installed and without invoking any host probe; a
missing toolchain must fail clearly at configure. A failed specialization must clean up
staging without overwriting an existing destination.

Keep generator/default regressions and installed-wheel checks. Opt-in integration checks
must add a real compiled dependency to a disposable generated project, then verify
dev/san/release builds, runtime output, CTest, compilation database and actual clangd
diagnostics. Exercise headers and import-std separately; do not infer combination support
from two isolated passing features. A test library is not a template dependency. Keep the
existing release gates and require separate release authorization.

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

## Approved DX increment — workflow presentation (2026-10-07)

Add only `cxx workflow <preset> [--verbose]`, delegating to a single native CMake
workflow. Keep generated projects, preset ownership, dependencies and init output
unchanged. Show stage progress, observed durations, native status, and raw log paths.
Retain stderr, stdout warning context, a verbose escape hatch, and plain non-TTY output.

Verify actual execution, not screenshots alone: native invocation/cwd/environment,
successful/no-op builds, warnings, configure/build/test failures, missing tools or
presets, arbitrary nonzero exits, cancellation/descendant cleanup, large and partial
output, raw logs, and installed-wheel invocation. Compare against native CMake on a
real generated project, including inherited presets and native failure stopping.
Check English output and real PTY scrollback at normal/narrow widths, including
diagnostics during progress, verbose mode, NO_COLOR and TERM=dumb fallbacks.
The initial increment stopped before merge/publication. On 2026-10-07 the owner
subsequently authorized merge, v0.4.0 publication and local cxx-init activation.
Run the complete Mac release gate and existing Ubuntu/Trusted Publishing workflow;
do not change generated projects or upgrade unrelated host tools.

On 2026-10-08 the owner authorized v0.4.1: omit log paths on ordinary success,
retaining raw logs and their location on failure, cancellation or verbose output.
Use the same complete release gates before publication and targeted local activation.

On 2026-10-08 the owner authorized closing the remaining approved updates. Release
v0.4.2 includes the previously approved println template: headers use `<print>`,
the explicit import-std specialization keeps `import std;`, and both use
`std::println` with the unchanged greeting. Verify the installed wheel's source
as well as runtime output so the old cout template cannot pass unnoticed. Require
the complete Mac gate and the existing Ubuntu/Trusted Publishing workflow with
GCC 14; do not rewrite existing projects or upgrade unrelated host tools.

## Approved DX increment — first workflow (2026-10-09)

Compose generation with the existing workflow view only when the owner supplies
`cxx init <name> --workflow <dev|san|release>`. Keep default output and generated
files unchanged. Do not infer or install compilers, tools or libraries. Document
environment/preset compiler selection, cache boundaries and vcpkg toolchain ownership.

Verify exactly one native invocation in the completed destination, inherited
environment, all existing generation-option combinations, generation failure before
execution, missing CMake, native nonzero status, cancellation and an actionable
retry without deleting the project. Extend the installed-wheel gate to actually
create and build through the new entry before the existing artifact checks.
Deliver through a PR; do not merge, publish or activate without further approval.

The owner gave that approval on 2026-10-09: merge the reviewed feature, release
v0.6.0 after the complete Mac and Ubuntu/Trusted Publishing gates, then activate
only cxx-init locally. Future owner-approved work follows the standing delivery
authorization recorded in AGENTS.md; scope expansion is not implicitly approved.
