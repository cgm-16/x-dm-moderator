# 2026-03-11 oldest-open-issue run

## Current repo state

- Started from `/Users/ori/repos/x-dm-moderator` on branch `main`.
- `git status --short` showed `?? .worktrees/` from the repo root.
- Existing worktrees:
  - `feat/config-loader-issue-2`
  - `feat/issue-5-db-connection-management`
  - `feat/logging-bootstrap-issue-3`
  - `feat/secrets-loader-issue-19`

## Backlog state

- `issues_todo.md` says `#5 DB connection management` is dependency-ready because it depends only on `#1`, which is done.
- `issues_todo.md` says `#4` is older in Milestone 1 but blocked by `#3`.

## Worktree checks

- `.worktrees/feat-issue-5-db-connection-management` is clean.
- That worktree is on branch `feat/issue-5-db-connection-management`.
- Its latest commit is `cc6ca58 feat(db): add sqlite connection factory`.
- `.worktrees/feat-logging-bootstrap-issue-3` is clean.
- `.worktrees/feat-secrets-loader-issue-19` is clean.

## Open questions

- Need GitHub issue data to confirm the oldest dependency-ready open issue today.
- Need to determine whether issue `#5` already has an open PR or otherwise counts as active work before duplicating work.

## Issue 26 execution

- Issue `#26` scope is `dmguard/classifier_runner.py` for subprocess execution and timeout handling.
- Dedicated worktree: `.worktrees/feat-classifier-runner-issue-26`
- Dedicated branch: `feat/classifier-runner-issue-26`
- Repository has `ClassifierResponse` but no `ClassifierResult`; implementation should return `ClassifierResponse` and avoid adding a compatibility alias without explicit approval.
- Testability requirement: keep the production timeout at 180 seconds but expose it as an internal module constant so tests can monkeypatch it to a short value.

## Issue 9 execution

- GitHub issue `#9` title: `Dequeue + claim transaction`.
- Live issue scope requires a new `dmguard/scheduler.py` module with:
  - `dequeue_next_job(conn) -> job_row | None`
  - `claim_job(conn, job_id) -> bool`
  - `advance_stage(conn, job_id, new_stage)`
  - `complete_job(conn, job_id, status)`
- `claim_job` must atomically set `status=processing`, increment `attempt`, and set `processing_started_at` and `updated_at`.
- `dequeue_next_job` must select oldest runnable queued job ordered by `next_run_at ASC, job_id ASC`.
- Planned branch: `feat/scheduler-issue-9-claim-transaction`
- Planned worktree: `.worktrees/feat-scheduler-issue-9-claim-transaction`
