"""JSON-Lines RPC contracts (transport-independent; Windows/Linux).

The server MAY initiate a whitelisted operation on an already authenticated
connection.  It cannot launch a program on an unrelated remote machine.
"""
from __future__ import annotations

import secrets

RPC_TIMEOUT_SECONDS = 15
ERR_UNKNOWN_FUNCTION = 1001
ERR_CREATE_WINDOW = 1002
ERR_WINDOW_NOT_VISIBLE = 1003


def create_window_request(client: str, client_ip: str = "", *, system_mode: str = "winXP", display=None) -> dict:
    """Create a single server->client request and a cryptographically random ID."""
    if not isinstance(client, str) or not client:
        raise ValueError("Client-ID fehlt")
    from .emulation import validate_client_display
    system_mode, display = validate_client_display(system_mode, display)
    return {
        "systemMode": system_mode,
        "display": display,
        "event": "rpc_request",
        "client": client,
        "lastErrorCode": 0,
        "setFunc": "CreateWindow",
        "rpcId": secrets.token_hex(16),
        "clientIp": client_ip,
    }


def result_message(request: dict, code: int, error_text: str = "") -> dict:
    """Used by a client to acknowledge creation (or failure)."""
    if type(code) is not int or not 0 <= code <= 65535:
        raise ValueError("Ungültiger RPC-Fehlercode")
    response = {
        "action": "rpc_result",
        "client": request["client"],
        "rpcId": request["rpcId"],
        "lastErrorCode": code,
    }
    if code and error_text:
        response["errorText"] = str(error_text).replace("\r", " ").replace("\n", " ")[:256]
    return response


def validate_result(message: dict, pending: dict, session_id: str) -> tuple[int, str]:
    """Match ACK to a pending RPC on this SAME authenticated socket."""
    if not pending:
        raise ValueError("Kein RPC-Aufruf ausstehend")
    if message.get("client") != session_id:
        raise ValueError("RPC-Client-ID passt nicht zur Verbindung")
    if message.get("rpcId") != pending["rpcId"]:
        raise ValueError("Unbekannte oder abgelaufene RPC-ID")
    code = message.get("lastErrorCode")
    if type(code) is not int or not 0 <= code <= 65535:
        raise ValueError("lastErrorCode muss eine Ganzzahl zwischen 0 und 65535 sein")
    error_text = message.get("errorText", "")
    if not isinstance(error_text, str):
        raise ValueError("errorText muss eine Zeichenkette sein")
    return code, error_text.replace("\r", " ").replace("\n", " ")[:256]
