param(
    [string]$Commit = "",
    [string]$Operator = "",
    [switch]$Help
)

if ($Help) {
    @"
Usage:
  pwsh -File scripts/new_prod_report.ps1 [-Commit <value>] [-Operator <value>]

Description:
  Creates a timestamped production execution report skeleton in docs/reports/.

Examples:
  pwsh -File scripts/new_prod_report.ps1 -Commit release-2026-03-10 -Operator devops
  pwsh -File scripts/new_prod_report.ps1
"@ | Write-Host
    exit 0
}

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportsDir = Join-Path $repoRoot "docs\reports"
if (-not (Test-Path $reportsDir)) {
    New-Item -ItemType Directory -Path $reportsDir | Out-Null
}

$effectiveCommit = $Commit
if (-not $effectiveCommit) {
    try {
        Push-Location $repoRoot
        $gitCommit = (& git rev-parse --short HEAD 2>$null)
        if ($LASTEXITCODE -eq 0 -and $gitCommit) {
            $effectiveCommit = ($gitCommit | Select-Object -First 1).Trim()
        }
    }
    catch {
    }
    finally {
        Pop-Location
    }
}
if (-not $effectiveCommit) {
    $effectiveCommit = "<not provided>"
}

$effectiveOperator = $Operator
if (-not $effectiveOperator) {
    if ($env:USERNAME) {
        $effectiveOperator = $env:USERNAME
    }
    elseif ($env:USER) {
        $effectiveOperator = $env:USER
    }
}
if (-not $effectiveOperator) {
    $effectiveOperator = "<not provided>"
}

$utcNow = [DateTime]::UtcNow
$ts = $utcNow.ToString("yyyyMMdd_HHmmss")
$filePath = Join-Path $reportsDir ("prod_execution_{0}.md" -f $ts)

$content = @"
# Production Execution Report

Дата/время (UTC): $($utcNow.ToString("yyyy-MM-dd HH:mm:ss"))
Release tag/commit: $effectiveCommit
Operator: $effectiveOperator

## 1) Preflight
- [ ] `DATABASE_URL` verified
- [ ] backup completed
- [ ] smoke scripts passed (`scripts\\ops.cmd smoke`)

## 2) DB Gate
- [ ] assert passed (`scripts\\ops.cmd verify -NoBackup -Commit $effectiveCommit -Operator $effectiveOperator`)
- [ ] smoke passed

## 3) Functional smoke
- [ ] `/mix` open/save/share/clone
- [ ] `/favorites` pagination
- [ ] `/playlist export <name>`
- [ ] `/radar` and releases toggle
- [ ] `/admin stats` cache hit rate + latency

## 4) Observability
- [ ] `analytics:events` updated
- [ ] external analytics sink (if enabled)
- [ ] yandex alert path sanity

## 5) Outcome
- [ ] PASS (continue rollout)
- [ ] FAIL (rollback)

## Notes

"@

Set-Content -Path $filePath -Value $content -Encoding UTF8
Write-Host "Created report skeleton: $filePath"
