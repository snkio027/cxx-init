"""Bounded cache-recovery / ASan assessment, not a production build wrapper.

Uses only disposable copies. Missing native capabilities remain failed gates.
An explicitly supplied ASan shared library is never downloaded or installed here.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--toml", type=Path, required=True)
    parser.add_argument("--zig", required=True)
    parser.add_argument("--asan-runtime", type=Path, required=True)
    parser.add_argument("--symbolizer", type=Path, required=True)
    parser.add_argument("--clangd", required=True)
    parser.add_argument("--dsymutil", type=Path, help="Optional macOS source-line recovery probe")
    args = parser.parse_args()
    fixture = Path(__file__).resolve().parent
    output = args.output.resolve()
    if output == fixture or fixture in output.parents:
        parser.error("output must be a new directory outside the fixture")
    runtime = args.asan_runtime.resolve(strict=True)
    symbolizer = args.symbolizer.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=False)
    project = output / "project"
    shutil.copytree(fixture, project, ignore=shutil.ignore_patterns(
        ".zig-cache", "zig-out", "__pycache__", "compile_commands.json", ".cache"))
    env = os.environ.copy()
    env.update(ZIG_GLOBAL_CACHE_DIR=str(output.parent / "zig-global-cache"),
               XDG_CACHE_HOME=str(output / "tool-cache"))
    # Do not inherit preload workarounds that could hide a missing runtime link.
    for name in ("LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "ASAN_OPTIONS"):
        env.pop(name, None)
    env["ASAN_SYMBOLIZER_PATH"] = str(symbolizer)
    zig = str(Path(shutil.which(args.zig) or args.zig).resolve())
    evidence = {"platform": platform.platform(), "machine": platform.machine(),
                "runtime": str(runtime), "runtime_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
                "symbolizer": str(symbolizer),
                "gates": {}, "commands": {}}

    def command(name, argv):
        start = time.monotonic()
        with subprocess.Popen(argv, cwd=project, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, start_new_session=True) as process:
            try:
                text, _ = process.communicate(timeout=600)
                code = process.returncode
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                text, _ = process.communicate()
                code, text = 124, "TIMEOUT\n" + text
        log = output / f"{name}.log"
        log.write_text(text)
        evidence["commands"][name] = {"argv": argv, "returncode": code,
            "seconds": round(time.monotonic() - start, 3),
            "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
        return code, text

    def gate(name, ok, detail):
        evidence["gates"][name] = {"status": "PASS" if ok else "FAIL", "detail": detail}
        (output / "results.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(f"{evidence['gates'][name]['status']} {name}", flush=True)

    evidence["zig"] = command("zig-version", [zig, "version"])[1].strip()
    evidence["frontend"] = command("frontend", [zig, "c++", "--version"])[1].strip()
    evidence["symbolizer_version"] = command("symbolizer-version", [str(symbolizer), "--version"])[1].strip()
    evidence["clangd"] = command("clangd-version", [args.clangd, "--version"])[1].strip()
    if evidence["zig"] != "0.17.0":
        raise SystemExit("This assessment requires Zig 0.17.0")
    records = output / "records"
    records.mkdir()
    base = [zig, "build", "-j4", "--summary", "all", f"-Dtoml={args.toml.resolve()}"]

    def build(name, *extra):
        return command(name, [*base, *extra])

    def database(record_dir=records):
        # Exact known graph membership: do not glob stale records into the DB.
        entries = [json.loads((record_dir / f"{name}.json").read_text().rstrip().rstrip(","))
                   for name in ("main", "core", "toml")]
        assert {Path(e["file"]).name for e in entries} == {"main.cpp", "core.cpp", "toml.cpp"}
        target = project / "compile_commands.json"
        target.write_text(json.dumps(entries, indent=2) + "\n")
        return entries

    flags = [f"-Drecords={records}"]
    code, text = build("capture", "test", *flags)
    gate("capture", code == 0 and all((records / f"{n}.json").is_file() for n in ("main", "core", "toml")), "three actual -MJ records")
    if code:
        return 1
    initial = database()
    (project / "compile_commands.json").unlink()
    gate("database_only_reassembly", database() == initial, "no compilation; requires all current fragments to survive")
    for file in records.iterdir():
        file.unlink()
    code, text = build("cached-recovery", "test", *flags)
    gate("native_cached_recovery", code == 0 and len(list(records.glob("*.json"))) == 3,
         {"cached_compiles": len(re.findall(r"compile (?:exe|lib) .* cached", text)),
          "recovered_fragments": len(list(records.glob("*.json")))})
    # Native workaround: deliberately cold local cache; keep it because the DB
    # references generated/exported headers there. This is NOT cheap cache repair.
    code, text = build("cold-recovery", "test", *flags, "--cache-dir", str(output / "recovery-cache"))
    recovered = database() if code == 0 else []
    gate("cold_cache_recapture", code == 0 and len(recovered) == 3,
         {"cached_compiles": len(re.findall(r"compile (?:exe|lib) .* cached", text)),
          "records": len(recovered)})
    code, text = command("recovered-clangd", [args.clangd, f"--check={project / 'src/core.cpp'}",
                                               f"--compile-commands-dir={project}"])
    gate("recovered_database_clangd", code == 0 and "0 errors" in text,
         "real clangd static check of the application TU; not internal-header acceptance")
    code, text = build("cold-noop", "test", *flags, "--cache-dir", str(output / "recovery-cache"))
    gate("recapture_noop", code == 0 and len(re.findall(r"compile (?:exe|lib) .* cached", text)) == 3,
         "native artifact caching still works; it does not restore the side effects")
    # Same path/config switch: fragments can say ReleaseFast while Debug is cached.
    code, _ = build("release-capture", "test", *flags, "-Doptimize=ReleaseFast",
                    "--cache-dir", str(output / "recovery-cache"))
    release = database() if code == 0 else []
    code, text = build("debug-return", "test", *flags, "--cache-dir", str(output / "recovery-cache"))
    current = database() if code == 0 else []
    gate("native_config_switch", bool(current) and all("-O0" in e["arguments"] for e in current),
         {"unchanged_from_release": current == release, "optimizations":
          [[a for a in e["arguments"] if re.fullmatch(r"-O[0-3sz]", a)] for e in current]})
    # Caller-selected config directories prevent cross-mode overwrites, but are
    # not a generic exporter: changed graph membership and missing records remain.
    scoped = {}
    for mode in ("Debug", "ReleaseFast", "Debug"):
        directory = output / f"records-{mode}"
        directory.mkdir(exist_ok=True)
        name = f"scoped-{mode}-{'return' if mode in scoped else 'first'}"
        code, text = build(name, "test", f"-Drecords={directory}", f"-Doptimize={mode}")
        scoped[mode] = database(directory) if code == 0 else []
    gate("scoped_config_switch", code == 0 and len(scoped["Debug"]) == 3 and
         len(scoped["ReleaseFast"]) == 3 and
         all("-O0" in e["arguments"] for e in scoped["Debug"]) and
         all("-O2" in e["arguments"] for e in scoped["ReleaseFast"]) and
         len(re.findall(r"compile (?:exe|lib) .* cached", text)) == 3,
         "separate record directories plus explicit DB selection; deletion recovery still needs recapture")

    code, text = build("asan-native", "test", "-Dsanitizer=address", "-Dcompiler-rt=true")
    gate("asan_native_compiler_rt", code == 0, {"unresolved_asan": "asan_" in text, "returncode": code})
    external = ["-Dsanitizer=address", f"-Dasan-runtime={runtime}"]
    code, text = build("asan-external-clean", "test", *external)
    gate("asan_external_clean", code == 0, "native Zig compile/link with explicitly supplied shared runtime")
    app = project / "src/main.cpp"
    original = app.read_text()
    faults = {
        "heap-overflow": "auto p = new int[1]; p[argc + 2] = 7; delete[] p;",
        "use-after-free": "auto p = new int[1]; delete[] p; volatile int index = 0; return p[index];",
    }
    for name, fault in faults.items():
        try:
            app.write_text(original.replace("const int actual", fault + "\n    const int actual"))
            code, text = build(f"asan-{name}", "test", *external)
            expected = "heap-buffer-overflow" if name == "heap-overflow" else "heap-use-after-free"
            gate(f"asan_external_{name}", code not in (0, 124) and
                 f"ERROR: AddressSanitizer: {expected}" in text,
                 "requires a real ASan report, not any nonzero link/run failure")
            gate(f"asan_symbolized_{name}", code not in (0, 124) and
                 f"ERROR: AddressSanitizer: {expected}" in text and
                 bool(re.search(r"src/main\.cpp:\d+", text)),
                 "report contains the source file and line, not just an address")
            if args.dsymutil:
                # Operate on the installed copy, never mutate native cache files.
                installed = project / "zig-out/bin/zig-cpp-probe"
                install_code, _ = build(f"asan-install-{name}", *external)
                dsym_code, _ = command(f"dsym-{name}", [str(args.dsymutil.resolve()),
                                      str(installed), "-o", str(installed) + ".dSYM"])
                run_code, report = command(f"dsym-run-{name}", [str(installed), "42"])
                gate(f"asan_dsym_{name}", install_code == dsym_code == 0 and
                     run_code not in (0, 124) and f"ERROR: AddressSanitizer: {expected}" in report and
                     bool(re.search(r"src/main\.cpp:\d+", report)),
                     "explicit dsymutil on installed artifact; extra platform step, no linker substitution")
        finally:
            app.write_text(original)
    code, _ = build("asan-restored", "test", *external)
    gate("asan_external_restored", code == 0, "restored source is clean")
    code, text = build("asan-missing-runtime", "test", "-Dsanitizer=address",
                       f"-Dasan-runtime={output / 'missing-runtime.so'}")
    gate("asan_missing_runtime_rejected", code not in (0, 124) and "missing-runtime.so" in text,
         "missing dependency must not silently disable instrumentation")
    evidence["source_sha256"] = {str(p.relative_to(fixture)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [fixture / "build.zig", Path(__file__).resolve(), *sorted((fixture / "src").glob("*"))]}
    (output / "results.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return int(any(g["status"] == "FAIL" for g in evidence["gates"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
