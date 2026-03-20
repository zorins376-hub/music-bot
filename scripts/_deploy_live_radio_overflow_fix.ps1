$ErrorActionPreference = "Stop"

Write-Output "Uploading LiveRadioView.tsx"
scp webapp/frontend/src/components/LiveRadioView.tsx root@89.169.52.174:/root/music-bot/webapp/frontend/src/components/LiveRadioView.tsx

Write-Output "Rebuilding bot service"
ssh root@89.169.52.174 "cd /root/music-bot && docker compose up -d --build bot"
