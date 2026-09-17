# PR 78 review notes
- Date: 2026-03-11
- Task: review PR 78 for correctness and actionable bugs.
- Need: inspect diff against main, changed files, and any impacted tests/behavior.
- Confirmed PR 78 maps to branch `feat/issue-17-webhook-post-enqueue` via git config `branch.*.github-pr-owner-number`.
- Reproduced fresh-db failure: POST /webhooks/x raises `sqlite3.OperationalError: no such table: webhook_events` because app never bootstraps schema.
- Reproduced signed invalid-UTF8 body failure: `json.loads(raw_body)` raises `UnicodeDecodeError`, so handler returns 500 instead of 400 invalid JSON.
