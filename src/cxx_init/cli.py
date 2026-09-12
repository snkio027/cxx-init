import argparse
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
VERSION = "0.1.1"


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


def create_app(name, use_git):
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
        destination = create_app(args.name, use_git=not args.no_git)
    except (GenerationError, OSError) as error:
        print(f"cxx: error: {error}", file=sys.stderr)
        return 1

    print(f"Created C++ project: {destination.name}")
    print()
    print("Next:")
    print(f"  cd {args.name}")
    print("  cmake --workflow --preset dev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
