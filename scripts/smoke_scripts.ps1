$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot
try {
    function Assert-ParserOk {
        param([string]$Path)
        $tok = $null
        $err = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tok, [ref]$err)
        if ($err -and $err.Count -gt 0) {
            $messages = $err | ForEach-Object { $_.Message } | Out-String
            throw "Parser errors in $Path`n$messages"
        }
        Write-Host "[OK] parser: $Path"
    }

    Assert-ParserOk "scripts/prod_verify.ps1"
    Assert-ParserOk "scripts/cleanup_reports.ps1"
    Assert-ParserOk "scripts/ops.ps1"

    & pwsh -File scripts/prod_verify.ps1 -Help | Out-Null
    Write-Host "[OK] prod_verify help"

    & pwsh -File scripts/cleanup_reports.ps1 -Help | Out-Null
    Write-Host "[OK] cleanup_reports help"

    if (Test-Path "scripts/prod_verify.cmd") {
        & scripts\prod_verify.cmd /? | Out-Null
        Write-Host "[OK] prod_verify.cmd help"
    }

    if (Test-Path "scripts/cleanup_reports.cmd") {
        & scripts\cleanup_reports.cmd /? | Out-Null
        Write-Host "[OK] cleanup_reports.cmd help"
    }

    if (Test-Path "scripts/ops.cmd") {
        & scripts\ops.cmd /? | Out-Null
        Write-Host "[OK] ops.cmd help"
    }

    if (Test-Path "scripts/smoke_scripts.cmd") {
        & scripts\smoke_scripts.cmd /? | Out-Null
        Write-Host "[OK] smoke_scripts.cmd help"
    }

    & pwsh -File scripts/prod_verify.ps1 -DryRun -NoBackup -Commit smoke -Operator ci | Out-Null
    Write-Host "[OK] prod_verify dry-run"

    & pwsh -File scripts/cleanup_reports.ps1 -KeepArtifacts 30 -DryRun | Out-Null
    Write-Host "[OK] cleanup dry-run"

    & pwsh -File scripts/ops.ps1 verify -DryRun -NoBackup -Commit smoke-ops -Operator ci | Out-Null
    Write-Host "[OK] ops verify route"

    & pwsh -File scripts/ops.ps1 cleanup -KeepArtifacts 30 -DryRun | Out-Null
    Write-Host "[OK] ops cleanup route"

    & pwsh -File scripts/ops.ps1 status | Out-Null
    Write-Host "[OK] ops status route"

    if (Test-Path "scripts/ops.cmd") {
        & scripts\ops.cmd status | Out-Null
        Write-Host "[OK] ops.cmd status route"
    }

    Write-Host "[OK] scripts smoke passed"
}
finally {
    Pop-Location
}
