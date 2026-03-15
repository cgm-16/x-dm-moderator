#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Installs XDMModerator on a Windows host.
.DESCRIPTION
    Checks prerequisites, creates directory structure, installs Python
    dependencies, downloads Traefik, and configures the Windows Firewall.
    Run as Administrator.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProgramFilesDir = 'C:\Program Files\XDMModerator'
$ProgramDataDir  = 'C:\ProgramData\XDMModerator'
# Sole version pin for Traefik — update here when upgrading.
$TraefikVersion  = '3.3.6'
$TraefikUrl      = "https://github.com/traefik/traefik/releases/download/v${TraefikVersion}/traefik_v${TraefikVersion}_windows_amd64.zip"
$FirewallRuleName = 'XDMModerator-HTTPS-In'

# --- Prerequisites -----------------------------------------------------------

Write-Host '--- Checking prerequisites ---'

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error 'Python is not on PATH. Install Python 3.12+ and try again.'
}
$pyVersion = & python --version 2>&1
Write-Host "  Python: $pyVersion"

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Error 'uv is not on PATH. Install uv (https://docs.astral.sh/uv/) and try again.'
}
Write-Host "  uv: $(& uv --version 2>&1)"

$servy = Get-Command servy-cli -ErrorAction SilentlyContinue
if (-not $servy) {
    $servyPath = 'C:\Program Files\Servy\servy-cli.exe'
    if (-not (Test-Path $servyPath)) {
        Write-Error "Servy CLI not found on PATH or at $servyPath. Install Servy first."
    }
}
Write-Host '  Servy: found'

# --- Directory structure ------------------------------------------------------

Write-Host '--- Creating directories ---'

New-Item -ItemType Directory -Force -Path $ProgramFilesDir | Out-Null
New-Item -ItemType Directory -Force -Path $ProgramDataDir | Out-Null
New-Item -ItemType Directory -Force -Path "$ProgramDataDir\traefik" | Out-Null
New-Item -ItemType Directory -Force -Path "$ProgramDataDir\logs" | Out-Null
New-Item -ItemType Directory -Force -Path "$ProgramDataDir\tmp" | Out-Null

# --- Copy repo contents ------------------------------------------------------

Write-Host '--- Copying project files ---'

$RepoRoot = Split-Path -Parent $PSScriptRoot

$itemsToCopy = @(
    'dmguard',
    'pyproject.toml',
    'uv.lock'
)
foreach ($item in $itemsToCopy) {
    $src = Join-Path $RepoRoot $item
    $dst = Join-Path $ProgramFilesDir $item
    if (Test-Path $src -PathType Container) {
        Copy-Item -Recurse -Force $src $dst
    } else {
        Copy-Item -Force $src $dst
    }
}

# --- Python dependencies -----------------------------------------------------

Write-Host '--- Installing Python dependencies ---'

Push-Location $ProgramFilesDir
try {
    & uv sync --locked
} finally {
    Pop-Location
}

# --- Traefik binary -----------------------------------------------------------

$traefikExe = Join-Path (Join-Path $ProgramFilesDir 'traefik') 'traefik.exe'
if (Test-Path $traefikExe) {
    Write-Host "--- Traefik binary already exists at $traefikExe, skipping download ---"
} else {
    Write-Host "--- Downloading Traefik v${TraefikVersion} ---"

    $zipPath = Join-Path $env:TEMP 'traefik.zip'
    $extractDir = Join-Path $env:TEMP 'traefik-extract'
    Invoke-WebRequest -Uri $TraefikUrl -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
    New-Item -ItemType Directory -Force -Path (Split-Path $traefikExe) | Out-Null
    Copy-Item -Force (Join-Path $extractDir 'traefik.exe') $traefikExe
    Remove-Item -Recurse -Force $extractDir
    Remove-Item -Force $zipPath
}

Write-Host "  Traefik: $traefikExe"

# --- Firewall -----------------------------------------------------------------

Write-Host '--- Configuring firewall ---'

$existingRule = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
if ($existingRule) {
    Write-Host "  Firewall rule '$FirewallRuleName' already exists, skipping"
} else {
    New-NetFirewallRule `
        -DisplayName $FirewallRuleName `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 443 `
        -Action Allow `
        -Profile Any | Out-Null
    Write-Host "  Created firewall rule '$FirewallRuleName'"
}

# --- Done ---------------------------------------------------------------------

Write-Host ''
Write-Host '=== Installation complete ==='
Write-Host ''
Write-Host 'Next steps:'
Write-Host "  cd `"$ProgramFilesDir`""
Write-Host '  uv run dmguard setup --public-hostname <YOUR_HOST>.duckdns.org --acme-email <YOUR_EMAIL>'
