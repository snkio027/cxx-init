# AGENTS.md

## Mission

Build `cxx-init` as a small personal developer-experience tool.

Optimize for:

- clarity;
- low maintenance;
- fast local use;
- deterministic behavior;
- minimal dependencies;
- minimal generated code.

Do not optimize for hypothetical teams, plugin ecosystems, enterprise extensibility or broad framework reuse.

## Architecture authority

Read before implementation:

1. `docs/architecture.md`
2. `docs/implementation-plan.md`

If code and architecture conflict, stop and surface the conflict. Do not silently expand the architecture.

## Hard boundaries

Do not:

- create `cxx build`, `cxx test`, `cxx run`, or similar wrappers (except the
  explicitly approved `cxx workflow <preset>` presentation entry below);
- replace CMake with another build system;
- hard-code vcpkg or Conan into the base project;
- install host tools;
- modify shell configuration or global Git configuration;
- require network access during project creation;
- introduce a plugin system;
- introduce a general-purpose template language;
- add automatic migrations;
- add C++26 or C++ Modules to the default baseline;
- add ROS, CUDA, embedded or vendor-SDK abstractions to the base tool;
- add dependencies merely to avoid writing a small amount of straightforward code.

## Simplicity rule

Before adding an abstraction, ask:

> Does the current implementation already have at least two concrete, non-trivial cases that need it?

If not, prefer direct code.

Before adding a dependency, ask:

> Is this materially safer or simpler than a small standard-library implementation?

If not, do not add it.

Before adding a generated file, ask:

> Does a normal personal C++ project need this on day one?

If not, defer it.

## Current scope

Approved on 2026-10-07: add optional `cxx workflow <preset> [--verbose]`.
Delegate to one native `cmake --workflow --preset <preset>` process; CMake owns
presets, ordering, failure propagation and dependencies. Only presentation,
temporary logs and cancellation handling belong to this entry. Do not parse
presets, add a runner or alter generated projects.
Preserve warnings, native nonzero exits, raw logs and a usable non-TTY mode.

The owner subsequently authorized merge, publication and local activation on
2026-10-07. On 2026-10-08 the owner authorized v0.4.1 publication and local
activation: successful workflows omit log paths; failure, cancellation and verbose
output retain them. Generated projects, dependencies and init behavior stay unchanged.
Local activation upgrades only cxx-init; it does not upgrade the host toolchain.
The experimental
module capability remains limited to:

```text
experimental cxx init <name> --import-std
fixed specialization of the existing canonical fixture
explicit environment-supplied module metadata
corresponding documentation and black-box / installed-wheel verification
```

The release gate is:

```text
build wheel
install wheel into an isolated tool environment
cxx init (headers and explicit import-std)
dev / san / release configure, build, test
exact runtime output and compilation databases
import-std tooling checks on the verified macOS LLVM environment
explicit vcpkg checks with a compiled dependency, including import-std composition
existing Ubuntu and Trusted Publishing gates
```

Publishing requires explicit release authorization; never bypass failed gates or add credentials.
The approved dependency integration is explicit `cxx init <name> --vcpkg`,
including composition with `--import-std`. Preserve its dependency contract: offline
generation, unchanged default fixture, project-owned fixed baseline, existing
environment-supplied toolchain, no dependency wrappers. The workflow presentation
exception above does not change generation. Future releases require new authorization.
Do not introduce `--modules`, custom named modules, module partitions, header units or profiles.
Do not add `lib`, `header-only`, Homebrew, standalone binaries, self-update or auto-versioning.

## Implementation freedom

You may decide ordinary internal details such as:

- private function names;
- small module boundaries;
- error types;
- test helpers;
- filesystem helper implementation.

Do not independently change:

- CLI syntax;
- generated project structure;
- CMake architecture;
- project naming rules;
- side-effect model;
- default language baseline;
- template semantics.

## Change discipline

Keep patches narrow.

Prefer:

```text
one problem
one coherent change
one verification path
```

Do not combine unrelated cleanup with feature work.

Do not pre-build future layers.

## Verification

For generated projects, verify the artifact itself, not only generator unit tests.

The important path is:

```text
generate
  -> configure
  -> build
  -> test
```

A passing generator test with a broken generated project is a failure.
