@echo off
if not exist certificates mkdir certificates
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 -keyout certificates\server.key -out certificates\server.crt -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
if errorlevel 1 exit /b 1
echo Zertifikat und RSA-Schluessel erzeugt.
