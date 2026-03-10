param(
    [string]$Commit = "",
    [string]$Operator = "",
    [switch]$NoBackup,
    [switch]$DryRun,
    [switch]$RotateArtifacts,
    [int]$KeepArtifacts = 20,
    [switch]$Help,
    [switch]$SkipMakeCheck
)

function Invoke-RotateArtifacts {
    param(
        [string]$Directory,
        [string]$Pattern,
        [int]$KeepCount
    )
    if (-not (Test-Path $Directory)) {
        return 0
    }
    $items = Get-ChildItem -Path $Directory -Filter $Pattern -File |
        Sort-Object LastWriteTime -Descending
    if ($items.Count -le $KeepCount) {
        return 0
    }
    $toRemove = $items | Select-Object -Skip $KeepCount
    foreach ($item in $toRemove) {
        Remove-Item -Path $item.FullName -Force -ErrorAction SilentlyContinue
    }
    return @($toRemove).Count
}

if ($Help) {
        @"
Usage:
    pwsh -File scripts/prod_verify.ps1 [options]

Options:
    -Commit <value>        Release tag/commit for report (auto-detect git SHA if omitted)
    -Operator <value>      Operator name (USERNAME/USER env if omitted)
    -NoBackup              Skip backup step (emergency/fast mode)
    -DryRun                Do not execute DB commands, only validate execution plan
    -RotateArtifacts       Rotate logs/reports in docs/reports after run
    -KeepArtifacts <n>     Number of latest logs/reports to keep during rotation (range: 1..500, default: 20)
    -SkipMakeCheck         Force direct CLI path (without make)
    -Help                  Show this help

Examples:
    pwsh -File scripts/prod_verify.ps1 -Commit release-2026-03-10 -Operator devops
    pwsh -File scripts/prod_verify.ps1 -NoBackup -Commit hotfix -Operator oncall
    pwsh -File scripts/prod_verify.ps1 -DryRun -NoBackup -Commit preview -Operator oncall
    pwsh -File scripts/prod_verify.ps1 -RotateArtifacts -KeepArtifacts 30 -Commit release -Operator devops
"@ | Write-Host
        exit 0
}

if ($KeepArtifacts -lt 1 -or $KeepArtifacts -gt 500) {
    throw "KeepArtifacts must be in range 1..500"
}

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportsDir = Join-Path $repoRoot "docs\reports"
$backupDir = Join-Path $repoRoot "backups"

if (-not (Test-Path $reportsDir)) {
    New-Item -ItemType Directory -Path $reportsDir | Out-Null
}
if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

$utcNow = [DateTime]::UtcNow
$ts = $utcNow.ToString("yyyyMMdd_HHmmss")
$logPath = Join-Path $reportsDir ("prod_verify_{0}.log" -f $ts)
$reportPath = Join-Path $reportsDir ("prod_verify_{0}.md" -f $ts)

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

$makeCmd = Get-Command make -ErrorAction SilentlyContinue
$useMake = $true
if (-not $makeCmd) {
    $useMake = $false
}
if ($SkipMakeCheck) {
    $useMake = $false
}

if (-not $useMake -and -not $DryRun) {
    $psqlCmd = Get-Command psql -ErrorAction SilentlyContinue
    if (-not $psqlCmd) {
        throw "Command 'psql' not found. Install PostgreSQL CLI tools or run in environment with psql."
    }
    if (-not $NoBackup) {
        $pgDumpCmd = Get-Command pg_dump -ErrorAction SilentlyContinue
        if (-not $pgDumpCmd) {
            throw "Command 'pg_dump' not found and backup is required. Use -NoBackup for emergency mode or install pg_dump."
        }
    }
}

if (-not $DryRun -and -not $env:DATABASE_URL) {
    throw "DATABASE_URL is not set. Export it before running this script."
}

$databaseUrlState = if ($env:DATABASE_URL) { "<redacted>" } else { "<not set>" }
$rotatedReports = 0
$rotatedLogs = 0

Push-Location $repoRoot
try {
    if ($DryRun) {
        if ($useMake) {
            if ($NoBackup) {
                $verifyCmd = "[DRY-RUN] make prod-db-assert && make prod-db-smoke"
            }
            else {
                $verifyCmd = "[DRY-RUN] make prod-db-verify-all"
            }
        }
        else {
            if ($NoBackup) {
                $verifyCmd = "[DRY-RUN] psql assert + psql smoke"
            }
            else {
                $verifyCmd = "[DRY-RUN] pg_dump + psql assert + psql smoke"
            }
        }
        "[DryRun] $verifyCmd" | Tee-Object -FilePath $logPath
        $exitCode = 0
    }
    elseif ($useMake) {
        if ($NoBackup) {
            $verifyCmd = "make prod-db-assert && make prod-db-smoke"
            "[NoBackup] Running: make prod-db-assert" | Tee-Object -FilePath $logPath
            & make prod-db-assert 2>&1 | Tee-Object -FilePath $logPath -Append
            $exitCode = $LASTEXITCODE
            if ($exitCode -eq 0) {
                "[NoBackup] Running: make prod-db-smoke" | Tee-Object -FilePath $logPath -Append
                & make prod-db-smoke 2>&1 | Tee-Object -FilePath $logPath -Append
                $exitCode = $LASTEXITCODE
            }
        }
        else {
            $verifyCmd = "make prod-db-verify-all"
            & make prod-db-verify-all 2>&1 | Tee-Object -FilePath $logPath
            $exitCode = $LASTEXITCODE
        }
    }
    else {
        if ($NoBackup) {
            $verifyCmd = "psql assert + psql smoke"
            "[NoBackup][Direct] Running: psql assert" | Tee-Object -FilePath $logPath
            & psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f "docs/PROD_DB_ASSERT.sql" 2>&1 | Tee-Object -FilePath $logPath -Append
            $exitCode = $LASTEXITCODE
            if ($exitCode -eq 0) {
                "[NoBackup][Direct] Running: psql smoke" | Tee-Object -FilePath $logPath -Append
                & psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f "docs/PROD_DB_SMOKE.sql" 2>&1 | Tee-Object -FilePath $logPath -Append
                $exitCode = $LASTEXITCODE
            }
        }
        else {
            $backupPath = Join-Path $backupDir ("prod_pre_assert_{0}.sql" -f $ts)
            $verifyCmd = "pg_dump + psql assert + psql smoke"
            "[Direct] Running: pg_dump" | Tee-Object -FilePath $logPath
            & pg_dump "$env:DATABASE_URL" > $backupPath
            $exitCode = $LASTEXITCODE
            if ($exitCode -eq 0) {
                "[Direct] Running: psql assert" | Tee-Object -FilePath $logPath -Append
                & psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f "docs/PROD_DB_ASSERT.sql" 2>&1 | Tee-Object -FilePath $logPath -Append
                $exitCode = $LASTEXITCODE
            }
            if ($exitCode -eq 0) {
                "[Direct] Running: psql smoke" | Tee-Object -FilePath $logPath -Append
                & psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f "docs/PROD_DB_SMOKE.sql" 2>&1 | Tee-Object -FilePath $logPath -Append
                $exitCode = $LASTEXITCODE
            }
        }
    }
}
finally {
    Pop-Location
}

$status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }

$report = @"
# Production Verify Report

Дата/время (UTC): $($utcNow.ToString("yyyy-MM-dd HH:mm:ss"))

Окружение:
- DATABASE_URL: $databaseUrlState
- Release tag/commit: $effectiveCommit
- Исполнитель: $effectiveOperator

Команда:
- $verifyCmd

Режим:
- $(if ($NoBackup) { "no-backup" } else { "with-backup" })
- DryRun: $(if ($DryRun) { "yes" } else { "no" })
- Runner: $(if ($useMake) { "make" } else { "direct-cli" })
- Rotation: $(if ($RotateArtifacts) { "enabled (keep=$KeepArtifacts)" } else { "disabled" })

Результат:
- $status
- Exit code: $exitCode

Артефакты:
- Log: docs/reports/$(Split-Path $logPath -Leaf)
- Backup dir: backups/

Итоговое решение:
- $(if ($exitCode -eq 0) { "rollout continue" } else { "rollback" })
"@

Set-Content -Path $reportPath -Value $report -Encoding UTF8

if ($RotateArtifacts) {
    $rotatedReports = Invoke-RotateArtifacts -Directory $reportsDir -Pattern "prod_verify_*.md" -KeepCount $KeepArtifacts
    $rotatedLogs = Invoke-RotateArtifacts -Directory $reportsDir -Pattern "prod_verify_*.log" -KeepCount $KeepArtifacts
    "[Rotation] Removed reports=$rotatedReports logs=$rotatedLogs (keep=$KeepArtifacts)" | Tee-Object -FilePath $logPath -Append
}

$report = $report + @"

Ротация артефактов:
- reports removed: $rotatedReports
- logs removed: $rotatedLogs
"@

Set-Content -Path $reportPath -Value $report -Encoding UTF8

if ($exitCode -eq 0) {
    Write-Host "Verification completed successfully. Report: $reportPath"
    exit 0
}

Write-Error "Verification failed. Report: $reportPath ; log: $logPath"
exit $exitCode
