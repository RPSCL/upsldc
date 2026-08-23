@echo off
cd /d D:\Git\upsldc

python fetch_upsldc.py

git add .

git diff --cached --quiet
if %errorlevel%==0 (
    exit /b 0
)

git commit -m "Update UPSLDC data hourly from UCE PC"
git push