param(
    [int]$KeepArtifacts = 30,
    [switch]$DryRun,
    [switch]$Help
)

if ($Help) {
    @"
Usage:
  pwsh -File scripts/cleanup_reports.ps1 [options]

Options:
  -KeepArtifacts <n>   Number of latest logs/reports to keep (range: 1..500, default: 30)
  -DryRun              Show what would be deleted without removing files
  -Help                Show this help

Examples:
  pwsh -File scripts/cleanup_reports.ps1 -KeepArtifacts 30
  pwsh -File scripts/cleanup_reports.ps1 -KeepArtifacts 50 -DryRun
"@ | Write-Host
    exit 0
}

if ($KeepArtifacts -lt 1 -or $KeepArtifacts -gt 500) {
    throw "KeepArtifacts must be in range 1..500"
}

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportsDir = Join-Path $repoRoot "docs\reports"

if (-not (Test-Path $reportsDir)) {
    Write-Host "Reports directory not found: $reportsDir"
    exit 0
}

function Invoke-ReportCleanup {
    param(
        [string]$Directory,
        [string]$Pattern,
        [int]$KeepCount,
        [switch]$WhatIf
    )

    $items = Get-ChildItem -Path $Directory -Filter $Pattern -File |
        Sort-Object LastWriteTime -Descending

    if ($items.Count -le $KeepCount) {
        return [PSCustomObject]@{
            Pattern = $Pattern
            Deleted = 0
            Kept = $items.Count
        }
    }

    $toRemove = $items | Select-Object -Skip $KeepCount
    if ($WhatIf) {
        foreach ($item in $toRemove) {
            Write-Host "[DryRun] Would delete: $($item.FullName)"
        }
    }
    else {
        foreach ($item in $toRemove) {
            Remove-Item -Path $item.FullName -Force -ErrorAction SilentlyContinue
        }
    }

    return [PSCustomObject]@{
        Pattern = $Pattern
        Deleted = @($toRemove).Count
        Kept = $KeepCount
    }
}

$mdResult = Invoke-ReportCleanup -Directory $reportsDir -Pattern "prod_verify_*.md" -KeepCount $KeepArtifacts -WhatIf:$DryRun
$logResult = Invoke-ReportCleanup -Directory $reportsDir -Pattern "prod_verify_*.log" -KeepCount $KeepArtifacts -WhatIf:$DryRun

Write-Host "Cleanup completed. keep=$KeepArtifacts dryRun=$DryRun"
Write-Host "Reports (*.md): deleted=$($mdResult.Deleted), kept~=$($mdResult.Kept)"
Write-Host "Logs (*.log): deleted=$($logResult.Deleted), kept~=$($logResult.Kept)"
