#!/usr/bin/env bash
set -euo pipefail
umask 077
mkdir -p certificates
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
  -keyout certificates/server.key -out certificates/server.crt \
  -subj '/CN=localhost' \
  -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'
chmod 600 certificates/server.key
