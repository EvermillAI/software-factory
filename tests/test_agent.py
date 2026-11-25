"""factory/bin/agent turns a Claude agent file into a `codex exec` call."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEX = json.loads((ROOT / "factory/config.json").read_text())["codex"]


def dry(*args):
    res = subprocess.run([str(ROOT / "factory/bin/agent"), *args], capture_output=True, text=True,
                         env={**os.environ, "FACTORY_DRY_RUN": "1"})
    return res, (json.loads(res.stdout) if res.returncode == 0 else None)


class AgentTest(unittest.TestCase):
    def test_prompt_is_the_agent_body_then_the_job_prompt(self):
        res, out = dry("intake", "Job: 007-x. Issue: #7.")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("tools: Read", out["stdin"])  # frontmatter is Claude's, not Codex's
        self.assertIn("intake.md", out["stdin"])
        self.assertTrue(out["stdin"].rstrip().endswith("Job: 007-x. Issue: #7."))

    def test_model_comes_from_the_agent_file_unless_routed(self):
        _, out = dry("builder", "p")
        self.assertEqual(out["cmd"][out["cmd"].index("-m") + 1], CODEX["models"]["opus"])
        _, out = dry("reviewer-code", "p", "--model", "sonnet")
        self.assertEqual(out["cmd"][out["cmd"].index("-m") + 1], CODEX["models"]["sonnet"])

    def test_sandbox_per_role(self):
        _, builder = dry("builder", "p")
        self.assertEqual(builder["cmd"][builder["cmd"].index("-s") + 1], CODEX["sandbox"]["builder"])
        _, intake = dry("intake", "p")
        self.assertEqual(intake["cmd"][intake["cmd"].index("-s") + 1], "workspace-write")
        # Intake reads untrusted issue text, so it gets no network.
        self.assertNotIn("sandbox_workspace_write.network_access=true", intake["cmd"])
        # So does retro: it reads reviews and feedback that quote the issue.
        res, retro = dry("retro", "p")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("sandbox_workspace_write.network_access=true", retro["cmd"])
        _, reviewer = dry("reviewer-code", "p")
        self.assertIn("sandbox_workspace_write.network_access=true", reviewer["cmd"])

    def test_unknown_role_is_refused(self):
        res, _ = dry("nope", "p")
        self.assertNotEqual(res.returncode, 0)


class TempFactory(unittest.TestCase):
    """A copy of the factory whose config.json a test can change."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        shutil.copytree(ROOT / "factory", self.tmp / "factory", ignore=shutil.ignore_patterns("jobs"))
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude")

    def agent(self, runtime, *args, models=None):
        path = self.tmp / "factory/config.json"
        config = json.loads(path.read_text())
        config["runtime"] = runtime
        if models is not None:
            for runner in config["runners"].values():
                runner["models"] = {tier: models.format(tier=tier) for tier in runner["models"]}
        path.write_text(json.dumps(config))
        return subprocess.run([str(self.tmp / "factory/bin/agent"), *args], capture_output=True, text=True,
                              env={**os.environ, "FACTORY_DRY_RUN": "1"})

    def cmd(self, runtime, *args, **kw):
        res = self.agent(runtime, *args, **kw)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)


class HybridTest(TempFactory):
    """config.json `runtime` says which CLI runs a role, relative to the orchestrator."""

    def test_other_means_the_cli_that_is_not_orchestrating(self):
        cross = {"reviewers": "other"}
        self.assertEqual(self.cmd(cross, "--host", "claude", "reviewer-code", "p")["cmd"][:2], ["codex", "exec"])
        self.assertEqual(self.cmd(cross, "--host", "codex", "reviewer-code", "p")["cmd"][0], "claude")
        # Roles without an entry stay with the orchestrator.
        self.assertEqual(self.cmd(cross, "--host", "codex", "builder", "p")["cmd"][:2], ["codex", "exec"])

    def test_a_role_entry_beats_the_reviewers_entry(self):
        out = self.cmd({"reviewers": "other", "reviewer-security": "claude"},
                       "--host", "claude", "reviewer-security", "p")
        self.assertEqual(out["cmd"][0], "claude")

    def test_claude_runs_the_agent_file_itself(self):
        out = self.cmd({"reviewers": "claude"}, "--host", "codex", "reviewer-code", "PROMPT", "--model", "sonnet")
        cmd = out["cmd"]
        self.assertEqual(cmd[cmd.index("--agent") + 1], "reviewer-code")
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")
        self.assertEqual(cmd[cmd.index("--allowedTools") + 1], "Read,Grep,Glob,Bash,Write")
        self.assertEqual(out["stdin"].strip(), "PROMPT")  # claude loads the body from the agent file

    def test_who_names_the_cli_and_the_model_behind_a_role(self):
        who = lambda *args: self.agent({"reviewers": "other"}, *args).stdout.strip()
        self.assertEqual(who("--host", "claude", "--who", "builder"), "claude opus")
        self.assertEqual(who("--host", "codex", "--who", "builder"), f"codex {CODEX['models']['opus']}")
        self.assertEqual(who("--host", "claude", "--who", "reviewer-code", "--model", "sonnet"),
                         f"codex {CODEX['models']['sonnet']}")
        res = self.agent({"reviewers": "gemini"}, "--who", "reviewer-code", models="m-{tier}")
        self.assertEqual(res.stdout.strip(), "gemini m-haiku")

    def test_which_tells_the_orchestrator_where_a_role_runs(self):
        res = self.agent({"reviewers": "other"}, "--host", "claude", "--which", "reviewer-ux")
        self.assertEqual(res.stdout.strip(), "codex")


class RunnerTest(TempFactory):
    """config.json `runners` adds other agent CLIs as command templates."""

    def test_each_runner_builds_its_command(self):
        for name, binary in (("gemini", "gemini"), ("cursor", "agent"), ("grok", "grok")):
            with self.subTest(name):
                cmd = self.cmd({"reviewers": name}, "reviewer-code", "JOBPROMPT", "--model", "sonnet",
                               models="m-{tier}")["cmd"]
                self.assertEqual(cmd[0], binary)
                self.assertIn("m-sonnet", cmd)
                prompt = cmd[-1]
                self.assertIn("review-code.md", prompt)  # the agent file's body
                self.assertTrue(prompt.rstrip().endswith("JOBPROMPT"))
                self.assertNotIn("{", " ".join(cmd[:-1]))  # every placeholder is filled

    def test_repo_placeholder_is_the_checkout(self):
        cmd = self.cmd({"builder": "cursor"}, "builder", "p", models="m-{tier}")["cmd"]
        self.assertEqual(Path(cmd[cmd.index("--workspace") + 1]).resolve(), self.tmp.resolve())

    def test_which_prints_the_runner(self):
        res = self.agent({"reviewers": "grok"}, "--which", "reviewer-ux")
        self.assertEqual(res.stdout.strip(), "grok")

    def test_unknown_runner_is_refused(self):
        res = self.agent({"reviewers": "llama"}, "reviewer-code", "p")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("llama", res.stderr)

    def test_a_runner_without_models_is_refused(self):
        res = self.agent({"reviewers": "gemini"}, "reviewer-code", "p")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("runners.gemini.models", res.stderr)

    def test_roles_that_read_untrusted_text_never_run_on_a_runner(self):
        for role in ("intake", "retro"):
            for args in ((role, "p"), ("--which", role)):
                res = self.agent({role: "gemini"}, *args, models="m-{tier}")
                self.assertNotEqual(res.returncode, 0)
                self.assertIn(role, res.stderr)


if __name__ == "__main__":
    unittest.main()
