@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0IsaacFactory\scripts\Open-Factory-Editor.ps1" %*
if errorlevel 1 pause
