$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_deploy_env.ps1"
$d = Get-DeploySsh

Write-Output "== docker compose ps =="
ssh $($d.Ssh) "cd $($d.ProjectDir) && docker compose ps"

Write-Output ""
Write-Output "== index asset references =="
ssh $($d.Ssh) "curl -s http://localhost:8080/" | Select-String -Pattern 'assets/index-[^"]*\.js|sw.js\?v=20260319-cover-svg' -AllMatches | ForEach-Object { $_.Matches.Value } | Select-Object -Unique

Write-Output ""
Write-Output "== broadcast markers in active bundle =="
$bundleCmd = @'
ASSET=$(curl -s http://localhost:8080/ | sed -n 's/.*\/assets\/\(index-[^"]*\.js\).*/\1/p' | head -n 1); test -n "$ASSET" && curl -s http://localhost:8080/assets/$ASSET | grep -ao '/api/broadcast/events\|/api/broadcast/load-playlist' | sort -u
'@
ssh $($d.Ssh) $bundleCmd.Trim()
