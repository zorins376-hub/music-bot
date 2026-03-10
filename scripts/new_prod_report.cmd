@echo off
setlocal

set SCRIPT_DIR=%~dp0
set PS1=%SCRIPT_DIR%new_prod_report.ps1

if not exist "%PS1%" (
  echo [ERROR] File not found: "%PS1%"
  exit /b 1
)

if /I "%~1"=="/?" goto show_help
if /I "%~1"=="-h" goto show_help
if /I "%~1"=="--help" goto show_help

where pwsh >nul 2>&1
if %ERRORLEVEL%==0 (
  pwsh -File "%PS1%" %*
  exit /b %ERRORLEVEL%
)

where powershell >nul 2>&1
if %ERRORLEVEL%==0 (
  powershell -ExecutionPolicy Bypass -File "%PS1%" %*
  exit /b %ERRORLEVEL%
)

echo [ERROR] Neither 'pwsh' nor 'powershell' found in PATH.
exit /b 1

:show_help
echo Usage:
echo   scripts\new_prod_report.cmd [-Commit value] [-Operator value]
echo.
echo Creates timestamped production execution report in docs\reports.
echo.
echo Alternative:
echo   pwsh -File scripts/new_prod_report.ps1
exit /b 0
