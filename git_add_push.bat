@echo off
cd /d D:\Git\upsldc

:: 1. Stage everything including bat file changes
git add -A

:: 2. Commit local changes if any. 2>nul hides "nothing to commit" error
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "timestamp=%dt:~0,4%-%dt:~4,2%-%dt:~6,2% %dt:~8,2%:%dt:~10,2%"
git commit -m "Auto commit %timestamp%" 2>nul

:: 3. Remove and re-add csv to force track it
git rm --cached upsldc_hourly_data.csv 2>nul
git add upsldc_hourly_data.csv
git commit -m "Force update UPSLDC data %timestamp%" 2>nul

:: 4. Pull remote changes first, then push ours
git pull --rebase origin main
git push origin main

echo Done