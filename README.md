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

### Local path setup on macOS/Linux

The default paths target the Windows install layout. For local work on macOS/Linux, point the app at local writable directories first:

```bash
export DMGUARD_APP_ROOT="$PWD/.dmguard/app"
export DMGUARD_DATA_ROOT="$PWD/.dmguard/data"
mkdir -p "$DMGUARD_APP_ROOT" "$DMGUARD_DATA_ROOT"
```

On Windows, skip this section and use the default paths under `C:\Program Files\XDMModerator\` and `C:\ProgramData\XDMModerator\`.

### Local setup

The CLI (`uv run dmguard`) handles setup and diagnostics; `python -m dmguard` starts the server.

Fill in the values below, then run:

```bash
export DMGUARD_PUBLIC_HOSTNAME="dmguard.duckdns.org"
export DMGUARD_ACME_EMAIL="ops@example.com"
export DMGUARD_DUCKDNS_TOKEN="replace-me"
export DMGUARD_X_ACCESS_TOKEN="replace-me"
export DMGUARD_X_CONSUMER_SECRET="replace-me"
export DMGUARD_HF_TOKEN="replace-me"

uv run dmguard setup --verbose \
  --public-hostname "$DMGUARD_PUBLIC_HOSTNAME" \
  --acme-email "$DMGUARD_ACME_EMAIL" \
  --duckdns-token "$DMGUARD_DUCKDNS_TOKEN" \
  --x-access-token "$DMGUARD_X_ACCESS_TOKEN" \
  --x-consumer-secret "$DMGUARD_X_CONSUMER_SECRET" \
  --hf-token "$DMGUARD_HF_TOKEN"
```

This writes the local runtime files under the resolved data root:

- `config.yaml`
- `secrets.bin`
- `setup_state.json`
- `setup.log`

### Add the missing `x_user_id` secret

`dmguard setup` does not currently prompt for `x_user_id`, but the runtime X client and `readycheck` expect it to exist in `secrets.bin`.

Set your X user ID, then patch the generated secrets file:

```bash
export DMGUARD_X_USER_ID="replace-me"

uv run python - <<'PY'
import json
import os
from dmguard.paths import SECRETS_PATH

payload = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
payload["x_user_id"] = os.environ["DMGUARD_X_USER_ID"]
SECRETS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"updated {SECRETS_PATH}")
PY
```

### Inspect setup state

```bash
uv run dmguard status
uv run dmguard status --full
```

### Warm up the local classifier path

`dmguard setup` writes `classifier_backend: fake` into `config.yaml` by default. Set
`classifier_backend: llavaguard` to run the real CUDA-backed model path instead of the
fake classifier.

The real backend uses `AIML-TUDA/LlavaGuard-v1.2-0.5B-OV-hf`, requires CUDA, and reads
`hf_token` from `secrets.bin`. When `classifier_backend` is `llavaguard`, the same
`warmup` command exercises the real model and fails clearly if CUDA or the Hugging Face
token is unavailable.

```bash
uv run dmguard warmup
```

### Run the app locally

Start the server in one shell:

```bash
uv run python -m dmguard
```

Smoke-test the local endpoints from another shell:

```bash
curl -s http://127.0.0.1:8080/version | python -m json.tool
curl -s http://127.0.0.1:8080/health | python -m json.tool
```

### Common CLI tasks

Run a fake classifier self-test:

```bash
uv run dmguard selftest --image ./path/to/image.jpg --force-safe
uv run dmguard selftest --video ./path/to/clip.mp4 --force-unsafe
```

Run a real classifier self-test using the configured backend:

```bash
uv run dmguard selftest --image ./path/to/image.jpg
uv run dmguard selftest --video ./path/to/clip.mp4
```

Manage local sender state:

```bash
uv run dmguard allowlist add --user-id sender-1 --source-event-id event-1
uv run dmguard allowlist remove --user-id sender-1
uv run dmguard blockstate remove --user-id sender-1
```

Reset generated local setup files:

```bash
uv run dmguard reset --force
```

Run the current readiness check:

```bash
uv run dmguard readycheck
```

Note: `readycheck` currently expects the `app_service` setup stage to be marked done. That stage is not created by the current `setup` flow, so `status` and `status --full` are the more useful local diagnostics today.

### Running tests

```bash
uv run pytest
```

### Running the linter

```bash
uv run ruff check .
```
