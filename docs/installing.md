# Installing X DM Moderator

This guide walks through installing and running X DM Moderator on a Windows machine with an NVIDIA GPU. Every command is copy-paste ready.

## Hardware Requirements

- **NVIDIA GPU** with compute capability 5.0 or higher (Maxwell and newer)
- **VRAM**: the LlavaGuard v1.2 0.5B model requires approximately 1-2 GB of VRAM
- **Disk**: ~2 GB for Python, dependencies, and model weights
- **Network**: a public IP address with port 443 forwarded to the host

## Prerequisites

### NVIDIA Driver and CUDA

The classifier runs on CUDA. Confirm your driver is installed:

```powershell
nvidia-smi
```

You should see your GPU name, driver version, and CUDA version. If the command is not found, download and install the latest driver from https://www.nvidia.com/Download/index.aspx.

### Python 3.12 and uv

Install `uv` (the package manager):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then install Python 3.12.12 through uv:

```powershell
uv python install 3.12.12
```

### ffmpeg

```powershell
winget install ffmpeg
```

Verify it's on PATH:

```powershell
ffmpeg -version
```

### Network

- A **public IP address** with **port 443** forwarded to this machine
- A **DuckDNS account** with a subdomain pointing to your public IP (https://www.duckdns.org)
- Your router/firewall must forward inbound TCP 443 to this host

### Traefik and Servy

The setup expects these paths to exist before running:

- Traefik templates under `C:\Program Files\XDMModerator\traefik\templates\`
- `servy-cli.exe` at `C:\Program Files\Servy\servy-cli.exe`

## Install Dependencies

Clone the repository and install all dependencies:

```powershell
git clone https://github.com/cgm-16/x-dm-moderator.git
cd x-dm-moderator
uv sync --locked --all-groups
```

## GPU Validation

Confirm CUDA is available to PyTorch:

```powershell
uv run python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
```

Expected output includes `CUDA available: True` and your GPU name. If you see `False`, see the [Troubleshooting](#troubleshooting) section.

## Setup

Gather these values before running setup:

| Value | Where to get it |
|---|---|
| DuckDNS hostname | Your DuckDNS subdomain (e.g. `mybot.duckdns.org`) |
| ACME email | Email for Let's Encrypt certificate notifications |
| DuckDNS token | From your DuckDNS account page |
| X client ID | From the X Developer Portal (your app's OAuth 2.0 Client ID) |
| X consumer secret | From the X Developer Portal (your app's Consumer Secret / API Secret) |
| HF token | From https://huggingface.co/settings/tokens (for model download) |

Run the setup command:

```powershell
uv run dmguard setup --verbose `
  --public-hostname "mybot.duckdns.org" `
  --acme-email "ops@example.com" `
  --duckdns-token "your-duckdns-token" `
  --x-client-id "your-x-client-id" `
  --x-consumer-secret "your-x-consumer-secret" `
  --hf-token "your-hf-token"
```

During the X auth stage, a **browser window opens** for OAuth PKCE authorization. Sign in to X and authorize the app. The access token, refresh token, and user ID are obtained automatically — no manual token entry required.

Setup writes these files under `C:\ProgramData\XDMModerator\`:

- `config.yaml` — non-secret runtime configuration
- `secrets.bin` — encrypted secrets (tokens, keys)
- `setup_state.json` — setup progress metadata
- `setup.log` — append-only setup log (secrets redacted)

On Windows, setup proceeds through: local config, X auth (OAuth PKCE), DuckDNS update, Traefik artifact generation, TLS validation, public reachability check, Servy service install/start, classifier warmup, and X webhook registration.

## Verify Setup

Check the setup state:

```powershell
uv run dmguard status
```

Run the full check including remote connectivity:

```powershell
uv run dmguard status --full
```

Run the readiness check (verifies DB, secrets, services, and artifacts):

```powershell
uv run dmguard readycheck
```

All checks should show `PASS`. If any show `FAIL`, check the setup log at `C:\ProgramData\XDMModerator\setup.log`.

## Classifier Configuration

Setup writes `classifier_backend: fake` into `config.yaml` by default. This uses a deterministic fake classifier for testing.

To use the real CUDA-backed model:

1. Edit `C:\ProgramData\XDMModerator\config.yaml` and set `classifier_backend: llavaguard`
2. Run warmup to download and validate the model:

```powershell
uv run dmguard warmup
```

The real backend uses `AIML-TUDA/LlavaGuard-v1.2-0.5B-OV-hf`, requires CUDA, and reads
`hf_token` from `secrets.bin`. Warmup fails clearly if CUDA or the Hugging Face token is
unavailable.

## Running the App

Start the server:

```powershell
uv run python -m dmguard
```

Smoke-test the local endpoints from another terminal:

```powershell
curl -s http://127.0.0.1:8080/version | python -m json.tool
curl -s http://127.0.0.1:8080/health | python -m json.tool
```

On a production deployment, Traefik and dmguard run as Servy-managed Windows services and start automatically on boot.

## Common CLI Tasks

Run a classifier self-test (fake mode):

```powershell
uv run dmguard selftest --image .\path\to\image.jpg --force-safe
uv run dmguard selftest --video .\path\to\clip.mp4 --force-unsafe
```

Run a real classifier self-test (uses the configured backend):

```powershell
uv run dmguard selftest --image .\path\to\image.jpg
uv run dmguard selftest --video .\path\to\clip.mp4
```

Manage local sender state:

```powershell
uv run dmguard allowlist add --user-id sender-1 --source-event-id event-1
uv run dmguard allowlist remove --user-id sender-1
uv run dmguard blockstate remove --user-id sender-1
```

Reset generated local setup files:

```powershell
uv run dmguard reset --force
```

Run the readiness check:

```powershell
uv run dmguard readycheck
```

## Troubleshooting

### CUDA not found / `torch.cuda.is_available()` returns False

- Verify your NVIDIA driver is installed: `nvidia-smi` should show your GPU
- Ensure you installed the CUDA-enabled PyTorch build (the project's `pyproject.toml` handles this via uv)
- Try reinstalling dependencies: `uv sync --locked --all-groups --reinstall`
- Check the CUDA version in `nvidia-smi` output matches what PyTorch expects

### CPU-only torch installed

If PyTorch was installed without CUDA support:

```powershell
uv sync --locked --all-groups --reinstall
```

This forces a fresh install using the project's configured PyTorch index.

### Port 443 not reachable

- Confirm port forwarding is configured on your router (TCP 443 → this machine's local IP)
- Check Windows Firewall: Traefik needs an inbound rule for port 443
- Verify with an external port checker that 443 is open on your public IP

### DuckDNS not resolving

- Log in to https://www.duckdns.org and confirm your subdomain points to your public IP
- Wait a few minutes for DNS propagation
- Test: `nslookup mybot.duckdns.org`

### OAuth PKCE browser flow fails

- Ensure you can reach the X Developer Portal and your app's callback URL is configured
- The browser must be able to open on the same machine running setup
- If the browser does not open automatically, check the terminal for the authorization URL and open it manually

### Warmup fails

- If using `llavaguard` backend: confirm `torch.cuda.is_available()` returns `True`
- Confirm your Hugging Face token has access to the model
- Check `C:\ProgramData\XDMModerator\setup.log` for details

### TLS certificate not issued

- TLS-ALPN-01 requires port 443 to be publicly reachable by Let's Encrypt
- Confirm DuckDNS hostname resolves to your public IP
- Confirm Traefik is running and listening on 443
- Check Traefik logs for ACME errors
