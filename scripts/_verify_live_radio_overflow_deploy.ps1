$ErrorActionPreference = "Stop"

Write-Output "== docker compose ps =="
ssh root@89.169.52.174 "cd /root/music-bot && docker compose ps"

Write-Output ""
Write-Output "== basic radio endpoint status =="
ssh root@89.169.52.174 "curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/api/broadcast"
Write-Output ""
