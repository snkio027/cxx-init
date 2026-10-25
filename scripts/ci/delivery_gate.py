#!/usr/bin/env python3
"""Add candidate-bound PR-full checks without replacing existing admission."""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from plan import FULL, current_plan

JOBS = {"fast", "plan", "build"}
EVENTS = {"workflow_dispatch", "push", "pull_request", "release"}


def evaluate(event: str, needs: object, expected: dict | None = None) -> str:
    if event not in EVENTS or not isinstance(needs, dict) or set(needs) != JOBS:
        raise ValueError("unsupported event or incomplete job inventory")
    for name, job in needs.items():
        if not isinstance(job, dict) or job.get("result") not in ("success", "skipped"):
            raise ValueError(f"unsuccessful or unknown job: {name}")
    required = {"fast"}
    if event == "pull_request":
        required.add("plan")
        outputs = needs["plan"].get("outputs")
        if (
            not isinstance(outputs, dict)
            or set(outputs) != {"mode", "plan"}
            or expected is None
        ):
            raise ValueError("missing candidate plan")
        actual = json.loads(outputs["plan"])
        if actual != expected or outputs["mode"] != expected["mode"]:
            raise ValueError("stale candidate or policy plan")
        if expected["mode"] == "full":
            required.update(FULL)
        elif expected["mode"] != "draft":
            raise ValueError("unsupported execution mode")
        if expected["coverage"] != ([] if expected["mode"] == "draft" else FULL):
            raise ValueError("incomplete coverage")
    else:
        required.update(FULL)
    pass
    if any(needs[job]["result"] != "success" for job in required):
        raise ValueError("required work did not execute successfully")
    lines = [
        f"## Delivery evidence: {event}",
        "",
        "| Job | Actual | Coverage |",
        "| --- | --- | --- |",
    ]
    for job in sorted(JOBS):
        state = needs[job]["result"]
        verdict = (
            "required"
            if job in required
            else (
                "not applicable; not executed"
                if state == "skipped"
                else "additional legacy coverage"
            )
        )
        lines.append(f"| {job} | {state} | {verdict} |")
    if expected:
        lines += ["", "```json", json.dumps(expected, indent=2), "```"]
        if expected["mode"] == "draft":
            lines += [
                "Draft feedback is not admission; legacy checks remain during migration."
            ]
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        event = os.environ["GITHUB_EVENT_NAME"]
        report = evaluate(
            event,
            json.loads(os.environ["NEEDS_JSON"]),
            current_plan() if event == "pull_request" else None,
        )
    except (ValueError, KeyError, TypeError) as error:
        print(f"Delivery blocked: {error}", file=sys.stderr)
        return 1
    print(report, end="")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as output:
        output.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
