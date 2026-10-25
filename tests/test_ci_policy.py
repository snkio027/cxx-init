#!/usr/bin/env python3
"""Exercise candidate identity, fail-closed delivery and actual workflow wiring."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/ci"))
import plan
import delivery_gate as gate

FULL = ["build"]
WORKFLOW = ROOT / ".github/workflows/release.yml"


def candidate(draft=False):
    return plan.make_plan(
        {
            "pull_request": {
                "draft": draft,
                "title": "ci: verify delivery",
                "base": {"ref": "main", "sha": "a" * 40},
                "head": {"sha": "b" * 40},
            }
        },
        "c" * 40,
        "d" * 40,
        ["a" * 40, "b" * 40],
        "e" * 64,
    )


def observations(p):
    states = {job: {"result": "success", "outputs": {}} for job in gate.JOBS}
    states["plan"]["outputs"] = {"mode": p["mode"], "plan": json.dumps(p)}
    for job in []:
        states[job]["result"] = "skipped"
    return states


class DeliveryPolicyTest(unittest.TestCase):
    def test_ready_requires_all_lanes_and_draft_is_not_admission(self):
        ready = candidate()
        self.assertEqual(ready["coverage"], FULL)
        self.assertIn(
            "Delivery evidence",
            gate.evaluate("pull_request", observations(ready), ready),
        )
        draft = candidate(True)
        self.assertEqual(draft["coverage"], [])
        self.assertIn(
            "not admission", gate.evaluate("pull_request", observations(draft), draft)
        )
        for job in ["fast", "plan", *FULL]:
            for result in [
                "skipped",
                "cancelled",
                "failure",
                "timed_out",
                "neutral",
                "",
                None,
            ]:
                with self.subTest(job=job, result=result):
                    states = observations(ready)
                    states[job]["result"] = result
                    with self.assertRaises((ValueError, TypeError)):
                        gate.evaluate("pull_request", states, ready)

    def test_inventory_outputs_and_stale_plans_fail_closed(self):
        p = candidate()
        for job in gate.JOBS:
            states = observations(p)
            del states[job]
            with self.assertRaises(ValueError):
                gate.evaluate("pull_request", states, p)
        for field, value in [
            ("schema", 2),
            ("profile", "queue"),
            ("base", "f" * 40),
            ("head", "f" * 40),
            ("candidate", "f" * 40),
            ("tree", "f" * 40),
            ("policy_revision", "f" * 64),
            ("mode", "unknown"),
            ("coverage", []),
        ]:
            changed = {**p, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                gate.evaluate("pull_request", observations(changed), p)
        for output in [
            {},
            {"mode": "full", "plan": "{"},
            {"mode": "", "plan": json.dumps(p)},
            {"mode": "full", "plan": json.dumps(p), "extra": "1"},
        ]:
            states = observations(p)
            states["plan"]["outputs"] = output
            with self.assertRaises(ValueError):
                gate.evaluate("pull_request", states, p)
        with self.assertRaises(ValueError):
            gate.evaluate("merge_group", observations(p), p)

    def test_wrong_checkout_target_title_and_draft_type_are_rejected(self):
        event = {
            "pull_request": {
                "draft": False,
                "title": "fix(ci): safe candidate",
                "base": {"ref": "main", "sha": "a" * 40},
                "head": {"sha": "b" * 40},
            }
        }
        for parents in [[], ["b" * 40, "a" * 40], ["a" * 40], ["f" * 40, "b" * 40]]:
            with self.assertRaises(ValueError):
                plan.make_plan(event, "c" * 40, "d" * 40, parents, "e" * 64)
        for field, value in [
            ("draft", "false"),
            ("title", "update"),
            ("title", "ci: ok\nforged"),
        ]:
            bad = copy.deepcopy(event)
            bad["pull_request"][field] = value
            with self.assertRaises(ValueError):
                plan.make_plan(bad, "c" * 40, "d" * 40, ["a" * 40, "b" * 40], "e" * 64)
        event["pull_request"]["base"]["ref"] = "other"
        with self.assertRaises(ValueError):
            plan.make_plan(event, "c" * 40, "d" * 40, ["a" * 40, "b" * 40], "e" * 64)

    def test_push_manual_and_failure_exit_status(self):
        p = candidate()
        states = observations(p)
        states["plan"] = {"result": "skipped", "outputs": {}}
        pass
        self.assertIn("Delivery evidence", gate.evaluate("push", states))
        with tempfile.TemporaryDirectory() as temp:
            for bad in [
                "{",
                "null",
                json.dumps({}),
                json.dumps({**states, "fast": {"result": "failure"}}),
            ]:
                process = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/ci/delivery_gate.py")],
                    env={
                        **os.environ,
                        "GITHUB_EVENT_NAME": "push",
                        "NEEDS_JSON": bad,
                        "GITHUB_STEP_SUMMARY": str(Path(temp) / "summary"),
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
                self.assertIn("Delivery blocked", process.stderr)

    def test_real_test_merge_plan_and_stale_candidate_exit(self):
        # Real Git objects, not a mocked checkout: the CLI must bind the event
        # base/head to the two parents and reject an otherwise valid stale SHA.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts/ci"
            scripts.mkdir(parents=True)
            (root / ".github/workflows").mkdir(parents=True)
            for name in ("plan.py", "delivery_gate.py"):
                (scripts / name).write_bytes((ROOT / "scripts/ci" / name).read_bytes())

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
                ).strip()

            git("init", "-b", "main")
            git("config", "user.name", "Delivery test")
            git("config", "user.email", "test@example.invalid")
            git("add", ".")
            git("commit", "-m", "baseline")
            base = git("rev-parse", "HEAD")
            git("switch", "-c", "candidate")
            (root / "sample").write_text("candidate\n")
            git("add", "sample")
            git("commit", "-m", "candidate")
            head = git("rev-parse", "HEAD")
            git("switch", "main")
            git("merge", "--no-ff", "candidate", "-m", "test merge")
            sha = git("rev-parse", "HEAD")
            event = root / "event.json"
            payload = {
                "pull_request": {
                    "draft": True,
                    "title": "ci: exercise candidate",
                    "base": {"ref": "main", "sha": base},
                    "head": {"sha": head},
                }
            }
            output = root / "output"
            env = {
                **os.environ,
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_EVENT_PATH": str(event),
                "GITHUB_SHA": sha,
                "GITHUB_OUTPUT": str(output),
                "GITHUB_STEP_SUMMARY": str(root / "summary"),
            }
            for draft in (True, False):
                payload["pull_request"]["draft"] = draft
                event.write_text(json.dumps(payload))
                output.write_text("")
                result = subprocess.run(
                    [sys.executable, str(scripts / "plan.py")],
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs = dict(
                    line.split("=", 1) for line in output.read_text().splitlines()
                )
                actual = json.loads(outputs["plan"])
                self.assertEqual(actual["head"], head)
                self.assertEqual(actual["base"], base)
                self.assertEqual(actual["candidate"], sha)
                self.assertEqual(actual["tree"], git("rev-parse", "HEAD^{tree}"))
                self.assertEqual(actual["coverage"], [] if draft else FULL)
                states = observations(actual)
                result = subprocess.run(
                    [sys.executable, str(scripts / "delivery_gate.py")],
                    env={**env, "NEEDS_JSON": json.dumps(states)},
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                # Missing a required lane must really terminate the CLI nonzero.
                states["fast"]["result"] = "skipped"
                result = subprocess.run(
                    [sys.executable, str(scripts / "delivery_gate.py")],
                    env={**env, "NEEDS_JSON": json.dumps(states)},
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            result = subprocess.run(
                [sys.executable, str(scripts / "plan.py")],
                env={**env, "GITHUB_SHA": head},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checkout differs", result.stderr)

    def test_workflow_and_rule_wiring(self):
        w = json.loads(
            subprocess.check_output(
                [
                    "ruby",
                    "-rjson",
                    "-ryaml",
                    "-e",
                    "puts JSON.generate(YAML.load_file(ARGV.fetch(0)))",
                    str(WORKFLOW),
                ],
                text=True,
            )
        )
        trigger = w.get("on", w.get("true"))
        self.assertEqual(
            set(trigger["pull_request"]["types"]),
            {
                "opened",
                "synchronize",
                "reopened",
                "edited",
                "ready_for_review",
                "converted_to_draft",
            },
        )
        self.assertIn("github.run_id", w["concurrency"]["group"])
        self.assertEqual(
            w["concurrency"]["cancel-in-progress"],
            "${{ github.event_name == 'pull_request' }}",
        )
        jobs = w["jobs"]
        delivery = jobs["delivery"]
        self.assertEqual(set(delivery["needs"]), gate.JOBS)
        self.assertEqual(delivery["if"], "${{ always() }}")
        self.assertIn("Draft Delivery Feedback", delivery["name"])
        self.assertIn("Main Delivery Quality", delivery["name"])
        self.assertEqual(jobs["plan"]["if"], "github.event_name == 'pull_request'")
        self.assertEqual(jobs["plan"]["steps"][-1]["run"], "python3 scripts/ci/plan.py")
        for step in jobs["plan"]["steps"]:
            self.assertNotIn("unittest", step.get("run", ""))
        for job in jobs.values():
            self.assertFalse(job.get("continue-on-error", False))
            for step in job["steps"]:
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertIs(step["with"]["persist-credentials"], False)
        self.assertEqual(delivery["steps"][-1]["if"], "${{ cancelled() }}")
        failure = subprocess.run(
            ["bash", "-c", delivery["steps"][-1]["run"]], capture_output=True
        )
        self.assertEqual(failure.returncode, 1)
        rules = json.loads((ROOT / ".github/delivery-ruleset.json").read_text())
        self.assertEqual(rules["bypass_actors"], [])
        policy = {r["type"]: r.get("parameters", {}) for r in rules["rules"]}
        self.assertEqual(policy["pull_request"]["required_approving_review_count"], 0)
        self.assertEqual(policy["pull_request"]["allowed_merge_methods"], ["squash"])
        self.assertTrue(
            policy["required_status_checks"]["strict_required_status_checks_policy"]
        )
        self.assertEqual(
            policy["required_status_checks"]["required_status_checks"],
            [
                {
                    "context": "Delivery / Quality / pr-full-standard-v1",
                    "integration_id": 15368,
                }
            ],
        )
        self.assertIn("required_linear_history", policy)
        self.assertEqual(jobs["publish"]["needs"], ["build", "delivery"])
        verify = next(
            s
            for s in jobs["build"]["steps"]
            if s["name"] == "Verify the wheel and generated project contracts"
        )
        self.assertEqual(verify["env"]["CXX_TEST_VCPKG"], "1")
        self.assertEqual(verify["env"]["CXX_TEST_CLANGD"], "1")
        self.assertIn("python3 -m unittest discover -s tests -v", verify["run"])
        self.assertEqual(jobs["publish"]["permissions"], {"id-token": "write"})


if __name__ == "__main__":
    unittest.main()
