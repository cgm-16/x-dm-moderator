## 2026-03-11

- Question: whether Codex can combine plan mode with yolo/full-auto so Ori approves a full plan once and then no further input is required.
- Local CLI findings:
  - `codex --full-auto` is an alias for `--ask-for-approval on-request --sandbox workspace-write`.
  - `--full-auto` is not zero-prompt execution; the model may still ask.
  - `--ask-for-approval never` is the zero-approval mode while keeping sandbox behavior.
  - `--dangerously-bypass-approvals-and-sandbox` disables both approvals and sandboxing.
  - `codex resume` and `codex exec resume` accept approval/sandbox flags, so a plan-first then resume-autonomous workflow is possible as two steps.
- No local CLI flag found for a single built-in "approve plan once, auto-run rest" hybrid mode.

- `gh` behavior in the current sandbox:
  - `gh issue list --limit 1` failed with `error connecting to api.github.com`, which points to sandboxed outbound network being unavailable.
  - `gh auth status` was able to read local auth state and reported the default token is invalid, so local config access is not the primary blocker for `gh issue`/`gh pr` API calls.
  - Practical implication: sandbox blocks the network path first; once that is lifted, GitHub auth may still need fixing for authenticated operations.

- Elevated permission scope in this environment:
  - An elevated request runs the approved command outside the Codex sandbox.
  - That is broad for the approved command: it can use normal network access, read/write outside the workspace, and perform other actions otherwise blocked by the sandbox, subject to the OS permissions of the current user.
  - It is not a blanket grant for the whole session by default.
  - Scope is per command/tool call, with command segments evaluated independently when shell control operators split the command (`|`, `&&`, `||`, `;`, subshells).
  - A `prefix_rule` can persist approval for future commands matching that prefix, which broadens the effect beyond a single call.
  - Elevation does not imply root/admin; it runs with the permissions of the Codex process's user account.

- Skill update in progress for `.agents/skills/gh-work-oldest-open-issue`:
  - The repo now has `issues_todo.md`, which defines dependency relationships between GitHub issues.
  - The skill and Claude mirror should read `issues_todo.md` during context building and choose the oldest open issue by `createdAt` only among dependency-ready issues.
  - `agents/openai.yaml` should be kept consistent with that dependency-aware behavior.
  - Follow-up: the skill must explicitly require keeping both `todo.md` and `issues_todo.md` honest so issue dependency state is not left stale after implementation work.

- Oldest dependency-ready open issue selection for execution:
  - `#3` is being worked in parallel in `.worktrees/feat-logging-bootstrap-issue-3`, so it should be treated as in progress and avoided for new work.
  - `gh issue list --state open --limit 100 --json number,title,createdAt,url` required elevated execution because sandboxed outbound network is blocked.
  - True oldest dependency-ready open issue is `#5 DB connection management` at `2026-03-11T00:52:17Z`.
  - `#4` is older overall but blocked by dependency `#3`.
  - Other dependency-ready candidates (`#19`, `#25`, `#34`, `#36`) are newer than `#5`.

- Execution assumptions for issue `#5`:
  - Implement only `dmguard/db.py` plus focused tests and backlog updates.
  - SQLite busy timeout chosen for this repo is `5000` ms.
  - `todo.md` currently has no checkbox that maps directly to issue `#5`, so only `issues_todo.md` should change unless implementation evidence says otherwise.

- `todo.md` and `issues_todo.md` are long shared ledgers with no current CI validation or generation path.
  - Practical risk: frequent branch-local edits to the same checklist sections will create predictable merge conflicts and stale state drift.
  - CI strategy likely needs to reduce them to either generated views or append-only / normalized data, not just lint formatting.
