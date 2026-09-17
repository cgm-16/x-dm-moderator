# PR 80 review notes
- Task: review PR 80 in x-dm-moderator and return only JSON findings.
- Need to inspect diff against main, confirm any regressions, and cite precise lines.
- Likely PR branch: origin/feat/issue-32-prune-command (latest unfused branch after reviewed PRs); reviewed prune diff and validated candidate bugs.
- Confirmed bug candidate: prune query only targets done/error, so skipped jobs (terminal per dmguard.job_machine) never age out.
- Confirmed bug candidate: delete helpers build one SQL placeholder per ID; pruning >32766 rows on current SQLite fails with too many SQL variables.
