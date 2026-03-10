@echo off
setlocal

set HAS_PWSH=0
set HAS_MAKE=0
set HAS_DBURL=0

where pwsh >nul 2>&1
if %ERRORLEVEL%==0 set HAS_PWSH=1

where make >nul 2>&1
if %ERRORLEVEL%==0 set HAS_MAKE=1

if not "%DATABASE_URL%"=="" set HAS_DBURL=1

echo ==== OPS STATUS ====
echo cwd: %CD%
echo pwsh: %HAS_PWSH%
echo make: %HAS_MAKE%
echo DATABASE_URL set: %HAS_DBURL%
echo.
echo Recommended flow:
echo 1^) Smoke scripts
if %HAS_PWSH%==1 (
  echo    scripts\smoke_scripts.cmd
) else (
  echo    [skip] pwsh is not available
)
echo.
echo 2^) Verify dry-run ^(safe, no DB calls^)
if %HAS_PWSH%==1 (
  echo    scripts\ops.cmd verify -DryRun -NoBackup -Commit preview -Operator oncall
)
echo.
echo 3^) Verify real
if %HAS_DBURL%==0 (
  echo    [blocked] set DATABASE_URL first
) else (
  if %HAS_MAKE%==1 (
    echo    scripts\ops.cmd verify -Commit release-YYYYMMDD -Operator oncall
  ) else (
    echo    scripts\ops.cmd verify -Commit release-YYYYMMDD -Operator oncall
    echo    ^(prod_verify will fallback to direct pg_dump/psql if make is unavailable^)
  )
)
echo.
echo 4^) Cleanup reports/logs
if %HAS_PWSH%==1 (
  echo    scripts\ops.cmd cleanup -KeepArtifacts 30 -DryRun
  echo    scripts\ops.cmd cleanup -KeepArtifacts 30
)
echo.
echo Help: scripts\ops_help.txt
exit /b 0
