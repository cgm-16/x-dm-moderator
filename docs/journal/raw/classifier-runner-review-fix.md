# Classifier runner review fix notes

- Worktree: `/Users/ori/repos/x-dm-moderator/.worktrees/feat-classifier-runner-issue-26`
- Branch: `feat/classifier-runner-issue-26`
- Goal: fix PR review about `run_classifier()` not persisting stderr to `classifier.log` when called before `setup_logging()`
- Observed runtime path: `dmguard warmup` -> `handle_warmup()` -> `run_setup_warmup()` -> `run_classifier()` with no logging bootstrap
- Likely fix location: `dmguard/classifier_runner.py`, not CLI wiring
- Existing branch state before edits: local branch behind `origin/feat/classifier-runner-issue-26` by 1 commit
- Active review-fix branch for this task: `/Users/ori/repos/x-dm-moderator/.worktrees/feat-classifier-runner-issue-26` on `feat/classifier-runner-issue-26`
- New review finding: `subprocess.Popen(..., text=True)` lets `process.communicate()` raise `UnicodeDecodeError` on non-UTF-8 stdout/stderr before `ClassifierResponse.model_validate_json()` runs
- Minimal fix direction: capture stdout/stderr as bytes, decode explicitly in `classifier_runner.py`, and convert decode failures into `ClassifierError`
- Unrelated observation during local pytest on macOS: repo can materialize an untracked `C:/` directory tree when Windows-style default paths are touched; do not fold cleanup into this review-fix commit
