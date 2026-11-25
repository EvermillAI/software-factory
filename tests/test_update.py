"""factory/bin/update moves a project's factory from one release to the next."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_claim import ROOT, sh

AGENT = ".claude/agents/reviewer-code.md"
V1 = {
    AGENT: "intro\n\n\n\nchecklist\n\n\n\nreply\n",
    "factory/bin/job": "job v1\n",
    "factory/bin/old": "old\n",
    "factory/checks.sh": "placeholder\n",
    "factory/LESSONS.md": "# Lessons\n",
    "README.md": "readme v1\n",
}
V2 = {
    **V1,
    AGENT: "intro\n\n\n\nchecklist\n\n\n\nreply v2\n",
    "factory/bin/job": "job v2\n",
    "factory/bin/new": "new\n",
    "factory/checks.sh": "placeholder v2\n",
    "factory/LESSONS.md": "# Lessons v2\n",
    "README.md": "readme v2\n",
}
del V2["factory/bin/old"]


def commit(repo, msg):
    sh("git", "add", "-A", cwd=repo)
    sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg, cwd=repo)


def write(repo, files):
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)


class UpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # No test changes the source, so build its two releases once.
        cls.source = source = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, source)
        sh("git", "init", "-q", "-b", "main", str(source))
        write(source, V1)
        commit(source, "v1")
        sh("git", "tag", "v1", cwd=source)
        (source / "factory/bin/old").unlink()
        write(source, V2)
        (source / "factory/bin/new").chmod(0o755)
        commit(source, "v2")
        sh("git", "tag", "v2", cwd=source)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.project = self.tmp / "project"
        sh("git", "init", "-q", "-b", "main", str(self.project))
        write(self.project, {**{k: v for k, v in V1.items() if k != "README.md"}, "factory/VERSION": "v1\n"})
        shutil.copy(ROOT / "factory/bin/update", self.project / "factory/bin/update")
        commit(self.project, "install")

        bindir = self.tmp / "bin"
        bindir.mkdir()
        shutil.copy(ROOT / "tests" / "fake_gh", bindir / "gh")
        (bindir / "gh").chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_GH": str(self.tmp),
                    "FACTORY_SOURCE": str(self.source)}

    def update(self, *args):
        return subprocess.run([str(self.project / "factory/bin/update"), *args],
                              capture_output=True, text=True, env=self.env)

    def read(self, path):
        return (self.project / path).read_text()

    def edit(self, path, text):
        write(self.project, {path: text})
        commit(self.project, "tailor")

    def test_untouched_files_move_to_the_release(self):
        res = self.update("v2")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.read("factory/bin/job"), "job v2\n")
        self.assertEqual(self.read(AGENT), V2[AGENT])
        self.assertEqual(self.read("factory/VERSION"), "v2\n")
        self.assertFalse((self.project / "README.md").exists())  # only the factory's folders

    def test_files_come_and_go_with_the_release(self):
        self.update("v2")
        self.assertTrue(os.access(self.project / "factory/bin/new", os.X_OK))
        self.assertFalse((self.project / "factory/bin/old").exists())

    def test_the_projects_own_files_are_never_touched(self):
        self.update("v2")
        self.assertEqual(self.read("factory/checks.sh"), "placeholder\n")
        self.assertEqual(self.read("factory/LESSONS.md"), "# Lessons\n")

    def test_a_tailored_file_keeps_its_changes(self):
        self.edit(AGENT, "intro\n\n\n\nchecklist for this stack\n\n\n\nreply\n")
        res = self.update("v2")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.read(AGENT), "intro\n\n\n\nchecklist for this stack\n\n\n\nreply v2\n")
        self.assertIn(f"merged\t{AGENT}", res.stdout)

    def test_a_conflict_is_marked_and_fails_the_run(self):
        self.edit(AGENT, "intro\n\n\n\nchecklist\n\n\n\nmy reply\n")
        self.edit("factory/bin/old", "mine\n")
        res = self.update("v2")
        self.assertEqual(res.returncode, 1)
        self.assertIn(f"CONFLICT\t{AGENT}", res.stdout)
        self.assertIn("<<<<<<<", self.read(AGENT))
        self.assertEqual(self.read("factory/bin/job"), "job v2\n")  # the rest still updates
        self.assertEqual(self.read("factory/bin/old"), "mine\n")  # dropped by the release, changed here
        self.assertEqual(self.read("factory/VERSION"), "v2\n")

    def test_a_deleted_file_stays_deleted(self):
        (self.project / AGENT).unlink()
        commit(self.project, "no code reviewer")
        self.assertEqual(self.update("v2").returncode, 0)
        self.assertFalse((self.project / AGENT).exists())

    def test_uncommitted_factory_changes_are_refused(self):
        write(self.project, {"factory/bin/job": "half an edit\n"})
        res = self.update("v2")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("commit", res.stderr)
        self.assertEqual(self.read("factory/bin/job"), "half an edit\n")

    def test_other_uncommitted_work_is_no_obstacle(self):
        write(self.project, {".claude/settings.json": "{}\n"})
        self.assertEqual(self.update("v2").returncode, 0)

    def test_without_a_tag_it_takes_the_latest_release(self):
        (self.tmp / "release").write_text("v2\n")
        res = self.update()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.read("factory/VERSION"), "v2\n")
        self.assertIn("releases/latest", (self.tmp / "log").read_text())

    def test_the_installed_release_is_up_to_date(self):
        res = self.update("v1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("up to date", res.stdout)

    def test_an_install_without_a_version_is_refused(self):
        (self.project / "factory/VERSION").unlink()
        commit(self.project, "lost it")
        res = self.update("v2")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("factory/VERSION", res.stderr)


if __name__ == "__main__":
    unittest.main()
