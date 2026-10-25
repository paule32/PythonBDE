#!/bin/sh
cd "$(dirname "$0")" || exit 1
exec "${PYTHON:-python3}" rpc_client.py "$@"
