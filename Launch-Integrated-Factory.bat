@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0IsaacFactory\scripts\Launch-Integrated-Factory.ps1" %*
if errorlevel 1 pause
