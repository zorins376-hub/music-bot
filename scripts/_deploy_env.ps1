# Shared deploy/.env loader for PowerShell scripts (mirrors deploy/ssh_common.py).
$ErrorActionPreference = "Stop"

function Import-DeployEnv {
    $root = Split-Path $PSScriptRoot -Parent
    $envFile = Join-Path $root "deploy\.env"
    if (-not (Test-Path $envFile)) {
        return
    }
    foreach ($line in Get-Content $envFile) {
        $line = $line.Trim()
        if (-not $line -or $line.StartsWith("#") -or $line -notmatch "=") {
            continue
        }
        $key, $val = $line -split "=", 2
        $key = $key.Trim()
        $val = $val.Trim().Trim('"').Trim("'")
        if (-not (Get-Item -Path "Env:$key" -ErrorAction SilentlyContinue)) {
            Set-Item -Path "Env:$key" -Value $val
        }
    }
}

function Get-DeploySsh {
    Import-DeployEnv
    $deployHost = $env:DEPLOY_SSH_HOST
    if (-not $deployHost) {
        throw "DEPLOY_SSH_HOST is required (set in env or deploy/.env)"
    }
    $user = if ($env:DEPLOY_SSH_USER) { $env:DEPLOY_SSH_USER } else { "root" }
    $projectDir = if ($env:DEPLOY_PROJECT_DIR) { $env:DEPLOY_PROJECT_DIR } else { "/opt/music-bot" }
    $ssh = "${user}@${deployHost}"
    [PSCustomObject]@{
        Ssh = $ssh
        ProjectDir = $projectDir
        Remote = "${ssh}:${projectDir}"
    }
}
