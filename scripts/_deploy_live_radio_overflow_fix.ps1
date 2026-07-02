$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_deploy_env.ps1"
$d = Get-DeploySsh

Write-Output "Uploading LiveRadioView.tsx"
scp webapp/frontend/src/components/LiveRadioView.tsx "$($d.Remote)/webapp/frontend/src/components/LiveRadioView.tsx"

Write-Output "Rebuilding bot service"
ssh $($d.Ssh) "cd $($d.ProjectDir) && docker compose up -d --build bot"
