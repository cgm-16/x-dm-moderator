# X DM Moderator

Prototype X DM safety filter for local development and deployment experiments.

## Developer Guide

### Prerequisites

- Python `3.12.12`
- `uv`
- `ffmpeg` on `PATH`

### Install dependencies

```bash
uv sync --locked --all-groups
```

### Running the app locally

`python -m dmguard` loads `config.yaml` and `secrets.bin` from the resolved data root. Create those files first with `uv run dmguard setup` or by writing them manually, then start the app with:

```bash
uv run python -m dmguard
```

### Running tests

```bash
uv run pytest
```

### Running the linter

```bash
uv run ruff check .
```

### macOS path overrides

The default paths target the Windows install layout. On macOS, point the app at local writable directories before running setup, tests, or the app:

```bash
export DMGUARD_APP_ROOT="$PWD/.dmguard/app"
export DMGUARD_DATA_ROOT="$PWD/.dmguard/data"
mkdir -p "$DMGUARD_APP_ROOT" "$DMGUARD_DATA_ROOT"
```

With those overrides in place, the app reads and writes local files such as:

- `$DMGUARD_DATA_ROOT/config.yaml`
- `$DMGUARD_DATA_ROOT/secrets.bin`
- `$DMGUARD_DATA_ROOT/state.db`
- `$DMGUARD_DATA_ROOT/logs/`
- `$DMGUARD_DATA_ROOT/tmp/`

### Fake classifier for local testing

The app uses `dmguard.classifier_fake` by default, so local runs do not require the real model. To exercise the fake classifier directly:

```bash
uv run dmguard selftest --image ./path/to/image.jpg --force-safe
uv run dmguard selftest --video ./path/to/clip.mp4 --force-unsafe
```
