param(
    [Parameter(Position = 0)]
    [ValidateSet("verify", "cleanup", "status", "smoke", "report", "help")]
    [string]$Action = "help",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardArgs
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$verifyScript = Join-Path $scriptDir "prod_verify.ps1"
$cleanupScript = Join-Path $scriptDir "cleanup_reports.ps1"
$statusScript = Join-Path $scriptDir "status.ps1"
$smokeScript = Join-Path $scriptDir "smoke_scripts.ps1"
$reportScript = Join-Path $scriptDir "new_prod_report.ps1"

function Show-Help {
    @"
Usage:
    pwsh -File scripts/ops.ps1 <verify|cleanup|status|smoke|report|help> [args]

Examples:
    pwsh -File scripts/ops.ps1 status
    pwsh -File scripts/ops.ps1 smoke
    pwsh -File scripts/ops.ps1 report -Commit release-2026-03-10 -Operator devops
  pwsh -File scripts/ops.ps1 verify -DryRun -NoBackup -Commit preview -Operator oncall
  pwsh -File scripts/ops.ps1 cleanup -KeepArtifacts 30 -DryRun

Cheat sheet:
    scripts/ops_help.txt
"@ | Write-Host
}

switch ($Action) {
    "verify" {
        if (-not (Test-Path $verifyScript)) {
            throw "File not found: $verifyScript"
        }
        & pwsh -File $verifyScript @ForwardArgs
        exit $LASTEXITCODE
    }
    "cleanup" {
        if (-not (Test-Path $cleanupScript)) {
            throw "File not found: $cleanupScript"
        }
        & pwsh -File $cleanupScript @ForwardArgs
        exit $LASTEXITCODE
    }
    "status" {
        if (-not (Test-Path $statusScript)) {
            throw "File not found: $statusScript"
        }
        & pwsh -File $statusScript
        exit $LASTEXITCODE
    }
    "smoke" {
        if (-not (Test-Path $smokeScript)) {
            throw "File not found: $smokeScript"
        }
        & pwsh -File $smokeScript
        exit $LASTEXITCODE
    }
    "report" {
        if (-not (Test-Path $reportScript)) {
            throw "File not found: $reportScript"
        }
        & pwsh -File $reportScript @ForwardArgs
        exit $LASTEXITCODE
    }
    default {
        Show-Help
        exit 0
    }
}
