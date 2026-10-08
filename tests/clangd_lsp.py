"""Bounded, real clangd diagnostics and navigation for generated projects."""

import json
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
from urllib.parse import unquote, urlparse


def collect_diagnostics(project, environment, sources, *, path="src/main.cpp"):
    return collect_evidence(project, environment, sources, path=path)["diagnostics"]


def collect_evidence(project, environment, sources, *, path="src/main.cpp", definition_positions=()):
    uri = (project / path).as_uri()
    messages = queue.Queue()
    with tempfile.TemporaryFile() as log, subprocess.Popen(
        [environment.get("CLANGD", "clangd"), "--enable-config", "--clang-tidy",
         "--background-index", "--log=error"],
        cwd=project, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
    ) as process:
        def read_messages():
            try:
                while True:
                    headers = {}
                    while (line := process.stdout.readline()) not in (b"\r\n", b""):
                        key, value = line.decode().split(":", 1)
                        headers[key.lower()] = value.strip()
                    if not line:
                        raise EOFError("clangd closed its output")
                    messages.put(json.loads(process.stdout.read(int(headers["content-length"]))))
            except Exception as error:
                messages.put(error)

        def send(method, params, request_id=None):
            message = {"jsonrpc": "2.0", "method": method, "params": params}
            if request_id is not None:
                message["id"] = request_id
            payload = json.dumps(message).encode()
            process.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)
            process.stdin.flush()

        def receive(predicate):
            deadline = time.monotonic() + 30
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("clangd did not send the expected LSP message within 30s")
                try:
                    message = messages.get(timeout=remaining)
                except queue.Empty as error:
                    raise TimeoutError("clangd did not send the expected LSP message within 30s") from error
                if isinstance(message, Exception):
                    raise message
                if predicate(message):
                    if "error" in message:
                        raise AssertionError(message)
                    return message

        reader = threading.Thread(target=read_messages, daemon=True)
        reader.start()
        try:
            send("initialize", {"processId": None, "rootUri": project.as_uri(), "capabilities": {
                "textDocument": {"publishDiagnostics": {"versionSupport": True}},
            }}, 1)
            receive(lambda message: message.get("id") == 1)
            send("initialized", {})
            results = []
            for version, source in enumerate(sources, start=1):
                if version == 1:
                    send("textDocument/didOpen", {"textDocument": {
                        "uri": uri, "languageId": "cpp", "version": version, "text": source,
                    }})
                else:
                    send("textDocument/didChange", {"textDocument": {"uri": uri, "version": version},
                                                    "contentChanges": [{"text": source}]})
                response = receive(lambda message: message.get("method") == "textDocument/publishDiagnostics"
                                   and message["params"].get("uri") == uri
                                   and message["params"].get("version") == version)
                results.append(response["params"]["diagnostics"])
            definitions = []
            headers = {}
            for request_id, position in enumerate(definition_positions, start=2):
                send("textDocument/definition", {"textDocument": {"uri": uri},
                                                 "position": position}, request_id)
                response = receive(lambda message: message.get("id") == request_id)
                locations = response["result"] or []
                if isinstance(locations, dict):
                    locations = [locations]
                definitions.append(locations)
                for location in locations:
                    target_uri = location["uri"]
                    if target_uri == uri or target_uri in headers:
                        continue
                    target = urlparse(target_uri)
                    if target.scheme != "file" or target.netloc:
                        raise AssertionError(f"unexpected definition URI: {target_uri}")
                    # Open the returned header in this same client, as an editor's
                    # goto-definition does; do not invent a separate compile command.
                    send("textDocument/didOpen", {"textDocument": {
                        "uri": target_uri, "languageId": "cpp", "version": 1,
                        "text": Path(unquote(target.path)).read_text(),
                    }})
                    response = receive(lambda message: message.get("method") == "textDocument/publishDiagnostics"
                                       and message["params"].get("uri") == target_uri
                                       and message["params"].get("version") == 1)
                    headers[target_uri] = response["params"]["diagnostics"]
            send("shutdown", None, len(definition_positions) + 2)
            receive(lambda message: message.get("id") == len(definition_positions) + 2)
            send("exit", None)
            if process.wait(timeout=10) != 0:
                raise AssertionError("clangd exited unsuccessfully")
            return {"diagnostics": results, "definitions": definitions, "headers": headers}
        except Exception as error:
            log.seek(0)
            raise AssertionError(f"LSP diagnostics regression failed: {error}\n"
                                 + log.read().decode(errors="replace")) from error
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            reader.join(timeout=5)
