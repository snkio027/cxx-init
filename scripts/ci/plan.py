#!/usr/bin/env python3
"""Bind PR-full coverage to the actual GitHub test-merge candidate; never run tests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

PROFILE = "pr-full-standard-v1"
FULL = ["build"]
ROOT = Path(__file__).resolve().parents[2]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def make_plan(
    event: dict, commit: str, tree: str, parents: list[str], revision: str
) -> dict:
    pr = event["pull_request"]
    base, head = pr["base"]["sha"], pr["head"]["sha"]
    if pr["base"]["ref"] != "main" or type(pr["draft"]) is not bool:
        raise ValueError("unexpected target or draft state")
    if not all(
        isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha)
        for sha in (base, head, commit, tree)
    ):
        raise ValueError("invalid candidate identity")
    if parents != [base, head]:
        raise ValueError("checkout is not the event's base + head test merge")
    if not re.fullmatch(
        r"(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^\r\n()]+\))?!?: [^\r\n]+",
        pr["title"],
    ):
        raise ValueError(
            "PR title must describe the integration using Conventional Commits"
        )
    return {
        "schema": 1,
        "profile": PROFILE,
        "policy_revision": revision,
        "base": base,
        "head": head,
        "candidate": commit,
        "tree": tree,
        "mode": "draft" if pr["draft"] else "full",
        "coverage": [] if pr["draft"] else FULL,
        "reason": "Draft feedback only"
        if pr["draft"]
        else "No queue: all integration lanes required",
    }


def current_plan() -> dict:
    if os.environ["GITHUB_EVENT_NAME"] != "pull_request":
        raise ValueError("PR plan requested for a non-PR event")
    if git("rev-parse", "HEAD") != os.environ["GITHUB_SHA"]:
        raise ValueError("checkout differs from workflow candidate SHA")
    revision = hashlib.sha256()
    paths = [Path(__file__).resolve(), ROOT / "scripts/ci/delivery_gate.py"]
    paths += sorted((ROOT / ".github/workflows").glob("*.yml"))
    for path in paths:
        revision.update(
            str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes()
        )
    return make_plan(
        json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()),
        git("rev-parse", "HEAD"),
        git("rev-parse", "HEAD^{tree}"),
        git("show", "-s", "--format=%P", "HEAD").split(),
        revision.hexdigest(),
    )


def main() -> None:
    plan = current_plan()
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write("mode=" + plan["mode"] + "\n")
        output.write("plan=" + json.dumps(plan, separators=(",", ":")) + "\n")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
        summary.write(
            "## Candidate coverage plan\n```json\n"
            + json.dumps(plan, indent=2)
            + "\n```\n"
        )


if __name__ == "__main__":
    main()
