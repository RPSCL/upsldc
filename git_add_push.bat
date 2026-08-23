@echo off
cd /d D:\Git\upsldc

:: 0. Nuke any stuck rebase and make sure we are on main
if exist .git\rebase-merge rmdir /s /q .git\rebase-merge
git checkout main

:: 1. Get timestamp
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "timestamp=%dt:~0,4%-%dt:~4,2%-%dt:~6,2% %dt:~8,2%:%dt:~10,2%"

:: 2. Stage everything and force add csv
git add -A
git add --force upsldc_hourly_data.csv

:: 3. Commit only if there are changes
git diff --cached --quiet
if %errorlevel% neq 0 (
    git commit -m "Force update UPSLDC data %timestamp%"
)

:: 4. Pull with merge instead of rebase to avoid getting stuck
git pull origin main

:: 5. Push. Use --force-with-lease because csv will conflict every hour
git push --force-with-lease origin main

echo Done
pause