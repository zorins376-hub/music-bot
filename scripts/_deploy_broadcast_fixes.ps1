$ErrorActionPreference = "Stop"

$remote = "root@89.169.52.174:/root/music-bot"
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

ssh root@89.169.52.174 "cd /root/music-bot && docker compose up -d --build bot"
Write-Output "Deploy completed"
