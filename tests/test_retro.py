"""After a merged job that needed more than one round, retro proposes lessons in a PR."""
import json
import subprocess
import unittest

from test_claim import TwoClones, sh

JOB = "007-add-dark-mode"
LESSONS = "factory/LESSONS.md"


class RetroTest(TwoClones):
    def setUp(self):
        super().setUp()
        self.job(self.a, "create", "7")
        self.tree = self.a / ".worktrees" / f"retro-{JOB}"

    def state(self, **fields):
        path = self.a / "factory/jobs" / JOB / "job.json"
        job = json.loads(path.read_text())
        if fields:
            path.write_text(json.dumps({**job, **fields}))
        return job

    def start(self):
        self.state(stage="merged", round=2)
        res = self.job(self.a, "retro", "7", "start")
        self.assertEqual(res.returncode, 0, res.stderr)
        return res

    def learn(self, n=1):
        with (self.tree / LESSONS).open("a") as f:
            f.write("".join(f"- Lesson {i} (#7).\n" for i in range(n)))

    def test_a_job_that_passed_in_one_round_has_nothing_to_learn(self):
        self.state(stage="merged", round=1)
        res = self.job(self.a, "retro", "7", "start")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("skip", res.stdout)
        self.assertFalse(self.tree.exists())

    def test_feedback_makes_a_one_round_job_worth_a_retro(self):
        self.state(stage="merged", round=1)
        (self.a / "factory/jobs" / JOB / "feedback-1.md").write_text("# Feedback 1\n")
        self.job(self.a, "retro", "7", "start")
        self.assertTrue(self.tree.exists())

    def test_start_gives_the_agent_a_worktree_on_its_own_branch(self):
        res = self.start()
        self.assertIn(str(self.tree), res.stdout)
        self.assertEqual(sh("git", "branch", "--show-current", cwd=self.tree).strip(), "retro/7")

    def test_only_a_merged_job_gets_a_retro(self):
        res = self.job(self.a, "retro", "7", "start")
        self.assertNotEqual(res.returncode, 0)
        self.assertFalse(self.tree.exists())

    def test_finish_opens_a_pr_with_the_lessons(self):
        self.start()
        self.learn()
        res = self.job(self.a, "retro", "7", "finish")
        self.assertEqual(res.returncode, 0, res.stderr)
        origin = ["git", "--git-dir", str(self.tmp / "origin.git")]
        self.assertIn("Lesson 0", sh(*origin, "show", f"retro/7:{LESSONS}"))
        self.assertNotIn("Lesson 0", sh(*origin, "show", f"main:{LESSONS}"))  # a human merges it
        self.assertIn("pr create", self.log())
        self.assertNotIn("pr merge", self.log())
        self.assertEqual(self.state()["retro"], "https://example.test/pull/9")
        self.assertFalse(self.tree.exists())

    def test_finish_without_changes_opens_nothing(self):
        self.start()
        res = self.job(self.a, "retro", "7", "finish")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.state()["retro"], "none")
        self.assertNotIn("pr create", self.log())
        self.assertNotIn("retro/7", self.remote_heads())

    def test_finish_refuses_any_other_file(self):
        self.start()
        self.learn()
        (self.tree / "factory/checks.sh").write_text("exit 0\n")
        res = self.job(self.a, "retro", "7", "finish")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("checks.sh", res.stderr)
        self.assertNotIn("retro/7", self.remote_heads())
        self.assertTrue(self.tree.exists())  # the agent can be sent back to fix it

    def test_finish_refuses_more_lessons_than_the_limit(self):
        limit = json.loads((self.a / "factory/config.json").read_text())["max_lessons"]
        self.start()
        self.learn(limit + 1)
        res = self.job(self.a, "retro", "7", "finish")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn(str(limit), res.stderr)
        self.assertNotIn("retro/7", self.remote_heads())

    def test_queue_lists_a_merged_job_that_still_needs_its_retro(self):
        self.state(stage="merged", round=2)
        self.assertTrue(self.job(self.a, "queue").stdout.startswith("retro\t7\t"))
        self.state(retro="none")
        self.assertTrue(self.job(self.a, "queue").stdout.startswith("skip\t7\t"))
        self.state(retro=None, round=1)  # passed first time: nothing to learn
        self.assertTrue(self.job(self.a, "queue").stdout.startswith("skip\t7\t"))


if __name__ == "__main__":
    unittest.main()
