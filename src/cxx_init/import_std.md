# Experimental C++23 `import std`

This project keeps the normal app layout and dev/san/release workflows, but imports
the standard library as a named module. It never falls back to headers. Custom
named modules, partitions and header units are not part of this generated setup.

## Configure your existing toolchain

Verified: Apple Silicon macOS, Homebrew LLVM/libc++ 23.1.2, CMake 4.4.3 and Ninja
1.13.2. These are tested versions, not minimum-version promises. This path requires
macOS and upstream Clang (not AppleClang), libc++ module sources/metadata, Ninja,
and a CMake version that accepts the experimental gate. Its CMake minimum is 4.4;
the gate was checked with 4.4.3, so recheck it when upgrading CMake.

With those tools already installed, run in this project:

```sh
export CXX="$(brew --prefix llvm)/bin/clang++"
export CMAKE_CXX_STDLIB_MODULES_JSON="$(brew --prefix llvm)/lib/c++/libc++.modules.json"
cmake --workflow --preset dev
cmake --workflow --preset san
cmake --workflow --preset release
```

The presets pass the metadata environment variable into the CMake cache. Keep it
set when running workflows; no machine path is stored in the generated sources.
For a one-off configure you can also use
`cmake --preset dev -DCMAKE_CXX_STDLIB_MODULES_JSON=/your/path/libc++.modules.json`,
then the normal build/test presets. A later workflow reapplies the environment
input. Use a new build directory when switching compiler or incompatible flags.

Creation is offline and does not run these commands or install tools. Missing
metadata, an unsupported compiler, or an incompatible module build is an error.
The default `cxx init <name>` remains the conventional headers path.

## Editor and analysis limitations

Build dev before editing: clangd uses `build/dev/compile_commands.json` and its
CMake-generated BMI arguments. Use clangd from the same LLVM installation.

### clangd / Include Cleaner

With `Diagnostics.MissingIncludes: Strict`, clangd may report standard-library
symbols made visible by `import std;` as requiring their traditional headers.
This experimental project therefore sets `MissingIncludes: None` in its `.clangd`.
This disables missing-direct-header diagnostics for all headers in this project,
not compilation, ordinary semantic diagnostics or clang-tidy diagnostics.
`UnusedIncludes` is independent and is not changed. Do not add standard-library
includes just to satisfy this false positive.

- clangd completion may suggest redundant standard-library `#include` edits.
  Completion header insertion is separate from missing-include diagnostics.
- Do not enable `--experimental-modules-support` for this verified setup: the
  observed clangd-generated PCM had a C++20/C++23 configuration mismatch.
- Header insertion is not globally disabled; ordinary/third-party headers still
  benefit from it. No editor user configuration is changed.

### clang-tidy: shared policy versus module-source noise

`bugprone-exception-escape` may diagnose `main()` when operations such as
`std::println` can allow exceptions to escape. The same warning occurs with
`#include <print>`; it is a shared analysis policy, not an import-std regression.
Neither generation mode adds a catch-all or changes exception semantics to silence it.

Separately, clang-tidy can report diagnostics originating in libc++ module sources,
such as `std.cppm` and its included implementation files. Classify that noise
separately from application diagnostics. Checks have not been disabled.

### Validation boundaries

`clangd --check` is a static smoke test, not a complete editor/LSP acceptance test.
The real LSP diagnostics regression checks `publishDiagnostics`, the Strict/None
contrast, retained semantic errors and the shared exception warning. It does not
establish complete completion, indexing, navigation or rename coverage.

- CMake's experimental notice and module-name warnings may appear at configure
  or module compilation. They are not suppressed to suggest stable support.
- Broad navigation/rename behavior, Linux, Windows and other toolchains have not
  been validated for this capability.

Tool upgrades and BMI compatibility need fresh validation. This is an opt-in
experiment, not a general C++ Modules support claim.
