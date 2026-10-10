@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if not "%~1"=="" (
  python 직원관리.py "%~1"
  echo.
)
:loop
echo ==================================================
python 직원관리.py
echo ==================================================
echo  명령 예:  승인 teacher01   /   거절 teacher01   /   퇴사 teacher01
echo  가입신청 파일을 이 창에 끌어다 놓아도 승인됩니다.
echo  그냥 엔터를 누르면 끝내고, 바뀐 계정으로 화면을 새로 만듭니다.
set "CMD="
set /p "CMD=명령> "
if "%CMD%"=="" goto rebuild
python 직원관리.py %CMD%
echo.
goto loop
:rebuild
echo.
python 수강관리.py --auto
pause
