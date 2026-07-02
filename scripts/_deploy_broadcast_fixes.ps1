$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_deploy_env.ps1"
$d = Get-DeploySsh

$remote = $d.Remote
$files = @(
    "webapp/api.py",
    "webapp/frontend/index.html",
    "webapp/frontend/public/sw.js",
    "webapp/frontend/src/App.tsx",
    "webapp/frontend/src/api.ts",
    "webapp/frontend/src/components/Icons.tsx",
    "webapp/frontend/src/components/PlaylistView.tsx",
    "webapp/frontend/src/components/LiveRadioView.tsx"
)

foreach ($file in $files) {
    Write-Output "Uploading $file"
    scp $file "$remote/$file"
}

ssh $($d.Ssh) "cd $($d.ProjectDir) && docker compose up -d --build bot"
Write-Output "Deploy completed"
