$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_deploy_env.ps1"
$d = Get-DeploySsh

Write-Output "== docker compose ps =="
ssh $($d.Ssh) "cd $($d.ProjectDir) && docker compose ps"

Write-Output ""
Write-Output "== basic radio endpoint status =="
ssh $($d.Ssh) "curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/api/broadcast"
Write-Output ""
