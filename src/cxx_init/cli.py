import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]*\Z")
# CMake's reserved lowercase targets, plus `test` because the fixture enables CTest.
RESERVED_TARGETS = {
    "all", "help", "install", "preinstall", "clean", "edit_cache", "rebuild_cache", "test",
}
FIXTURE_NAME = "robot-runtime"
FIXTURE_IDENTIFIER = "robot_runtime"
LOCAL_FIXTURE_ENTRIES = ("build", "CMakeUserPresets.json", ".DS_Store", ".idea", ".vscode")
VERSION = "0.2.1"


class GenerationError(Exception):
    pass


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="cxx",
        description="Create a clean, native C++ project.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="create an executable project")
    init_parser.add_argument("name", help="project name: [a-z][a-z0-9-]*")
    init_parser.add_argument(
        "--import-std", action="store_true",
        help="use experimental C++23 import std (verified on macOS + Homebrew LLVM)",
    )
    init_parser.add_argument(
        "--no-git",
        action="store_true",
        help="do not initialize a local Git repository",
    )

    return parser.parse_args(argv)


def validate_destination(name, identifier, destination):
    if NAME_PATTERN.fullmatch(name) is None:
        raise GenerationError(f"invalid project name {name!r}; expected [a-z][a-z0-9-]*")

    if identifier in RESERVED_TARGETS:
        raise GenerationError(f"project name {name!r} produces reserved CMake target {identifier!r}")

    if destination.is_symlink():
        raise GenerationError(f"destination must not be a symbolic link: {destination}")

    if not destination.exists():
        return False

    if not destination.is_dir():
        raise GenerationError(f"destination already exists and is not a directory: {destination}")

    if next(destination.iterdir(), None) is not None:
        raise GenerationError(f"destination already exists and is not empty: {destination}")

    return True


def render_fixture(root, name, identifier):
    replacements = (
        (FIXTURE_NAME, name),
        (FIXTURE_IDENTIFIER, identifier),
    )

    for generated_file in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        try:
            content = generated_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise GenerationError(f"fixture contains a non-text file: {generated_file}") from error

        for source, replacement in replacements:
            content = content.replace(source, replacement)

        generated_file.write_text(content, encoding="utf-8")


def initialize_git(root):
    # A caller's repository paths must not redirect this new repository.
    environment = os.environ.copy()
    for variable in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        environment.pop(variable, None)
    try:
        result = subprocess.run(
            ["git", "init", "--quiet"],
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise GenerationError("git is not available; rerun with --no-git") from error

    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown error"
        raise GenerationError(f"git init failed: {detail}")


def enable_import_std(root):
    # Specialize the shared fixture; do not maintain a second project template.
    prefix = '''cmake_minimum_required(VERSION 4.4)

# Experimental gate verified with CMake 4.4.3; recheck when upgrading CMake.
set(CMAKE_EXPERIMENTAL_CXX_IMPORT_STD "f35a9ac6-8463-4d38-8eec-5d6008153e7d")
if(NOT EXISTS "${CMAKE_CXX_STDLIB_MODULES_JSON}")
    message(FATAL_ERROR
        "import std requires libc++.modules.json: set CMAKE_CXX_STDLIB_MODULES_JSON. See README.md")
endif()

project(robot_runtime LANGUAGES CXX)

if(NOT APPLE OR NOT CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
    message(FATAL_ERROR "This import std experiment requires macOS and upstream Clang/libc++")
endif()
if(NOT "23" IN_LIST CMAKE_CXX_COMPILER_IMPORT_STD)
    message(FATAL_ERROR "The selected toolchain does not provide C++23 import std support")
endif()'''
    changes = (
        ("CMakeLists.txt", "cmake_minimum_required(VERSION 3.25)\n\n"
         "project(robot_runtime LANGUAGES CXX)", prefix),
        ("CMakeLists.txt", "PROPERTIES CXX_EXTENSIONS OFF)",
         "PROPERTIES CXX_EXTENSIONS OFF CXX_MODULE_STD ON)"),
        ("src/main.cpp", "#include <iostream>", "import std;"),
        (".clangd", "MissingIncludes: Strict", "MissingIncludes: None"),
    )
    for filename, old, new in changes:
        path = root / filename
        content = path.read_text(encoding="utf-8")
        if content.count(old) != 1:
            raise GenerationError(f"import std fixture anchor is missing or ambiguous: {filename}")
        path.write_text(content.replace(old, new), encoding="utf-8")

    presets_path = root / "CMakePresets.json"
    presets = json.loads(presets_path.read_text(encoding="utf-8"))
    presets["cmakeMinimumRequired"] = {"major": 4, "minor": 4, "patch": 0}
    dev = next(preset for preset in presets["configurePresets"] if preset["name"] == "dev")
    dev["cacheVariables"]["CMAKE_CXX_STDLIB_MODULES_JSON"] = "$env{CMAKE_CXX_STDLIB_MODULES_JSON}"
    presets_path.write_text(json.dumps(presets, indent=2) + "\n", encoding="utf-8")
    provenance = root / ".cxx.toml"
    provenance.write_text(provenance.read_text() + 'stdlib = "import-std"\n', encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("import_std.md"), root / "README.md")


def create_app(name, use_git, import_std=False):
    fixture = Path(__file__).resolve().parent / "fixtures" / "canonical-app"
    if not fixture.is_dir():
        raise GenerationError(f"bundled app fixture is missing: {fixture}")

    destination = Path.cwd() / name
    identifier = name.replace("-", "_")
    destination_was_empty = validate_destination(name, identifier, destination)

    staging = Path(tempfile.mkdtemp(prefix=f".{name}.cxx-", dir=destination.parent))
    try:
        shutil.copytree(
            fixture,
            staging,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*LOCAL_FIXTURE_ENTRIES),
        )
        if import_std:
            enable_import_std(staging)
        render_fixture(staging, name, identifier)

        if use_git:
            initialize_git(staging)

        if destination_was_empty:
            destination.rmdir()

        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if destination_was_empty and not destination.exists():
            destination.mkdir()
        raise

    return destination


def main(argv=None):
    args = parse_args(argv)

    try:
        destination = create_app(args.name, use_git=not args.no_git, import_std=args.import_std)
    except (GenerationError, OSError) as error:
        print(f"cxx: error: {error}", file=sys.stderr)
        return 1

    print(f"Created C++ project: {destination.name}")
    if args.import_std:
        print("Standard library mode: import std [experimental]")
        print("Verified toolchain: macOS + Homebrew LLVM (see README.md)")
    print()
    print("Next:")
    print(f"  cd {args.name}")
    if args.import_std:
        print('  export CXX="$(brew --prefix llvm)/bin/clang++"')
        print('  export CMAKE_CXX_STDLIB_MODULES_JSON="$(brew --prefix llvm)/lib/c++/libc++.modules.json"')
    print("  cmake --workflow --preset dev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
