$ErrorActionPreference = "Stop"

function Invoke-RemoteStatus([string] $label, [string] $curlArgs) {
    Write-Output $label
    ssh root@89.169.52.174 "curl -s -o /dev/null -w '%{http_code}' $curlArgs"
    Write-Output ""
}

Invoke-RemoteStatus "GET /api/broadcast" "http://localhost:8080/api/broadcast"
Invoke-RemoteStatus "GET /api/broadcast/events" "http://localhost:8080/api/broadcast/events"
Invoke-RemoteStatus "POST /api/broadcast/load-playlist" "-X POST http://localhost:8080/api/broadcast/load-playlist"
