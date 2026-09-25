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

- clangd completion may suggest redundant standard-library `#include` edits.
- Do not enable `--experimental-modules-support` for this verified setup: the
  observed clangd-generated PCM had a C++20/C++23 configuration mismatch.
- Header insertion is not globally disabled; ordinary/third-party headers still
  benefit from it. No editor user configuration is changed.
- clang-tidy can report diagnostics from libc++ module sources; classify these
  separately from application diagnostics. Checks have not been disabled.
- CMake's experimental notice and module-name warnings may appear at configure
  or module compilation. They are not suppressed to suggest stable support.
- Broad navigation/rename behavior, Linux, Windows and other toolchains have not
  been validated for this capability.

Tool upgrades and BMI compatibility need fresh validation. This is an opt-in
experiment, not a general C++ Modules support claim.
