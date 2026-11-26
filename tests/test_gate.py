"""The gate and the reviewers overlap, and a merge doesn't test one commit twice."""
import json
import unittest

from test_claim import TwoClones, sh

JOB = "007-add-dark-mode"


class JobWithPR(TwoClones):
    def setUp(self):
        super().setUp()
        self.job(self.a, "create", "7")
        self.dir = self.a / "factory/jobs" / JOB
        self.tree = self.a / ".worktrees" / JOB
        sh("git", "fetch", "-q", "origin", cwd=self.a)
        sh("git", "worktree", "add", "-q", "-b", "factory/7", str(self.tree), "origin/factory/7", cwd=self.a)
        (self.tree / "feature.txt").write_text("dark\n")
        sh("git", "add", "-A", cwd=self.tree)
        sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "feature", cwd=self.tree)
        (self.dir / "round-1").mkdir()
        self.state(round=1, pr=3, agents={"reviewers": {"code": "sonnet"}})

    def state(self, **fields):
        path = self.dir / "job.json"
        job = json.loads(path.read_text())
        path.write_text(json.dumps({**job, **fields}))
        return job

    def head(self):
        return sh("git", "rev-parse", "HEAD", cwd=self.tree).strip()

    def passed(self, commit=None):
        (self.dir / "round-1/checks.md").write_text(f"GATE: PASS\nCOMMIT: {commit or self.head()}\n")

    def merge(self):
        self.state(stage="merging")
        res = self.job(self.a, "merge", "7")
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout


class GateTest(JobWithPR):
    def test_a_review_written_while_the_gate_runs_counts(self):
        self.state(stage="gate")
        (self.dir / "round-1/review-code.md").write_text("VERDICT: PASS\n")
        self.assertIn("code:PASS", self.job(self.a, "sync", "7").stdout)
        self.passed()
        self.assertEqual(self.job(self.a, "advance", "7", "review").returncode, 0)
        res = self.job(self.a, "advance", "7", "approve")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_the_job_waits_for_the_reviewers_that_started_with_the_gate(self):
        self.state(stage="gate", agents={"reviewers": {"code": "sonnet", "ux": "sonnet"}})
        self.passed()
        res = self.job(self.a, "advance", "7", "review")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("missing reviews from: code", res.stderr)  # ux starts after the gate
        (self.dir / "round-1/review-code.md").write_text("VERDICT: PASS\n")
        res = self.job(self.a, "advance", "7", "review")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_advance_says_who_reviews_with_the_gate(self):
        self.state(stage="build", agents={"reviewers": {"code": "sonnet", "ux": "sonnet"}})
        (self.dir / "build.md").write_text("STATUS: READY\n")
        sh("git", "push", "-q", "origin", "factory/7", cwd=self.tree)
        (self.tmp / "prs.json").write_text('[{"number": 3, "url": "u"}]')
        res = self.job(self.a, "advance", "7", "gate")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("with the gate: code; after it: ux", res.stdout)

    def test_merge_skips_the_gate_when_the_base_did_not_move(self):
        self.passed()
        # The placeholder checks.sh fails, so this merges only if the gate is skipped.
        self.assertIn("merged PR #3", self.merge())
        self.assertIn("Reused checks.md", (self.dir / "round-1/merge-checks.md").read_text())
        self.assertFalse((self.dir / "round-1/merge-checks.log").exists())
        self.assertIn("pr merge 3", self.log())

    def test_merge_runs_the_gate_when_the_base_moved(self):
        self.passed()
        (self.a / "factory/checks.sh").write_text("exit 0\n")
        (self.b / "other.txt").write_text("x\n")
        sh("git", "add", "-A", cwd=self.b)
        sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "other", cwd=self.b)
        sh("git", "push", "-q", "origin", "main", cwd=self.b)
        self.assertIn("merged PR #3", self.merge())
        self.assertIn("GATE: PASS", (self.dir / "round-1/merge-checks.md").read_text())

    def test_merge_runs_the_gate_when_it_passed_another_commit(self):
        self.passed("0" * 40)
        self.assertIn("needs-human", self.merge())  # the placeholder checks.sh fails
        self.assertTrue((self.dir / "round-1/merge-checks.log").exists())


class AutoMergeTest(JobWithPR):
    """The base branch requires checks that are still running when the approver is done."""

    def setUp(self):
        super().setUp()
        self.passed()
        (self.tmp / "protected").touch()

    def stage(self):
        return self.state()["stage"]

    def test_a_merge_github_refuses_is_handed_to_auto_merge(self):
        self.assertIn("waiting", self.merge())
        self.assertEqual(self.stage(), "merging")
        self.assertIn("pr merge 3 --merge --auto", self.log())

    def test_a_waiting_job_is_not_merged_or_pushed_again(self):
        self.merge()
        (self.tmp / "checks").write_text("pending\n")
        self.assertIn("waiting", self.job(self.a, "merge", "7").stdout)
        self.assertEqual(self.log().count("pr merge 3 --merge"), 2)  # the refused one and --auto

    def test_a_waiting_job_holds_no_slot_and_shows_as_wait(self):
        self.merge()
        row = self.job(self.a, "queue").stdout
        self.assertTrue(row.startswith("wait\t7\t"), row)
        self.assertIn("GitHub merges PR #3", row)
        self.assertEqual(self.job(self.a, "create", "8").returncode, 0)  # the one slot is free

    def test_the_job_is_merged_once_github_merged_it(self):
        self.merge()
        (self.tmp / "merged").touch()
        self.assertIn("merged PR #3", self.job(self.a, "merge", "7").stdout)
        self.assertEqual(self.stage(), "merged")
        watched = self.log().count("pr checks")
        self.job(self.a, "queue")
        self.assertEqual(self.log().count("pr checks"), watched)  # a merged job is not watched any more

    def test_a_failed_required_check_goes_to_a_human(self):
        self.merge()
        (self.tmp / "checks").write_text("pass\nfail\n")
        self.assertIn("needs-human", self.job(self.a, "queue").stdout)
        self.assertEqual(self.stage(), "needs-human")
        self.assertIn("pr merge 3 --disable-auto", self.log())
        self.assertIn("required check", (self.dir / "decision.md").read_text())

    def test_a_merge_that_waits_for_a_review_goes_to_a_human(self):
        (self.tmp / "review").write_text("REVIEW_REQUIRED\n")
        self.assertIn("needs-human", self.merge())
        self.assertNotIn("--auto", self.log())

    def test_the_next_round_merges_again_after_an_escalation(self):
        self.merge()
        (self.tmp / "checks").write_text("fail\n")
        self.job(self.a, "queue")
        (self.tmp / "protected").unlink()
        (self.dir / "decision.md").write_text("APPROVE\n")
        self.assertIn("merged PR #3", self.merge())


if __name__ == "__main__":
    unittest.main()
