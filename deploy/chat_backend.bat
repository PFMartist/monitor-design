@echo off
rem Local chat backend for the Device Monitor console (no console window).
cd /d %~dp0
pythonw chat_backend.py
