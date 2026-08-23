@echo off
cd /d D:\Git\upsldc

:: 0. If stuck in rebase, nuke it and hard reset to remote
if exist .git\rebase-merge (
    echo Stuck rebase detected. Cleaning...
    rmdir /s /q .git\rebase-merge
    git checkout main
    git reset --hard origin/main
)

:: 1. Make sure we are on main
git checkout main

:: 2. Get timestamp
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "timestamp=%dt:~0,4%-%dt:~4,2%-%dt:~6,2% %dt:~8,2%:%dt:~10,2%"

:: 3. Stage everything and force add csv
git add -A
git add --force upsldc_hourly_data.csv

:: 4. Commit only if there are changes
git diff --cached --quiet
if %errorlevel% neq 0 (
    git commit -m "Force update UPSLDC data %timestamp%"
)

:: 5. Pull with merge to avoid rebase conflicts
git pull origin main

:: 6. Push. Use --force-with-lease because csv conflicts every hour
git push --force-with-lease origin main

echo Done
timeout /t 10 /nobreak >nul
exit