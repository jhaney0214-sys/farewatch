@echo off
REM Double-click launcher: refresh the deals, then open the report.
REM
REM Feeds are cached for 30 minutes, so opening this twice in a row reuses the
REM cache instead of hammering the sources. Pass /force to refetch regardless.

setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

set REFRESH=
if /i "%~1"=="/force" set REFRESH=--refresh

echo Refreshing Farewatch...
echo.
python fw.py run --open %REFRESH%

if errorlevel 1 (
  echo.
  echo Refresh failed - opening the last saved report instead.
  if exist "out\index.html" (
    start "" "out\index.html"
  ) else (
    echo No saved report found. Check the error above.
  )
  echo.
  pause
)

endlocal
