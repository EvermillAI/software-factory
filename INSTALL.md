# Install the software factory

You are a coding agent installing this factory into the user's project. Copy
what's generic, adapt what's repo-specific, verify it, and report. Work in the
project's root. Don't clone this repository.

The source is the folder the user pointed you at. On GitHub, install the
latest release: step 1 reads its tag and copies from it.

## 0. Check the project

Stop and tell the user if any of these fail:

- It's a git repo with an `origin` on GitHub, and `gh auth status` shows a user
  who can push to it and manage its labels.
- Its default branch (`gh repo view --json defaultBranchRef`) exists on
  `origin`.
- `claude --version` is 2.1.257 or later (the intake agent runs on Fable).
- `python3 --version` is 3.9 or later. The scripts use only the standard
  library.
- None of the files in step 1 already exist. If one does, show the user the
  clash and ask before overwriting.

## 1. Copy

Copy these files to the same paths in the project, unchanged:

```
.claude/skills/factory/SKILL.md
.agents/skills/factory/SKILL.md
.claude/agents/intake.md
.claude/agents/spec-writer.md
.claude/agents/builder.md
.claude/agents/reviewer-code.md
.claude/agents/reviewer-security.md
.claude/agents/reviewer-ux.md
.claude/agents/reviewer-ui.md
.claude/agents/approver.md
.claude/agents/retro.md
factory/config.json
factory/checks.sh
factory/LESSONS.md
factory/bin/job
factory/bin/gate
factory/bin/route
factory/bin/agent
factory/bin/update
factory/dashboard.html
```

```bash
TAG=$(gh api repos/EvermillAI/software-factory/releases/latest --jq .tag_name)
SRC=https://raw.githubusercontent.com/EvermillAI/software-factory/$TAG
for f in <the paths above>; do
  mkdir -p "$(dirname "$f")" && curl -fsSL "$SRC/$f" -o "$f"
done
chmod +x factory/checks.sh factory/bin/job factory/bin/gate factory/bin/route factory/bin/agent factory/bin/update
echo "$TAG" > factory/VERSION
```

`factory/VERSION` is the release you copied. `factory/bin/update` merges a
newer release against it, so write it before you adapt anything and commit it
with the rest. Copying from a local folder: use its `git describe --tags`.

Don't copy `README.md`, `DESIGN.md`, `INSTALL.md`, `LICENSE`, `NOTICE` or
`tests/`. They describe the reference, not the user's project.

## 2. Adapt

**`factory/checks.sh`.** Replace the placeholder with the project's real
checks: install dependencies if a fresh worktree needs them, then lint,
typecheck, tests and build, whichever the project has. Find them in
`AGENTS.md`, `CLAUDE.md`, `package.json` scripts, `Makefile`, `pyproject.toml`
and CI config. The script runs with a job's worktree as its working directory.
It must be non-interactive, must not rewrite files (no `--fix`, no
`--update-snapshots`), and must exit non-zero on any failure. Keep
`set -euo pipefail`.

**`factory/config.json`.**

- `base_branch`: the default branch.
- `merge_method`: `merge`, `squash` or `rebase`, one the repo allows
  (`gh api repos/{owner}/{repo} --jq '{allow_merge_commit, allow_squash_merge, allow_rebase_merge}'`).
- `protected_paths`: keep the two factory entries and don't add the project's
  tests. Features legitimately change existing tests (a new required field
  changes every fixture), and a protected test blocks the job with no way
  through. The code reviewer catches weakened or special-cased tests instead.
  Add a path only when no job should ever change it. They are fnmatch
  patterns, so `*` also matches `/`.
- `reviewers_after_gate`: reviewers that must not run while the gate does,
  because they start a dev server or build in the worktree. Keep `ux` and `ui`.
  Add `code` or `security` only if this project's checks can't share the
  worktree with a reviewer reading it.
- `ports`: move `base` if the project already uses ports 5100–5199.
- `runtime`: leave `reviewers` on `host` unless the user wants Claude and Codex
  to review each other; then set it to `other` and check both `claude` and
  `codex` run on this machine.
- `runners`: leave the models empty unless the user wants Gemini, Cursor or
  Grok. For each one they want: check the CLI is installed and signed in,
  compare its `--help` with the runner's `cmd`, and fill in `models`.
- `codex`: only matters when the factory runs from Codex. Check that the
  models exist for the user (`codex exec -m <model> "hi"`) and ask before
  changing `sandbox`.
- Leave `concurrency`, `max_rounds`, `routing`, `surface_reviewers` and
  `prices_usd_per_mtok` as they are unless the user asks.

**Agents.** The checklists are general on purpose. Tailor them to the stack
without changing their structure, file names, first-line formats or one-line
replies:

- `reviewer-security.md`: this project's hot spots (its auth, its data access
  rules, its payment and webhook code, where user input meets queries or HTML).
- `reviewer-ui.md`: where the design tokens, theme and shared components live.
- `reviewer-ux.md`: the kinds of users the app has.
- `approver.md`: what a human must always see in this project, added to the
  ESCALATE list.
- `intake.md`: one line under **Decide** saying what the project is for, so
  intake can tell what belongs.

**`AGENTS.md`** (or `CLAUDE.md`, whichever the project uses; create `AGENTS.md`
if neither exists). Every agent reads it. Make sure it says:

- how to set up a fresh checkout (install dependencies, env files to copy);
- how to start the dev server on a given port, if the project has one;
- the validation commands, matching `factory/checks.sh`.

Then add a short section:

```markdown
## Software factory

`/factory run` builds every open GitHub issue labeled `factory` through
intake → spec → build → gate → review → approve, one PR per issue. State is in
`factory/jobs/` (gitignored); `factory/bin/job` is its only writer. Checks:
`factory/checks.sh`. It runs from Claude Code (`/factory run`) and from Codex
("factory run"), on any number of machines: the branch `factory/<issue>` on
origin marks an issue as taken. Dashboard: `cd factory && python3 -m http.server`, then
open http://localhost:8000/dashboard.html.

Each job works in its own git worktree, a full checkout of the repo at
`.worktrees/<job-id>` (gitignored). A tool run from the repo root that doesn't
read `.gitignore` sees those copies too; exclude `.worktrees/` in its config.
```

**`.gitignore`.** Append these two lines:

```gitignore
/factory/jobs/
/.worktrees/
```

`factory/jobs/` is runtime state (job metadata, specs, reviews, check logs)
local to the machine running the factory. Each job's worktree is a full
checkout in `.worktrees/<job-id>`. Neither belongs in the repo. Everything you
copied in step 1 does: the skill in `.claude/skills/factory/`, the agents in
`.claude/agents/` and the rest of `factory/` are part of the project and get
committed, so ignore only these two paths, never `.claude/` or `factory/`.

**Labels.** Create them on GitHub:

```bash
gh label create factory --color 5319E7 --description "Build this with the software factory"
gh label create factory:needs-info --color FBCA04 --description "The factory asked the author a question"
gh label create factory:needs-human --color D93F0B --description "The factory needs a human decision on the PR"
gh label create factory:in-progress --color 0E8A16 --description "A machine is building this with the software factory"
```

## 3. Verify

1. In the project root, on the current branch, `bash factory/checks.sh` exits 0.
   If it fails there, the factory can never pass a job: fix the
   script (not the project) or tell the user what's broken.
2. `factory/bin/job queue` runs without an error.
3. Each file in `.claude/agents/` has only these frontmatter keys: `name`,
   `description`, `tools`, `model`, and `hooks` on the builder. Claude Code
   ignores unknown keys without a warning, so a typo silently changes behaviour.
4. `python3 -m json.tool factory/config.json` succeeds.
5. `FACTORY_DRY_RUN=1 factory/bin/agent intake test` prints a `codex exec`
   command.
6. `git check-ignore factory/jobs/x .worktrees/x` prints both paths, and
   `git status --porcelain --untracked-files=all` lists every file from step 1
   (the skills, the agents and `factory/`) as committable.

## 4. Hand over

Stay on the branch the user is on: don't create or check out another branch.
Commit the install there with a one-line message and show the user the diff.
Ask before pushing: the factory branches every job from `origin/<base_branch>`,
so the install must be on that branch there before the first run.

Then tell the user, in a few lines:

- `/factory update` moves the factory to a newer release and keeps their
  changes; it commits nothing.
- Label one or two small issues `factory`, then run `/factory run` in Claude
  Code from the project root.
- Every job ends as a PR. The approver merges what it approves; the rest wait
  labeled `factory:needs-human`. Approve one by merging it on GitHub, or tell
  the factory what to change with `/factory <anything>`.
- Intake runs on Fable, once per issue. Depending on their plan, Fable can
  bill to usage credits rather than the plan's included usage.
- To start carefully, set `concurrency` to 1 in `factory/config.json` and read
  every PR until they trust it.
