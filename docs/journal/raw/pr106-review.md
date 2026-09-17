# PR 106 review notes
- Task: review PR 106 for actionable bugs and output findings JSON only.
- Need to identify the local branch/commit range corresponding to PR 106 and inspect the diff against main.
- PR 106 appears to be origin/feat/pipeline-wiring-issue-41 (only remote branch ahead of main by one commit).
- Confirmed regression: _dispatch_moderation maps moderation outcome="error" to JobStatus.done, so unsafe media with failed block attempts are marked complete.
- Confirmed resource leak: _dispatch_moderation instantiates XClient per job without closing it; tests elsewhere use async with / aclose.
