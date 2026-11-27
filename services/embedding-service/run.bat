@echo off
echo Starting High-Speed Embedding Microservice on port 8001...
cd /d "%~dp0"
uvicorn app:app --host 0.0.0.0 --port 8001
pause
