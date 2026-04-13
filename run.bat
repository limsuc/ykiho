@echo off
cd /d "%~dp0"
setlocal EnableDelayedExpansion

set "PYEXE=%LocalAppData%\Programs\Python\Python312\python.exe"
if not exist "!PYEXE!" set "PYEXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if not exist "!PYEXE!" set "PYEXE=%LocalAppData%\Programs\Python\Python310\python.exe"

if not exist "!PYEXE!" (
  echo Python을 찾을 수 없습니다.
  echo winget install Python.Python.3.12
  echo 또는 https://www.python.org/downloads/ 에서 설치할 때 "Add python.exe to PATH"를 체크하세요.
  pause
  exit /b 1
)

echo Python: !PYEXE!
"!PYEXE!" -m pip install -r requirements.txt -q
echo.
echo ========================================
echo  서버 주소: http://127.0.0.1:5000
echo  이 창을 닫지 마세요. 닫으면 브라우저에서 접속할 수 없습니다.
echo  종료: Ctrl+C
echo ========================================
echo.
"!PYEXE!" app.py
pause
