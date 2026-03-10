$ErrorActionPreference = "Stop"

$hasPwsh = [bool](Get-Command pwsh -ErrorAction SilentlyContinue)
$hasMake = [bool](Get-Command make -ErrorAction SilentlyContinue)
$hasDbUrl = -not [string]::IsNullOrWhiteSpace($env:DATABASE_URL)

Write-Host "==== OPS STATUS ===="
Write-Host "cwd: $(Get-Location)"
Write-Host "pwsh: $([int]$hasPwsh)"
Write-Host "make: $([int]$hasMake)"
Write-Host "DATABASE_URL set: $([int]$hasDbUrl)"
Write-Host ""
Write-Host "Recommended flow:"
Write-Host "1) Smoke scripts"
Write-Host "   scripts\smoke_scripts.cmd"
Write-Host ""
Write-Host "2) Verify dry-run (safe, no DB calls)"
Write-Host "   scripts\ops.cmd verify -DryRun -NoBackup -Commit preview -Operator oncall"
Write-Host ""
Write-Host "3) Verify real"
if (-not $hasDbUrl) {
    Write-Host "   [blocked] set DATABASE_URL first"
}
else {
    Write-Host "   scripts\ops.cmd verify -Commit release-YYYYMMDD -Operator oncall"
    if (-not $hasMake) {
        Write-Host "   (prod_verify will fallback to direct pg_dump/psql if make is unavailable)"
    }
}
Write-Host ""
Write-Host "4) Cleanup reports/logs"
Write-Host "   scripts\ops.cmd cleanup -KeepArtifacts 30 -DryRun"
Write-Host "   scripts\ops.cmd cleanup -KeepArtifacts 30"
Write-Host ""
Write-Host "Help: scripts\ops_help.txt"
