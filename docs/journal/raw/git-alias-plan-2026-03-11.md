# 2026-03-11 git alias cleanup plan

## User request

- Ori first asked for a plan to create two Git aliases:
  - delete all local branches except `main`
  - delete all local worktrees
- Ori then decided these should be one command named `tidy` because worktree cleanup is a direct prerequisite for branch cleanup.

## Repo facts

- Main worktree is `/Users/ori/repos/x-dm-moderator` on branch `main`.
- Additional linked worktrees currently exist under `.worktrees/`.
- Several local branches are checked out in linked worktrees.
- Git will not delete a branch that is currently checked out by any worktree.

## Planning implication

- Safe behavior for `git tidy` is:
  1. remove linked worktrees first
  2. prune stale worktree metadata
  3. switch the main worktree to `main`
  4. delete local branches except `main`

## Ori decisions

- The cleanup should be a global Git alias, not repo-local.
- Protected branches should include both `main` and `develop`.
- Branch eligibility should be based on branches merged into `origin/main`, accepting the hardcoded convention and its dependency on remote-tracking freshness.

## Installed alias

- Global Git alias `tidy` was written to the user Git config.
- Alias behavior:
  - `git tidy` skips branch deletion when non-force worktree removal fails and does not mark the overall run failed for that case.
  - `git tidy --force` marks the run failed if forced worktree removal fails.
  - Branch deletion uses `git branch -D` after the explicit merged-into-`origin/main` filter and marks the run failed on deletion failure.
- Verification:
  - `git config --global --get alias.tidy` returned the stored alias body.
  - `git tidy --bogus` returned exit code `2` and printed `usage: git tidy [--force]`, confirming Git invokes the alias.
