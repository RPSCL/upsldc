@echo off
cd /d D:\Git\upsldc

git add .

git diff --cached --quiet
if %errorlevel%==0 (
    echo No changes to commit.
) else (
    git commit -m "Update UPSLDC data hourly from UCE PC"
    git push
)

exit