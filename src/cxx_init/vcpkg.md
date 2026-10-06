# Explicit vcpkg integration

This project opted into vcpkg; the ordinary `cxx init` remains dependency-free.
Creation was offline. `vcpkg.json` starts with no libraries and pins the builtin
registry at `434307da09bc05b2c86996dccc8b2351fc0d5d37`, a tested snapshot, not
an automatic latest-version policy. Review baseline updates as project changes.

Point at your **existing** vcpkg checkout before configuring:

```sh
export VCPKG_ROOT="/path/to/existing/vcpkg"
cmake --workflow --preset dev
```

The presets pass `CMAKE_TOOLCHAIN_FILE` into CMake before `project()`. Missing
toolchains fail explicitly; the generator does not install vcpkg or silently
continue without it. Configure may download/build dependencies. Installed
packages stay under the ignored `build/<preset>/vcpkg_installed` directories.
Keep `VCPKG_ROOT` set for subsequent workflows. A deliberate toolchain override
can be recorded in `CMakeUserPresets.json` or supplied with `-D`; it is project
configuration, not something the generator or editor rewrites.

Add dependencies to the manifest, then use their documented CMake targets:

```cmake
find_package(Package CONFIG REQUIRED)
target_link_libraries(robot_runtime PRIVATE Package::Target)
```

`Package` / `Package::Target` are placeholders, not a promised naming convention.
Use the library's public headers. clangd obtains include paths and definitions
from `build/dev/compile_commands.json`; do not duplicate them in `.clangd`.
The integration cannot make private implementation headers self-contained.

Choose compiler, target triplet and ABI together. The application's `CXX`
environment setting does not automatically select the compiler used for all
vcpkg ports. Use vcpkg's documented triplet/chainload controls when needed,
then configure a fresh build directory for incompatible toolchain changes.

`--import-std --vcpkg` retains all experimental module requirements described
above; it does not convert third-party headers to modules or promise arbitrary
library compatibility. There are no `cxx add/build/run` wrappers or automatic
migrations. After creation, ordinary CMake and vcpkg own this project.
