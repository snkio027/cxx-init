"""Disposable native-build experiment; records failed feasibility gates honestly.

No dependency downloads, host changes, production fixtures, or CMake delegation.
The -MJ collector is deliberately experimental, not a production compdb exporter.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import select
import shutil
import signal
import subprocess
import sys
import time


def completion_probe(project, environment):
    """One real completion request against this fixture, with bounded raw LSP IO."""
    source = project / "src/core.cpp"
    text = source.read_text().replace("toml::parse(", "toml::par(")
    lines = text.splitlines()
    row = next(i for i, line in enumerate(lines) if "toml::par(" in line)
    uri = source.as_uri()
    log_path = project.parent / "completion-clangd.log"
    with log_path.open("wb") as log, subprocess.Popen(
        [environment["CLANGD"], "--enable-config", "--log=error"], cwd=project,
        env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
        bufsize=0,
    ) as process:
        pending = bytearray()

        def send(method, params, request_id=None):
            message = {"jsonrpc": "2.0", "method": method, "params": params}
            if request_id is not None:
                message["id"] = request_id
            payload = json.dumps(message).encode()
            process.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)

        def response(request_id):
            deadline = time.monotonic() + 30
            while True:
                split = pending.find(b"\r\n\r\n")
                if split >= 0:
                    header = bytes(pending[:split]).decode()
                    length = int(next(line.split(":", 1)[1] for line in header.split("\r\n")
                                      if line.lower().startswith("content-length:")))
                    end = split + 4 + length
                    if len(pending) >= end:
                        message = json.loads(pending[split + 4:end])
                        del pending[:end]
                        if (request_id is None and message.get("method") == "textDocument/publishDiagnostics"
                                and message["params"].get("uri") == uri and message["params"].get("version") == 1):
                            return message["params"]
                        if request_id is not None and message.get("id") == request_id:
                            if "error" in message:
                                raise AssertionError(message)
                            return message["result"]
                        continue
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                    raise TimeoutError("clangd completion exceeded 30s")
                block = os.read(process.stdout.fileno(), 65536)
                if not block:
                    raise EOFError("clangd exited before completion response")
                pending.extend(block)

        try:
            send("initialize", {"processId": None, "rootUri": project.as_uri(), "capabilities": {
                "textDocument": {"publishDiagnostics": {"versionSupport": True}}}}, 1)
            response(1)
            send("initialized", {})
            send("textDocument/didOpen", {"textDocument": {
                "uri": uri, "languageId": "cpp", "version": 1, "text": text}})
            # Avoid clangd's documented preamble-not-ready completion fallback.
            response(None)
            send("textDocument/completion", {"textDocument": {"uri": uri}, "position": {
                "line": row, "character": lines[row].index("toml::par") + len("toml::par")}}, 2)
            items = response(2)
            if isinstance(items, dict):
                items = items.get("items", [])
            labels = [item["label"] for item in items or []]
            send("shutdown", None, 3)
            response(3)
            send("exit", None)
            if process.wait(timeout=10) != 0:
                raise AssertionError("clangd completion session exited unsuccessfully")
            return labels
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toml", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New isolated result directory")
    parser.add_argument("--zig", default="zig")
    parser.add_argument("--clangd", default="clangd")
    args = parser.parse_args()
    output = args.output.resolve()
    fixture = Path(__file__).resolve().parent
    if output == fixture or fixture in output.parents:
        raise SystemExit("--output must be outside the fixture to avoid recursive copying")
    output.mkdir(parents=True, exist_ok=False)
    project = output / "project"
    shutil.copytree(fixture, project, ignore=shutil.ignore_patterns(
        ".zig-cache", "zig-out", "compile_commands.json", ".cache", "__pycache__"))
    records = output / "records"
    records.mkdir()
    environment = os.environ.copy()
    environment["ZIG_GLOBAL_CACHE_DIR"] = str(output.parent / "zig-global-cache")
    environment["XDG_CACHE_HOME"] = str(output / "tool-cache")
    results = {"platform": platform.platform(), "machine": platform.machine(), "gates": {}}
    zig = str(Path(shutil.which(args.zig) or args.zig).resolve())
    environment["CLANGD"] = str(Path(shutil.which(args.clangd) or args.clangd).resolve())

    def command(label, argv):
        start = time.monotonic()
        with subprocess.Popen(argv, cwd=project, env=environment, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              start_new_session=True) as process:
            try:
                text, _ = process.communicate(timeout=600)
                code = process.returncode
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                text, _ = process.communicate()
                code, text = 124, "TIMEOUT after 600s\n" + text
        (output / f"{label}.log").write_text(text)
        return {"returncode": code, "seconds": round(time.monotonic() - start, 3), "output": text}

    def gate(name, ok, detail):
        results["gates"][name] = {"status": "PASS" if ok else "FAIL", "detail": detail}
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(f"{'PASS' if ok else 'FAIL'} {name}", flush=True)

    base = [zig, "build", "-j4", "--summary", "all", f"-Dtoml={args.toml.resolve()}", f"-Drecords={records}"]

    def build(label, *options):
        result = command(label, [*base, *options])
        return result

    results["zig"] = command("zig-version", [zig, "version"])["output"].strip()
    results["clangd"] = command("clangd-version", [environment["CLANGD"], "--version"])["output"].strip()
    results["toml_revision"] = subprocess.check_output(
        ["git", "-c", f"safe.directory={args.toml.resolve()}", "-C", str(args.toml), "rev-parse", "HEAD"], text=True).strip()
    if results["zig"] != "0.17.0" or results["toml_revision"] != "30172438cee64926dc41fdd9c11fb3ba5b2ba9de":
        raise SystemExit("This bounded experiment requires Zig 0.17.0 and toml++ v3.4.0")
    first = build("debug", "test")
    gate("native_debug", first["returncode"] == 0, first)
    if first["returncode"] != 0:
        return 1
    for mode in ("ReleaseSafe", "ReleaseFast"):
        result = build(mode, "test", f"-Doptimize={mode}")
        gate(mode, result["returncode"] == 0, result)
    result = build("run", "run", "--", "42")
    gate("run_arguments", result["returncode"] == 0 and "answer=42" in result["output"], result)
    result = build("run-failure", "run", "--", "99")
    gate("run_failure", result["returncode"] != 0 and "process exited with code 23" in result["output"], result)

    # Incremental invalidation must change runtime results, not merely timestamps.
    result = build("noop", "test")
    cached = re.findall(r"compile (?:exe|lib) .* cached", result["output"])
    gate("noop", result["returncode"] == 0 and len(cached) == 3, result)
    private = project / "src/private.hpp"
    original = private.read_text()
    try:
        private.write_text(original.replace("= 4;", "= 5;"))
        result = build("private-header", "run", "--", "43")
        gate("private_header", result["returncode"] == 0 and "answer=43" in result["output"], result)
    finally:
        private.write_text(original)
    public = project / "include/core.hpp"
    original = public.read_text()
    try:
        public.write_text(original.replace("= 0;", "= 3;"))
        result = build("public-header", "run", "--", "45")
        gate("public_header", result["returncode"] == 0 and "answer=45" in result["output"], result)
    finally:
        public.write_text(original)
    result = build("generated-header", "test", "-Dbias=7")
    gate("generated_header", result["returncode"] == 0, result)

    source = project / "src/core.cpp"
    original = source.read_text()
    try:
        source.write_text(original + "\n#error deliberate_compile_failure\n")
        result = build("compile-failure", "test")
        gate("compile_failure", result["returncode"] != 0 and "deliberate_compile_failure" in result["output"], result)
    finally:
        source.write_text(original)
    app = project / "src/main.cpp"
    original = app.read_text()
    try:
        app.write_text(original.replace("return argc > 1", "if (argc > 0) return 23;\n    return argc > 1"))
        result = build("test-failure", "test")
        gate("test_failure", result["returncode"] != 0 and "process exited with code 23 (expected exited with code 0)" in result["output"], result)
    finally:
        app.write_text(original)
    records = output / "compdb-records"
    records.mkdir()
    base[-1] = f"-Drecords={records}"
    restored = build("restore-and-capture-debug", "test")
    gate("restore_debug", restored["returncode"] == 0, restored)

    # Native Clang records contain its actual expanded system includes and macros.
    # Do not reconstruct them from another config or silently remove parser errors.
    entries = [json.loads((records / f"{name}.json").read_text().strip().rstrip(","))
               for name in ("main", "core", "toml")]
    database = project / "compile_commands.json"
    database.write_text(json.dumps(entries, indent=2) + "\n")
    results["compdb_sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
    gate("compdb_three_units", {Path(entry["file"]).name for entry in entries} == {"main.cpp", "core.cpp", "toml.cpp"},
         "Clang -MJ records assembled without modifying arguments")
    # Reuse the repository's real bounded LSP protocol client, not clangd --check.
    sys.path.insert(0, str(fixture.parents[1] / "tests"))
    from clangd_lsp import collect_evidence
    try:
        cpp = source.read_text()
        lines = cpp.splitlines()
        line = next(i for i, value in enumerate(lines) if "toml::parse(" in value)
        evidence = collect_evidence(project, environment,
            [cpp, cpp + "\nunknown_probe_type injected;\n", cpp], path="src/core.cpp",
            definition_positions=[{"line": line, "character": lines[line].index("parse(") + 1}])
        (output / "lsp.json").write_text(json.dumps(evidence, indent=2) + "\n")
        diagnostics = evidence["diagnostics"]
        errors = lambda items: [item for item in items if item.get("severity") == 1]
        injected = any("unknown_probe_type" in item["message"] for item in errors(diagnostics[1]))
        gate("clangd_diagnostics", not errors(diagnostics[0]) and injected and not errors(diagnostics[2]), evidence)
        locations = evidence["definitions"][0]
        gate("clangd_definition", bool(locations) and all("toml" in item["uri"] for item in locations), locations)
        gate("clangd_open_definition", bool(evidence["headers"]) and all(not errors(items) for items in evidence["headers"].values()), evidence["headers"])
    except Exception as error:
        gate("clangd_session", False, str(error))
    try:
        labels = completion_probe(project, environment)
        gate("clangd_completion", any("parse(" in label for label in labels), labels)
    except Exception as error:
        gate("clangd_completion", False, str(error))

    # -MJ writes are not registered Zig graph outputs: explicitly probe regeneration.
    for path in records.glob("*.json"):
        path.unlink()
    result = build("compdb-cache-recovery", "test")
    gate("compdb_cache_recovery", result["returncode"] == 0 and all((records / f"{name}.json").exists() for name in ("main", "core", "toml")),
         {"build": result, "remaining_records": sorted(path.name for path in records.glob("*.json"))})

    for sanitizer, body in (
        ("undefined", "volatile int value = 2147483647; return value + 1;"),
        ("address", "int* p = new int[1]; volatile int index = argc + 2; p[index] = 7; delete[] p; return 0;"),
    ):
        try:
            app.write_text(original.replace("const int actual = probe::answer();", body + "\n    const int actual = probe::answer();"))
            result = build(f"san-{sanitizer}", "run", f"-Dsanitizer={sanitizer}")
            # A compile/link failure is NOT successful runtime detection.
            detected = ("panic: signed integer overflow:" in result["output"]
                        and "process terminated with signal ABRT" in result["output"]) if sanitizer == "undefined" else "ERROR: AddressSanitizer" in result["output"]
            gate(f"sanitizer_{sanitizer}", result["returncode"] != 0 and detected, result)
        finally:
            app.write_text(original)
    return int(any(item["status"] == "FAIL" for item in results["gates"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
