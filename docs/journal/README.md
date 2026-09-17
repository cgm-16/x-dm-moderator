# Project journal

What the code does not say. Distilled from 27 agent session notes written during the
v0.1 build (2026-03-10 → 2026-03-24), now preserved under `raw/` rather than left in
gitignored scratch files on one machine.

Read `../audit-2026-09.md` first for why the project is mothballed. This file is the
engineering memory behind it.

## Still live at mothball — read this first

**One known bug was never fixed and is in the shipped code.** It was found in review,
a fix direction was agreed, and the fix was never applied. The passing test suite does
not contradict this: nothing covers it.

- **`run_classifier` can raise `UnicodeDecodeError` out of the public API.**
  `dmguard/classifier_runner.py:48` still passes `text=True` to `subprocess.Popen`, so
  `communicate()` at `:52` decodes classifier output as UTF-8 and throws on anything
  else. The `except Exception` at `:70` wraps only
  `ClassifierResponse.model_validate_json()`, so the decode error is never converted
  into `ClassifierError` and propagates to the caller uncaught.
  `grep -c "UnicodeDecode\|errors=\|bytes" tests/test_classifier_runner.py` → **0**.
  Tracked as **#140**, with a reproduction. Agreed fix direction, per
  `raw/classifier-runner-review-fix.md`: capture stdout and stderr as bytes, decode
  explicitly, convert decode failures into `ClassifierError`.
  Note that the same bug shape *was* fixed at the webhook boundary
  (`dmguard/app.py:572` catches `UnicodeDecodeError` and returns 400) — the classifier
  boundary was missed.

## Bugs that were real, and what caused them

These are fixed in the current tree; verified at mothball, not assumed from the notes.

Each of these shipped or nearly shipped. They are recorded because the same shapes will
recur in any rebuild.

- **A guard that logged but did not skip.** Commit `e0bb90c` ("added guard pattern to
  media_dispatch") logged unsupported media types and then appended them anyway,
  silently regressing the behaviour merged in #22. Caught two issues later during #23.
  Logging a rejection is not rejecting it.
- **Fail-open leaked into the status mapping.** `_dispatch_moderation` mapped a
  moderation `outcome="error"` to `JobStatus.done`, so unsafe media whose block attempt
  had failed was marked complete. Found in PR #106 review. This is the exact failure
  mode the audit flags as unacceptable for a hosted service.
- **Same shape at the webhook boundary.** `json.loads(raw_body)` on a signed request with
  invalid UTF-8 returned 500 instead of 400. Untrusted bytes need explicit decoding at
  every trust boundary, not implicit.
- **Schema was never bootstrapped on a fresh DB.** `POST /webhooks/x` raised
  `sqlite3.OperationalError: no such table: webhook_events`. Found in PR #78.
- **The pruner missed a terminal state.** It targeted `done` and `error` only, but
  `skipped` is also terminal per `job_machine`, so allowlisted jobs never aged out.
- **Placeholder-per-ID delete.** The delete helpers built one SQL placeholder per row id,
  so pruning more than 32,766 rows fails on SQLite's variable limit. Batch it.
- **`XClient` leaked per job.** Instantiated inside `_dispatch_moderation` without being
  closed, while every other call site used `async with` / `aclose()`.

## Environment facts that cost time

- **macOS materializes a `C:/` directory tree inside the repo** when Windows-style default
  paths get touched during tests. This is the whole reason `paths.py` requires explicit
  non-Windows overrides (#137) rather than silently defaulting. If a rebuild drops the
  Windows target, that constraint can go with it — but do not remove it while the
  Windows defaults remain.
- **`git tidy`** exists as a global alias: remove linked worktrees, prune metadata,
  switch to `main`, then delete branches merged into `origin/main`. Order matters — git
  refuses to delete a branch checked out by any worktree.

## Decisions worth not relitigating

- **No backward-compatibility aliases.** Enforced throughout; renames were done outright
  (`insert_job_error` → `record_job_error`, and `get_block_failed` was left as debt in
  #103 rather than aliased). Anything that looks like a compat shim in a rebuild is a
  regression from this standard.
- **Fail-open was deliberate for v0.1**, not an oversight. The audit explains why it
  stops being defensible once the operator and the customer are different people.
- **The 180s classifier timeout is a module constant**, specifically so tests can
  monkeypatch it short. Keep production behaviour and testability separate that way.
- **`allowed_senders.source_event_id` is `NOT NULL`**, which is why `allowlist add`
  requires `--source-event-id`. The CLI ergonomics follow from the schema, not taste.
- **Process was issue → worktree branch → PR**, one issue per worktree. 43 issues across
  14 milestones, 127 commits.

## Known debt, never fixed

- **`todo.md` and `issues_todo.md` are long shared ledgers with no CI validation or
  generation path.** Frequent branch-local edits to the same checklist sections produced
  predictable merge conflicts and stale state drift — `issues_todo.md` was observed stale
  against merged work more than once. The identified fix was to make them generated views
  or append-only normalized data, not merely lint them. A rebuild should not reproduce
  hand-maintained parallel ledgers.
- The open issues are all labelled `mothballed` on GitHub. They are real findings, not
  live work. 19 carried over from the v0.1 build; #140 was filed at mothball for the live
  decode bug above, which nothing else tracked.

## `raw/`

The 27 original session notes, renamed from `.codex-memory-<slug>.md` to `<slug>.md` so
git will track them (`.gitignore:13` still ignores the original pattern). Unedited.
Useful for archaeology on a specific issue or PR; the synthesis above is what matters.
