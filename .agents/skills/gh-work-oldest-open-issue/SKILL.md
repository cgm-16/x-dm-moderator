---
name: gh-work-oldest-open-issue
description: Work the oldest open GitHub issue in a repository from a fresh git worktree. Use when Ori wants Codex to choose the earliest-created open issue automatically, implement the issue on a feature branch based on main, and keep the repository's todo.md aligned with what was actually completed and verified.
---

# Work Oldest Open Issue

## Overview

Use this skill when no issue number is provided and backlog work should be taken in issue age order. Read the repository instructions first, select the oldest dependency-ready open issue by `createdAt`, create a new worktree from an updated `main`, execute the issue with the repository's debugging and testing rules, and update `todo.md` only for work that is truly done.

## Workflow

1. Build context first.
   - Read `AGENTS.md`.
   - Search for and read `.codex-memory-*.md`.
   - Read `todo.md`.
   - Read `issues_todo.md`.
   - Inspect `git status --short`, `git branch --show-current`, and `git worktree list`.
   - Publish an executable plan where every step includes action intent, exact command or action, and a done-check.

2. Select the issue.
   - If Ori already supplied an issue number or URL, use it instead of selecting one.
   - Otherwise list open issues and choose the earliest by `createdAt` that has all dependencies resolved.
   - Example command:

   ```bash
   gh issue list --state open --limit 100 --json number,title,createdAt,url
   ```

   - Open the selected issue and read the full body before changing code.
   - If a `gh` command fails in a sandboxed session, stop and ask Ori for permission before retrying.

3. Prepare a fresh worktree.
   - Sync `main` with fetch plus fast-forward-only. If sync fails, stop and ask Ori.
   - Example commands:

   ```bash
   git switch main
   git fetch origin main
   git pull --ff-only origin main
   branch="feat/issue-<number>-<topic>"
   worktree=".worktrees/${branch//\//-}"
   git worktree add "$worktree" -b "$branch" main
   cd "$worktree"
   ```

   - Use `type/scope-topic` branch naming and keep all issue work inside the new worktree.

4. Investigate before fixing.
   - Reproduce the problem or locate the missing behavior.
   - Read errors carefully.
   - Find similar working code in the repository.
   - State one root-cause hypothesis before editing code.
   - Write the smallest failing test first when the repository supports it.

5. Implement in small verified steps.
   - Make the smallest reasonable change.
   - Re-run targeted tests after each meaningful edit.
   - Match the surrounding style and leave unrelated files alone.
   - If the first hypothesis fails, stop and re-analyze instead of stacking fixes.

6. Keep `todo.md` honest.
   - Update only the checklist items that are actually complete in the current branch.
   - Mark acceptance criteria complete only when they were verified.
   - Leave future work unchecked.
   - If an issue covers only part of a section, use the repository's existing status markers conservatively.
   - `todo.md` must describe the real state of the branch, not the intended scope.

7. Close out cleanly.
   - Run the relevant tests and note what was and was not verified.
   - Review `git diff --stat` and `git status --short`.
   - Commit on the feature branch with a Conventional Commit message that follows repository language rules.
   - If repository policy requires a PR and authentication is available, open it after the branch is ready.

## Done Check

- The selected issue is the earliest dependency-ready open issue by `createdAt`.
- The work happens in a new worktree on a feature branch based on updated `main`.
- The implementation matches the issue scope and has test or verification evidence.
- `todo.md` matches what was actually completed and verified.
- The final report includes the issue reference, branch name, worktree path, tests run, and blockers.
