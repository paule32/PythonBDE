@echo off
cd /d "%~dp0"
py -3 rpc_client.py %*
