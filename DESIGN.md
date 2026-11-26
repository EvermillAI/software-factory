# Design

How the v2 factory works, and why it's built this way. The source is small
enough to read in one sitting: one skill, eight agents, three scripts and a
config file.

## The idea

A software factory turns a queue of requests into merged code with a fixed
pipeline. Scripts handle the deterministic stages, such as running the tests,
moving state and merging. Agents do the judgment in between: whether a request
is worth building, what exactly to build, the code itself, and whether it's
good. Each stage leaves a file behind, so you can see what happened and why.
Every step's file opens with a `## Summary` of three to five bullets, so a human can
skim a job on the dashboard and read the detail only where it matters.

## Pieces

| Piece | File | Job |
|---|---|---|
| Queue | GitHub issues labeled `factory` | What to build. Anyone can file an issue; only people with triage or write access can label it. |
| Orchestrator | `.claude/skills/factory/SKILL.md` | The session that runs `/factory`. Starts jobs, spawns agents, calls the scripts. Writes nothing itself. |
| Agents | `.claude/agents/*.md` | One file per role. Each reads files, writes exactly one file, and replies with one line. |
| State | `factory/jobs/<job-id>/` | `job.json` plus every agent's file. Gitignored, local to the machine running the factory. |
| Claim | branch `factory/<issue>` on origin | Which machine has the issue. Created by `job create`, deleted when the job is merged or rejected. |
| Codex runner | `factory/bin/agent`, `.agents/skills/factory/SKILL.md` | Runs the same agent files with `codex exec` when the orchestrator is Codex. |
| Spine | `factory/bin/job`, `gate`, `route` | Deterministic. `job` is the only writer of `job.json` and refuses illegal moves. |
| Lessons | `factory/LESSONS.md`, `.claude/agents/retro.md` | Rules from earlier jobs, read by every later spec-writer, builder and reviewer. Changed only by a retro PR a person merges. |
| Update | `factory/bin/update`, `factory/VERSION` | Moves the installed files to a newer release with a three-way merge per file, so the project's tailoring stays. Never touches `checks.sh` or `LESSONS.md`, never commits. |
| Checks | `factory/checks.sh` | The repo's test, lint, typecheck and build commands. The only repo-specific script. |
| Exit | the PR | Every job ends as a PR that closes its issue. Merging it is the approval. |

## Pipeline

```
intake (fable)     → ACCEPT (scope possibly changed) | NEEDS-INFO | REJECT, posted as an issue comment
route (script)     → reviewers + models from risk/surfaces via config.json
worktree           → factory/<issue> from origin/main
spec-writer (opus) → spec.md
builder            → commits; first round pushes + opens draft PR "Closes #<n>"
gate (script)      → checks.sh, alongside the reviewers that only read; FAIL → builder gets the log and those reviews
reviewers (routed) → parallel, WAIT FOR ALL; CHANGES → builder → gate → reviewers (max rounds)
approver (opus)    → APPROVE: sync origin/main, gate again if that moved the branch, gh pr merge
                     ESCALATE: PR ready, decision as PR comment, label factory:needs-human
retro (sonnet)     → merged after more than one round or after feedback: PR on factory/LESSONS.md
```

`stage` in `job.json` is one of `intake`, `needs-info`, `spec`, `build`,
`gate`, `review`, `approve`, `merging`, `needs-human`, `merged`, `rejected`.
The legal moves are in `TRANSITIONS` at the top of `factory/bin/job`.

## Decisions

**Issues are the queue; you trigger the run.** `/factory run` drains every open
`factory` issue. Nothing runs in GitHub Actions or on a schedule: the factory
runs on your machine, on your Claude plan, when you start it. An issue can't
start a Claude Code session by itself, and keeping it local means your
worktrees, dev servers and dashboard are right there.

**One orchestrator for every job.** The session running `/factory run` starts up
to `concurrency` jobs and spawns every agent as a background subagent. There
are no per-job orchestrators to coordinate. Its context stays small because
agents reply with one line and the scripts print one line; the detail lives in
files the next agent reads. Claude Code allows 20 concurrent subagents per
session by default, which covers three jobs with four reviewers each.

**Fable at the door, once.** Intake is the only Fable call per job. It decides
whether the issue is worth building, rewrites the scope when the issue is too
big or vague, and asks the author when only they can answer. Its decision goes
on the issue as a comment; the issue body stays as written. Questions go to
the author before a spec exists, so the spec writer never stalls on one.

**Risk routes the work, a script does the routing.** Intake rates risk (`low`,
`medium`, `high`) and surfaces (`ui`, `security`). `factory/bin/route` looks
them up in `config.json`:

| | code review | ux | ui | security |
|---|---|---|---|---|
| low | Haiku | | | |
| medium | Sonnet | | | |
| high | Sonnet | | | |
| + `ui` surface | | Sonnet | Haiku | |
| + `security` surface | | | | Opus |

The builder always runs on Opus.

A low-risk change with no UI runs one Haiku reviewer. Routing is visible in
one file and changes without touching a prompt.

**Scripts decide whether it works.** The gate runs `checks.sh` on every build, and
again before the merge when syncing with `main` brought anything in: a sync
that changes nothing leaves the commit the gate already passed. To save the
wait, the reviewers that only read the code start with the gate instead of
after it. A job still moves on only when the gate passed and every review is
in, so the overlap changes when things run, not what has to be true; `job
advance` refuses to leave `gate` while an early review is missing, so no
reviewer is still reading the worktree when the next builder starts. Reviewers
in `reviewers_after_gate` (`ux` and `ui`) start a dev server in the worktree,
which could disturb the checks, so they start once the gate passed. A failing
build goes back to the builder with the log and whatever the early reviewers
found, so one round can fix both. The gate runs
the main checkout's copy of `checks.sh`, so a branch can't edit the checks it
is judged by. It fails any branch that modifies or deletes a file under
`protected_paths`: the factory's own checks and config. Tests aren't
protected, since features have to update them; the code reviewer fails any
test that was weakened, skipped or special-cased to pass. The
builder also has a `SubagentStop` hook that runs the checks before it finishes,
as a nudge; the gate is still what decides.

**Agents judge what scripts can't.** Reviewers don't re-run the test suite;
they read the diff for correctness, scope, security, UX and visual fit.

**A PR per issue, merged through GitHub.** v1 merged locally, which broke when
the main checkout was dirty or busy. v2 merges with `gh pr merge`, so branch
protection, required checks and the PR history all apply, and your main
checkout is never touched. Before merging, the branch is synced with `main` and
gated again, because another job may have merged since it was tested. When
the base branch requires checks that haven't finished, the factory doesn't wait
for them: it turns on GitHub's auto-merge and frees the job's slot. `job queue`
later finds the PR merged, or hands the job to a human when a required check
failed. A merge blocked by a missing review goes to a human at once, because
auto-merge would wait on it forever.

**You approve by merging.** The approver merges what it would merge itself and
escalates the rest with a specific question. An escalated PR is ready for
review and its issue is labeled `factory:needs-human`. Merge it to approve, or
tell the factory what to change with `/factory <anything>`: your words go to
the builder as `feedback-<k>.md` and the job runs another round. To drop a
job that waits on you or on its author, tell the factory to reject it: the
reason goes on the issue, its PR closes, and the job moves to Done.

**State is files, so runs resume.** Every fact the orchestrator needs is in
`factory/jobs/`. If the session dies or compacts, a fresh `/factory run` reads
the queue and resumes every job from its stage.

**Cost is measured per job.** Claude Code writes each subagent's transcript,
with model and token counts per message, to
`~/.claude/projects/<project>/<session>/subagents/`. Every factory prompt starts
with the job's folder, so `factory/bin/job` sums the transcripts that name it
and prices them with `prices_usd_per_mtok`. The figure is the API-equivalent
cost of the job's agents; on a subscription it shows relative spend, not your
bill. The orchestrator's own tokens aren't attributed to a job. The
transcript format isn't a documented interface, so a Claude Code update could
break this.

**A branch is the claim, so several machines can run the factory.** Job state
is local, so nothing used to stop two computers from building the same issue.
`job create` now creates `refs/heads/factory/<issue>` through the GitHub API
before it writes anything. GitHub refuses to create a ref that exists, so the
second machine gets an error and no job. The issue gets the label
`factory:in-progress` and a comment naming the machine; `job queue` lists
issues claimed elsewhere as `skip`. Job ids start with the issue number, so
they are the same everywhere. A job stays on the machine that claimed it:
there is no hand-over, because that would mean syncing `factory/jobs/`.
`job release <n>` deletes a claim whose machine is gone, and refuses while a
PR is open from the branch.

**One set of agent files, two runtimes.** The scripts never depended on Claude
Code; only spawning agents did. Under Codex, `factory/bin/agent` reads the same
`.claude/agents/<role>.md`, drops the frontmatter and runs `codex exec` with
the model and sandbox from `config.json` `codex`. The Codex skill is a short
list of differences that points at the Claude skill. Codex runs agents as
blocking shell commands, so it works one job at a time, can't resume a
builder, and has no builder stop hook and no cost figure. The builder runs in
`danger-full-access` because commits in a worktree write to the main
checkout's `.git`.

**The builder and its reviewers can be different models.** A reviewer from the
same model family shares the builder's blind spots. `config.json` `runtime`
maps a role to `host`, `other`, `claude` or `codex`, and `factory/bin/agent`
resolves it against the CLI that is orchestrating. With
`"reviewers": "other"` the review always comes from the other vendor,
whichever CLI you started in. Claude runs a role headless with
`claude -p --agent <role>`, so the agent file and its tool list apply
unchanged. Roles that run this way aren't in the cost figure.

**Other agents are config, not code.** Claude and Codex have their own code
paths because each has behaviour worth using: Claude loads the agent file
itself, Codex has a sandbox per role. Gemini, Cursor and Grok are entries in
`config.json` `runners`: a command with `{model}`, `{prompt}` and `{repo}`.
`factory/bin/agent` fills it in, runs it in the main checkout and prints the
last line of stdout. Runners approve every tool call, so `intake` and `retro`,
which read text nobody vetted, are refused on them. The list is
`untrusted_input` in `config.json`: those roles also get no network under
Codex.

**Lessons go through a pull request.** `factory/jobs/` is local to one machine
and no agent reads an old job, so without a retro every job repeats the last
one's mistakes. The retro writes rules where every agent already looks: a file
in the repo. Such a rule is an instruction nobody reviewed, and the reviews it
is drawn from can quote the issue, so three things keep it honest. The retro
agent has no shell and may change one file; `job retro finish` refuses a diff
that touches anything else or holds more than `max_lessons` rules. The change
lands as a PR on `retro/<issue>` that the factory never merges. And
`LESSONS.md` is a protected path, so a job's own branch can't edit it. Only
merged jobs with more than one round or with feedback get a retro: a job that
passed first time has nothing to teach, and a rejected one never reached
review.

## Guardrails

- Only issues labeled `factory` run. Labels need triage or write access, so the
  label is the trust boundary.
- Issue text reaches agents as quoted data in `issue.md`, with comments only
  from the issue's author and the factory's operator. It is never part of a
  prompt. Intake, which reads it first, has no shell.
- Agents push only `factory/*` branches. Only `factory/bin/job merge` merges,
  through `gh pr merge`. The factory never deploys.
- `factory/LESSONS.md` changes only through a retro PR that a person merges.
- One PR per issue; at most `max_rounds` build rounds per job before a human
  is asked.
