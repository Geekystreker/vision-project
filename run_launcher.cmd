@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Virtual environment not found at "%PYTHON_EXE%".
    echo Create it first with: py -3.11 -m venv .venv
    exit /b 1
)

"%PYTHON_EXE%" "%ROOT%launcher.py"
