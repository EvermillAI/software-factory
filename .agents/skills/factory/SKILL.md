---
name: factory
description: Run the software factory on GitHub issues from Codex. Use when the user asks for "factory run", "factory run <n>", "factory release <n>", "factory update", or says anything else to the factory (a question, feedback on a job, a new feature).
---

# Factory (Codex)

Read `.claude/skills/factory/SKILL.md` in this repo and follow it. It is the one
description of the pipeline, the files, the scripts and the guardrails. It was
written for Claude Code, so apply these differences:

**Spawning an agent.** There is no Agent tool here. Run the agent as a shell
command from the main checkout and wait for it:

```bash
factory/bin/agent <role> "<header> <rest of the prompt>"
factory/bin/agent reviewer-<r> "<header> Review round <N>." --model <model from job.json agents.reviewers>
```

The script reads `config.json` `runtime` and runs the role with Codex,
with `claude -p`, or with a runner (Gemini, Cursor, Grok). You call it the
same way either way.

`<role>` is `intake`, `spec-writer`, `builder`, `reviewer-<r>`, `approver` or
`retro`.
The command prints the agent's one-line reply when it finishes. Pass `--model`
only for reviewers, with the value from `job.json`. A build can take a long
time: give the command the longest timeout you can, and if it is cut off, read
`build.md` and `git log` in the worktree before starting the builder again.

**Gate and reviewers in parallel.** Start the gate and the reviewers that don't
wait for it in one shell command, and wait for all of them. Read the gate's
verdict from `round-<N>/checks.md`:

```bash
factory/bin/gate <id> &
factory/bin/agent reviewer-code "<prompt>" --model sonnet &
wait
```

`job advance <id> gate` prints which reviewers start with the gate and which
after it. Start the second group the same way once the gate passed.

**Creating a job.** Use `factory/bin/job create <n> --host codex`, so the board
shows which CLI and model each role runs on.

**No SendMessage.** A builder can't be resumed. Every build round starts a new
`builder`, told what the round is for and that it is resuming: it reads
`build.md` and `git log` to see where the last one stopped. This is the same
path the Claude skill uses after a dead session.

**One job at a time.** Agents block your shell, so finish a job's current step
before you start another job's. `concurrency` still caps how many jobs are open.

**Cost.** `cost_usd` counts Claude Code subagent transcripts only. Jobs run
here show `$0.00`, also for roles that ran on Claude; say so when you print the summary.

Everything else is the same: every change of state goes through
`factory/bin/job`, the gate is `factory/bin/gate`, routing is
`factory/bin/route`, and you never write code, specs, reviews or decisions
yourself.
