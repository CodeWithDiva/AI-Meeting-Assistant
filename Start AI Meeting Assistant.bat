@echo off
REM Double-click this file to start the AI Meeting Assistant.
REM It starts the backend and frontend, then opens the app in your browser.
REM Leave the two windows that open running in the background while you use the app.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-app.ps1"
pause
