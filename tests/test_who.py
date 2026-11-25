"""job.json says which CLI, model and machine a job's agents run on, for the board."""
import json
import shutil
import socket
import subprocess
import unittest

from test_claim import ROOT, TwoClones

JOB = "007-add-dark-mode"
CODEX = json.loads((ROOT / "factory/config.json").read_text())["codex"]["models"]


class WhoTest(TwoClones):
    def setUp(self):
        super().setUp()
        shutil.copytree(ROOT / ".claude", self.a / ".claude")

    def state(self):
        return json.loads((self.a / "factory/jobs" / JOB / "job.json").read_text())

    def test_create_records_the_machine_and_the_planned_agents(self):
        res = self.job(self.a, "create", "7", "--host", "codex")
        self.assertEqual(res.returncode, 0, res.stderr)
        job = self.state()
        self.assertEqual(job["machine"], socket.gethostname())
        self.assertEqual(job["who"]["builder"], {"cli": "codex", "model": CODEX["opus"]})
        self.assertEqual(job["who"]["intake"], {"cli": "codex", "model": CODEX["fable"]})

    def test_without_a_host_nothing_is_guessed(self):
        self.job(self.a, "create", "7")
        self.assertEqual(self.state()["who"], {})
        self.assertEqual(self.state()["machine"], socket.gethostname())

    def test_an_unknown_host_is_refused_before_the_claim(self):
        res = self.job(self.a, "create", "7", "--host", "llama")
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn("factory/7", self.remote_heads())

    def test_routing_adds_the_reviewers(self):
        self.job(self.a, "create", "7", "--host", "claude")
        (self.a / "factory/jobs" / JOB / "intake.md").write_text(
            "DECISION: ACCEPT\nRESCOPED: no\nRISK: low\nSURFACES: none\n\nFine.\n")
        res = subprocess.run([str(self.a / "factory/bin/route"), JOB], capture_output=True, text=True, env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.state()["who"]["reviewer-code"], {"cli": "claude", "model": "haiku"})


if __name__ == "__main__":
    unittest.main()
