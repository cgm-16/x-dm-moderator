#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Removes XDMModerator from a Windows host.
.DESCRIPTION
    Stops and removes Servy services, deletes the firewall rule, and removes
    the installation and data directories. Run as Administrator.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProgramFilesDir  = 'C:\Program Files\XDMModerator'
$ProgramDataDir   = 'C:\ProgramData\XDMModerator'
$FirewallRuleName = 'XDMModerator-HTTPS-In'
$ServiceNames     = @('XDMModerator', 'XDMModeratorTraefik')

$servyCli = 'C:\Program Files\Servy\servy-cli.exe'

# --- Services -----------------------------------------------------------------

Write-Host '--- Stopping and removing services ---'

foreach ($svc in $ServiceNames) {
    if (Test-Path $servyCli) {
        try {
            & $servyCli stop --quiet --name $svc
            Write-Host "  Stopped $svc"
        } catch {
            Write-Host "  $svc was not running"
        }
        try {
            & $servyCli uninstall --quiet --name $svc
            Write-Host "  Uninstalled $svc"
        } catch {
            Write-Host "  $svc was not installed"
        }
    } else {
        Write-Host "  Servy CLI not found, skipping service cleanup for $svc"
    }
}

# --- Firewall -----------------------------------------------------------------

Write-Host '--- Removing firewall rule ---'

$existingRule = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
if ($existingRule) {
    Remove-NetFirewallRule -DisplayName $FirewallRuleName
    Write-Host "  Removed '$FirewallRuleName'"
} else {
    Write-Host "  Rule '$FirewallRuleName' not found, skipping"
}

# --- Directories --------------------------------------------------------------

Write-Host '--- Removing directories ---'

if (Test-Path $ProgramFilesDir) {
    Remove-Item -Recurse -Force $ProgramFilesDir
    Write-Host "  Removed $ProgramFilesDir"
} else {
    Write-Host "  $ProgramFilesDir not found, skipping"
}

if (Test-Path $ProgramDataDir) {
    Remove-Item -Recurse -Force $ProgramDataDir
    Write-Host "  Removed $ProgramDataDir"
} else {
    Write-Host "  $ProgramDataDir not found, skipping"
}

# --- Done ---------------------------------------------------------------------

Write-Host ''
Write-Host '=== Uninstall complete ==='
