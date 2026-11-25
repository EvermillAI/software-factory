"""Two clones of one origin stand in for two computers running the factory."""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sh(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout


class TwoClones(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        origin = self.tmp / "origin.git"
        sh("git", "init", "-q", "--bare", "-b", "main", str(origin))
        seed = self.tmp / "seed"
        sh("git", "clone", "-q", str(origin), str(seed))
        shutil.copytree(ROOT / "factory", seed / "factory", ignore=shutil.ignore_patterns("jobs"))
        (seed / ".gitignore").write_text("/factory/jobs/\n/.worktrees/\n")
        sh("git", "add", "-A", cwd=seed)
        sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed", cwd=seed)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=seed)
        self.a, self.b = self.tmp / "a", self.tmp / "b"
        for clone in (self.a, self.b):
            sh("git", "clone", "-q", str(origin), str(clone))
        bindir = self.tmp / "bin"
        bindir.mkdir()
        shutil.copy(ROOT / "tests" / "fake_gh", bindir / "gh")
        (bindir / "gh").chmod(0o755)
        me = {f"GIT_{who}_{what}": "t@t" for who in ("AUTHOR", "COMMITTER") for what in ("NAME", "EMAIL")}
        self.env = {**os.environ, **me, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_GH": str(self.tmp)}

    def job(self, clone, *args, stdin=None):
        return subprocess.run([str(clone / "factory" / "bin" / "job"), *args],
                              capture_output=True, text=True, env=self.env, input=stdin)

    def log(self):
        return (self.tmp / "log").read_text()

    def remote_heads(self):
        return sh("git", "--git-dir", str(self.tmp / "origin.git"), "for-each-ref", "--format=%(refname)")


class ClaimTest(TwoClones):
    def test_create_claims_the_issue(self):
        res = self.job(self.a, "create", "7")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "007-add-dark-mode")
        job = json.loads((self.a / "factory/jobs/007-add-dark-mode/job.json").read_text())
        self.assertEqual(job["branch"], "factory/7")
        self.assertIn("refs/heads/factory/7", self.remote_heads())
        self.assertIn("--add-label factory:in-progress", self.log())
        self.assertIn(socket.gethostname(), self.log())  # the claim comment names the machine

    def test_second_machine_is_refused(self):
        self.job(self.a, "create", "7")
        res = self.job(self.b, "create", "7")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("claimed", res.stderr)
        self.assertFalse((self.b / "factory/jobs").exists() and any((self.b / "factory/jobs").iterdir()))

    def test_queue_skips_an_issue_claimed_elsewhere(self):
        self.job(self.a, "create", "7")
        self.assertTrue(self.job(self.a, "queue").stdout.startswith("resume\t7\t"))
        row = self.job(self.b, "queue").stdout
        self.assertTrue(row.startswith("skip\t7\t"), row)
        self.assertIn("claimed", row)

    def test_release_frees_a_claim_without_an_open_pr(self):
        self.job(self.a, "create", "7")
        (self.tmp / "prs.json").write_text('[{"number": 3}]')
        res = self.job(self.b, "release", "7")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("PR #3", res.stderr)
        (self.tmp / "prs.json").unlink()
        res = self.job(self.b, "release", "7")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("factory/7", self.remote_heads())
        self.assertIn("--remove-label factory:in-progress", self.log())
        self.assertEqual(self.job(self.b, "create", "7").returncode, 0)

    def test_release_refuses_a_job_this_machine_is_running(self):
        self.job(self.a, "create", "7")
        res = self.job(self.a, "release", "7")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("factory/7", self.remote_heads())

    def test_a_finished_job_gives_up_its_claim(self):
        self.job(self.a, "create", "7")
        (self.a / "factory/jobs/007-add-dark-mode/intake.md").write_text("DECISION: REJECT\n\nNot for this repo.\n")
        res = self.job(self.a, "advance", "7", "rejected")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("factory/7", self.remote_heads())
        self.assertIn("--remove-label factory:in-progress", self.log())


if __name__ == "__main__":
    unittest.main()
