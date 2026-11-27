@echo off
echo Starting SQS Consumer Worker locally...
cd /d "%~dp0\.."
set PYTHONPATH=%CD%
python -m consumer.sqs_consumer
pause
