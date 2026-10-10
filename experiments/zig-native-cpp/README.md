# Zig native C++ feasibility prototype

**2026-10-10: experiment completed; production integration NO-GO.**

The owner approved an isolated prototype, not a new cxx backend or migration.
This directory is outside the packaged `src/cxx_init` tree. It does not change
the CMake default, CLI, dependency manager, release version, Neovim or daily setup.
The existing architecture remains authoritative for production.

## What is exercised

One native Zig graph: C++23 application -> static core -> compiled toml++ 3.4.0.
It uses `std.Build.Module`, native compile/link steps, a generated config header,
exported `.hpp` headers and native run/test steps. There is no CMake subprocess,
external compiler wrapper, dependency downloader or generated-project migration.

The application uses `<print>` / `std::println`. The core actually calls toml++
with `TOML_HEADER_ONLY=0`; the final executable resolves the transitive archive.
Changing the configuration bias from 2 to 7 changes the expected result from 42
to 47. This avoids the earlier tutorial's hard-coded expected-value ambiguity.

## Measured environment and result

Base: `c4c80bc5f58e87d8fccd2d3bcf1a6591096a7201`.
Both runs used Zig **0.17.0**, native ARM64 execution, and toml++ commit
`30172438cee64926dc41fdd9c11fb3ba5b2ba9de` (v3.4.0).

- macOS 26.7, build 25G229, clangd 23.1.2 (Homebrew).
- Ubuntu 26.04.1 / glibc 2.43, clangd 21.1.8, in an isolated ARM64 OrbStack
  container. This is real Linux compilation and execution, not cross-compilation
  alone. It does **not** establish x86_64, Ubuntu 24.04, musl or Windows support.
- Official Linux Zig archive SHA-256:
  `9e8d11661d4ae3bd57702a3832781e23ad151dde5798e16a5ccd503f65234ff8`.

| Gate | macOS | Linux |
| --- | --- | --- |
| Debug, ReleaseSafe, ReleaseFast: compile/link and exact-output test | PASS | PASS |
| Run arguments and deliberate exit 23 propagation | PASS | PASS |
| No-op: all three compilation steps cached | PASS | PASS |
| Private, public and generated header invalidation | PASS | PASS |
| Deliberate compiler error and failed native test propagate nonzero | PASS | PASS |
| Restored Debug graph and three real compilation records | PASS | PASS |
| Real clangd diagnostics, injected error, repair and goto-definition | PASS | PASS |
| Real `toml::par` completion includes `parse(...)` | PASS | PASS |
| Opening the returned toml++ internal definition without errors | FAIL | FAIL |
| Recreate missing compilation records on a cached build | FAIL | FAIL |
| UBSan: real signed overflow, diagnostic and abnormal termination | PASS | PASS |
| ASan: link and detect a real heap bounds violation | FAIL | FAIL |

The executable harness has **20 gates: 17 PASS / 3 FAIL on each platform**.
It deliberately returns **1**, not green, while any feasibility gate fails.
`evidence.json` records versions, individual verdicts and source/log hashes.
Existing production generator/CMake tests also passed: **18/18** (`test_cxx.py`).
No claim is made that the production release gate or remote CI ran this prototype.

## Findings that block integration

### 1. Compilation records are observable, but not cache-safe outputs

Clang `-MJ` captures the actual expanded arguments, including Zig's libc++ paths,
macOS SDK / Linux include paths, target, language and macro settings. The probe
assembles the three JSON fragments **without rewriting their arguments**. clangd
successfully uses them; no duplicate build flags are placed in `.clangd`.

However, these fragments are compiler side effects, not registered Zig graph
outputs. Delete them and run the same successful cached build: none are restored.
Different configurations can also overwrite a shared fragment directory. The
harness uses a fresh recording directory to capture an unambiguous Debug graph
before testing LSP, then explicitly reproduces the deletion/cache failure.

This is not a production `compile_commands.json` exporter. A future integration
needs a version-compatible graph-aware exporter with cache/configuration and
removed-source handling. Do not fix this by rebuilding everything on editor open
or duplicating flags in Neovim.

### 2. ASan instrumentation does not supply its runtime

`-fsanitize=address` instruments the C++ objects, but the tested native link fails:
`__asan_init`, `__asan_report_store4` and related symbols are unresolved on both
platforms. No ASan-instrumented executable was run successfully.

This is a limitation of the tested self-contained path, not proof that every
external-runtime integration is impossible. Adding host-specific Clang runtimes
would create a new compatibility/ownership obligation and is not done here.
UBSan does work: Zig's runtime reports signed integer overflow and the application
terminates with ABRT. `sanitizer=none` means no **additional** flags; it does not
disable Zig's native Debug safety defaults. ReleaseSafe is not an ASan substitute.

### 3. Changing the build system does not fix non-self-contained library headers

Both real LSP sessions locate `toml::parse`, then open its returned `parser.hpp`
in the same client. Both reproduce `date_time.hpp:337: no template named 'optional'`.
The application translation unit itself has no semantic errors, rejects an injected
unknown type and recovers after repair. The separate completion probe waits for
versioned diagnostics before asking for candidates; an immediate request can use
clangd's preamble-not-ready fallback.

The existing toml++ internal-header boundary therefore remains. No global forced
include, diagnostic suppression or single-library editor rule is added. The native
header-export API also places the definition under `.zig-cache/o/.../toml++/`;
source-location ergonomics would need attention before editor integration.

## Reproduce

Use installed Zig 0.17.0, Python 3.10+, Git and clangd. Download dependencies
explicitly into an isolated directory; the build and verifier do not fetch them.
Run from the repository root:

```sh
lab=$(mktemp -d)
git clone --branch v3.4.0 --depth 1 https://github.com/marzer/tomlplusplus.git "$lab/tomlplusplus"
git -C "$lab/tomlplusplus" checkout --detach 30172438cee64926dc41fdd9c11fb3ba5b2ba9de
python3 experiments/zig-native-cpp/verify.py \
  --toml "$lab/tomlplusplus" --output "$lab/result" \
  --zig /absolute/path/to/zig --clangd /absolute/path/to/clangd
```

`--output` must not exist. The verifier copies the fixture there, mutates only that
copy for fault injection, restores sources, bounds processes, and retains logs,
the compilation database, LSP observations and `results.json`. Zig's global cache
is placed beside the result directory. The output is platform/path-specific and
must be regenerated, not moved to another machine for use as a live project.

To try only the native graph, from this directory with an existing toml++ checkout:

```sh
zig build run -Dtoml=/absolute/path/to/tomlplusplus -- 42
zig build test -Dtoml=/absolute/path/to/tomlplusplus
zig build test -Dtoml=/absolute/path/to/tomlplusplus -Dbias=7
zig build test -Dtoml=/absolute/path/to/tomlplusplus -Doptimize=ReleaseFast
```

## Decision boundary

Keep this as an experiment. Do not add `--build-system zig`, migrate existing
projects, change daily Neovim commands, publish a cxx release or replace the CMake
default on the strength of these results. vcpkg ABI compatibility, debugger UX,
package discovery, import-std and comparative performance were not validated.

Any next increment should first resolve the compilation-database lifecycle and
ASan runtime strategy within an explicitly approved maintenance budget. The
internal-header issue is independent and should not be advertised as a Zig benefit.
