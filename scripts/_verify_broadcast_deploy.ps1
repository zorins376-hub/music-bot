$ErrorActionPreference = "Stop"

Write-Output "== docker compose ps =="
ssh root@89.169.52.174 "cd /root/music-bot && docker compose ps"

Write-Output ""
Write-Output "== index asset references =="
ssh root@89.169.52.174 "curl -s http://localhost:8080/" | Select-String -Pattern 'assets/index-[^"]*\.js|sw.js\?v=20260319-cover-svg' -AllMatches | ForEach-Object { $_.Matches.Value } | Select-Object -Unique

Write-Output ""
Write-Output "== broadcast markers in active bundle =="
ssh root@89.169.52.174 "ASSET=$(curl -s http://localhost:8080/ | sed -n 's/.*\/assets\/\(index-[^"]*\.js\).*/\1/p' | head -n 1); test -n \"$ASSET\" && curl -s http://localhost:8080/assets/$ASSET | grep -ao '/api/broadcast/events\|/api/broadcast/load-playlist' | sort -u"
