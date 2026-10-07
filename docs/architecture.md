# cxx-init Architecture

**Status:** Bootstrap baseline with approved workflow presentation (2026-10-07)
**Purpose:** Personal Modern C++ project bootstrap

## 1. Product definition

The `cxx-init` repository ships `cxx`, a small offline scaffolder with an optional
native-workflow presentation entry.

The job of `cxx init` remains:

```text
inputs
  -> create a clean project tree
  -> stop
```

The generated project then uses normal native tooling directly.

`cxx` is not a build system, package manager or environment manager. Projects remain
independent of it after generation.

## 2. Desired UX

Primary flow:

```bash
cxx init robot-runtime
cd robot-runtime
cmake --workflow --preset dev
```

Incremental development remains normal CMake/CTest:

```bash
cmake --build --preset dev
ctest --preset dev
```

There should be no `cxx build` abstraction.

### Approved exception: terminal workflow presentation

On 2026-10-07 the owner approved `cxx workflow <preset> [--verbose]` in response
to repeated dependency/configure noise obscuring the result of real daily builds.
This is an explicit amendment to the original no-wrapper rule, not permission
to introduce separate build/test/run/dependency commands.

The entry launches exactly one `cmake --workflow --preset <preset>` process in
the current directory, with the inherited environment. CMake alone loads/includes
presets, expands macros, chooses tools, orders steps, stops on failure and installs
manifest dependencies when its configured toolchain requires it. The entry must
not read/reimplement presets or change flags, targets, project files or templates.

Only these effects are added: concise stage/timing/result presentation, raw stdout
and stderr logs in a unique private temporary directory, and cancellation cleanup.
Presentation recognizes native stage markers opportunistically; an unknown output
format must not change execution or the final verdict. Only the native process
exit status decides success. Nonzero exits propagate; signals use 128 + signal.
Stage times reflect observed output boundaries, not compiler profiling measurements.

Stderr is always visible; common stdout diagnostics retain nearby context.
`--verbose` streams everything. Unknown/localized stdout diagnostics remain in the
raw logs and may require verbose mode. TTY status colors respect NO_COLOR; non-TTY
output has no presentation escape sequences. Cancellation forwards to the POSIX
process group and bounds cleanup; Windows only guarantees direct-child termination.
This is a workflow view, not an interactive application runner or a PTY replacement.

## 3. Base generated project

Production baseline:

```text
C++23
target-centric CMake
CMake Presets
CMake Workflow Presets
Ninja
compile_commands.json
clangd
clang-format
clang-tidy
CTest
warnings
ASan / UBSan profile where supported
```

The project should remain compiler-neutral even though Clang tooling is the preferred development tooling.

Expected compiler families over time:

```text
Clang
GCC
AppleClang
MSVC
```

## 4. Build truth

### Standard-library module adoption (v0.2)

`cxx init <name> --import-std` explicitly enables experimental C++23 standard-library
module adoption. The default command and its headers-based output remain unchanged.
This is not general Modules support: custom named modules, partitions, header units
and a general module project profile remain outside the generator contract.

The two paths share one canonical fixture, target graph, workflows and clang configuration,
except for the necessary project-local `MissingIncludes` override described below.
Fixed transformations introduce only the required module differences and a short generated
README. There is no second full template, profile engine, capability registry or fallback
to headers. Provenance adds `stdlib = "import-std"` only for the opt-in path.

The currently verified environment is macOS with Homebrew LLVM/libc++. The experimental
project requires upstream Clang on macOS; other environments are not silently accepted.
Metadata location is supplied through the preset's environment input
`CMAKE_CXX_STDLIB_MODULES_JSON`, never a generated host path. Toolchain validation happens
at configure/build, not via host probes or installation during project creation.

Verified versions are evidence, not universal minimum-version guarantees. The generated
project documents its version-specific CMake gate and known clangd/clang-tidy limitations.
Release testing must exercise both paths from an installed wheel on the supported Mac;
the existing Ubuntu headers release gate does not establish Linux import-std support.

Headers projects enable `Diagnostics.MissingIncludes: Strict` only for owned paths:
`src/`, `include/`, `tests/`, and root-level C/C++ files. The compilation database remains
unconditional. This is a missing-include policy, not blanket suppression of dependency
diagnostics or support for parsing non-self-contained internal headers. Projects may
adjust the owned paths or add precise library workarounds without changing build flags.
Import-std projects use
`None` because Include Cleaner can incorrectly require textual standard-library headers
for symbols provided by `import std;`. Only this project-local diagnostic is changed;
unused-include checking, semantic diagnostics, clang-tidy policy and exception semantics
remain shared. Do not add headers, global editor changes or a profile framework to mask
the issue. `bugprone-exception-escape` on `std::println` also occurs with headers and is
not a module-specific limitation. Any entry-point exception policy is a separate decision.

Distinguish compiler/build checks, command-line tooling and real editor/LSP validation.
`clangd --check` is a static smoke test; editor diagnostics require a real LSP session.
Passing either does not imply complete completion, indexing, navigation or rename coverage.

### Single source of build semantics

CMake owns build semantics.

```text
CMake target graph
      |
      v
compile_commands.json
      |
      v
clangd
```

`.clangd` may point clangd at the compilation database, but it must not duplicate include paths, defines, language mode or target flags that CMake already owns.

Prefer target-local CMake configuration:

```cmake
target_compile_features(...)
target_compile_options(...)
target_include_directories(...)
target_link_libraries(...)
```

Avoid directory-global build state when target-local configuration is sufficient.

## 5. Template model

The eventual base artifact types are:

```text
app
lib
header-only
```

They represent different artifact semantics, not cosmetic directory variants.

Implementation order is intentionally:

```text
app
 -> lib
 -> header-only
```

Do not create a generic template framework first.

### app

A minimal executable project.

It does not need a public `include/` directory by default.

### lib

A compiled library with public headers separated from implementation.

Use a namespaced CMake alias such as:

```text
robot_core::robot_core
```

### header-only

An interface library backed by public headers and tests.

## 6. Dependency boundary

The base project has:

```text
dependencies = none
```

This is intentional.

`cxx init <name> --vcpkg` is an approved explicit integration, not base architecture.
It composes with `--import-std` without creating a second canonical fixture or a profile engine.
Default output remains byte-for-byte unchanged. The opt-in adds an empty `vcpkg.json`,
a documented fixed builtin-registry baseline, the preset's environment-supplied toolchain,
a configure-time guard and short setup instructions. No libraries are preselected.

The initial baseline is the tested snapshot `434307da09bc05b2c86996dccc8b2351fc0d5d37`;
it is a reproducible starting point, not an implicit latest-version policy. The generated
manifest belongs to the project and baseline updates are explicit project changes.
`VCPKG_ROOT` selects an already installed toolchain; no machine paths are generated.
Missing toolchains fail before `project()`, with no silent unmanaged fallback. Package
restoration may access the network during CMake configure, never during `cxx init`.
Only CMake target dependencies reach clangd through the compilation database.
Compiler/triplet/ABI choices remain the project's responsibility; setting `CXX` for the
application is not a promise that vcpkg will build every dependency with the same compiler.

Conan remains deferred. There are no `cxx add`, dependency update commands, separate
build wrappers or automatic migrations. Optional workflow presentation does not
create another dependency owner.

Domain-native dependency systems remain domain-native:

```text
ROS 2 -> package.xml / rosdep / ament
vendor SDK -> vendor integration
embedded -> cross/vendor toolchain
```

## 7. Side-effect boundary

Normal project creation may only:

```text
create the destination tree
write project files
optionally run local `git init`
```

It must not:

```text
install tools
modify shell files
modify global Git configuration
download templates
clone dependencies
query registries
run generated code
```

Project creation must work offline.

If the destination already exists and is non-empty, fail instead of merging or overwriting.

## 8. Distribution boundary

`cxx` is distributed as a standard pure-Python package named `cxx-init`.

```text
wheel / source distribution
        -> isolated tool installation
        -> cxx executable
        -> bundled canonical fixture
```

Runtime dependencies remain empty. `uv_build` is a build dependency only.

The wheel must contain the canonical fixture so project creation remains offline after installation.
Package downloads belong to installation and upgrade, never to `cxx init`.
An explicitly invoked workflow may access the network through the project's native
CMake/toolchain steps; the presentation layer does not initiate downloads itself.

The initial distribution does not include standalone binaries, Homebrew packaging, an installer
script, self-update or automatic version management.

## 9. Naming

Initial project names use:

```text
[a-z][a-z0-9-]*
```

Example:

```text
robot-runtime
```

Canonical identifier:

```text
robot_runtime
```

Use the mapping consistently for CMake targets and C++ namespaces.

Do not invent multiple independent naming conversions.

## 10. Provenance

Generated projects should contain a tiny metadata file such as:

```text
.cxx.toml
```

Its purpose is observability only.

Example:

```toml
schema = 1
template = "app"
language = "c++23"
```

Normal builds must not depend on this file.

No automatic project migration is planned for the initial product.

## 11. What is intentionally deferred

Do not include these in the first implementation:

```text
Conan
C++26
custom C++ named modules, partitions, header units and general module profiles
ROS
CUDA
embedded profiles
cross compilation profiles
benchmarking
fuzzing
coverage systems
packaging/publishing
plugin architecture
remote templates
automatic migration
```

They can be reconsidered only after the base experience is proven.

## 12. Architecture test

A proposed feature should normally be rejected or deferred if it:

- creates another source of build truth;
- mutates the host;
- requires the network for project creation;
- makes every generated project larger for a niche use case;
- adds execution policy beyond the approved native-workflow presentation entry;
- exists only for hypothetical future extensibility.

The central rule is:

> Generate a good native C++ project, then get out of the way.
