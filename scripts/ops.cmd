@echo off
setlocal

set SCRIPT_DIR=%~dp0
set VERIFY_CMD=%SCRIPT_DIR%prod_verify.cmd
set CLEANUP_CMD=%SCRIPT_DIR%cleanup_reports.cmd
set STATUS_CMD=%SCRIPT_DIR%status.cmd
set SMOKE_CMD=%SCRIPT_DIR%smoke_scripts.cmd
set REPORT_CMD=%SCRIPT_DIR%new_prod_report.cmd

set ACTION=%~1
if "%ACTION%"=="" goto show_help
if /I "%ACTION%"=="help" goto show_help
if /I "%ACTION%"=="/?" goto show_help
if /I "%ACTION%"=="-h" goto show_help
if /I "%ACTION%"=="--help" goto show_help

if /I "%ACTION%"=="verify" goto run_verify
if /I "%ACTION%"=="cleanup" goto run_cleanup
if /I "%ACTION%"=="status" goto run_status
if /I "%ACTION%"=="smoke" goto run_smoke
if /I "%ACTION%"=="report" goto run_report

echo [ERROR] Unknown command: %ACTION%
goto show_help

:run_verify
if not exist "%VERIFY_CMD%" (
  echo [ERROR] File not found: "%VERIFY_CMD%"
  exit /b 1
)
call "%VERIFY_CMD%" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%

:run_cleanup
if not exist "%CLEANUP_CMD%" (
  echo [ERROR] File not found: "%CLEANUP_CMD%"
  exit /b 1
)
call "%CLEANUP_CMD%" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%

:run_status
if not exist "%STATUS_CMD%" (
  echo [ERROR] File not found: "%STATUS_CMD%"
  exit /b 1
)
call "%STATUS_CMD%"
exit /b %ERRORLEVEL%

:run_smoke
if not exist "%SMOKE_CMD%" (
  echo [ERROR] File not found: "%SMOKE_CMD%"
  exit /b 1
)
call "%SMOKE_CMD%"
exit /b %ERRORLEVEL%

:run_report
if not exist "%REPORT_CMD%" (
  echo [ERROR] File not found: "%REPORT_CMD%"
  exit /b 1
)
call "%REPORT_CMD%" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%

:show_help
echo Usage:
echo   scripts\ops.cmd verify [verify-args]
echo   scripts\ops.cmd cleanup [cleanup-args]
echo   scripts\ops.cmd status
echo   scripts\ops.cmd smoke
echo   scripts\ops.cmd report [report-args]
echo.
echo Examples:
echo   scripts\ops.cmd status
echo   scripts\ops.cmd smoke
echo   scripts\ops.cmd report -Commit release-2026-03-10 -Operator devops
echo   scripts\ops.cmd verify -DryRun -NoBackup -Commit preview -Operator oncall
echo   scripts\ops.cmd cleanup -KeepArtifacts 30 -DryRun
echo.
echo For detailed help:
echo   scripts\prod_verify.cmd /?
echo   scripts\cleanup_reports.cmd /?
echo   scripts\ops_help.txt
exit /b 0
