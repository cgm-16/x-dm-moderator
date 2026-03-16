# X DM Moderator

Local safety filter for X (Twitter) direct messages. Receives DM webhooks, classifies attached media for violence/gore using LlavaGuard, and auto-blocks unsafe senders. Designed for a single Windows host with an NVIDIA GPU.

## Quick Start

See [docs/installing.md](docs/installing.md) for the full Windows installation guide with CUDA prerequisites and troubleshooting.

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

On Windows, the operational ingress flow expects:

- Traefik templates under `C:\Program Files\XDMModerator\traefik\templates\`
- `servy-cli.exe` installed at `C:\Program Files\Servy\servy-cli.exe`
- public `443` reachability for the DuckDNS hostname

Fill in the values below, then run:

```bash
export DMGUARD_PUBLIC_HOSTNAME="dmguard.duckdns.org"
export DMGUARD_ACME_EMAIL="ops@example.com"
export DMGUARD_DUCKDNS_TOKEN="replace-me"
export DMGUARD_X_CLIENT_ID="replace-me"
export DMGUARD_X_CONSUMER_SECRET="replace-me"
export DMGUARD_HF_TOKEN="replace-me"

uv run dmguard setup --verbose \
  --public-hostname "$DMGUARD_PUBLIC_HOSTNAME" \
  --acme-email "$DMGUARD_ACME_EMAIL" \
  --duckdns-token "$DMGUARD_DUCKDNS_TOKEN" \
  --x-client-id "$DMGUARD_X_CLIENT_ID" \
  --x-consumer-secret "$DMGUARD_X_CONSUMER_SECRET" \
  --hf-token "$DMGUARD_HF_TOKEN"
```

Setup uses OAuth PKCE to obtain the X access token, refresh token, and user ID automatically — no manual token entry required. A browser window opens during the X auth stage for authorization.

This writes the local runtime files under the resolved data root:

- `config.yaml`
- `secrets.bin`
- `setup_state.json`
- `setup.log`

On Windows, `setup` continues through DuckDNS update, Traefik artifact generation, Servy service install/start, public HTTPS validation, classifier warmup, and X webhook registration. On macOS/Linux, those Windows-only ingress stages are recorded as skipped so local development setup can still prepare config and secrets without pretending the public edge is operational.

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

### Running tests

```bash
uv run pytest
```

### Running the linter

```bash
uv run ruff check .
```

## Documentation

- [Installation Guide](docs/installing.md) — full Windows setup with CUDA prerequisites
- [Specification](specs.md) — frozen v0.1 design reference
- [Whitepaper](docs/archive/whitepaper.md) — archived build blueprint
