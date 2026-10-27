"""Beispielclient für PythonBDE (localhost, JSON-Lines).

Standardmäßig wird exakt die Antwort auf `login` angezeigt.
Optionale Zusatzabfragen: `--ping`, `--whoami`, `--list-users`, `--list-aliases`.
"""
import argparse
import getpass
import json
import socket
import ssl
from pathlib import Path
import sys


def send(sock, f, action, **args):
    """Eine Anfrage senden und genau eine Antwortzeile lesen; keine eigene Ausgabe.

    `sock` bleibt zur Kompatibilität mit älteren Aufrufen im Argumentbestand.
    """
    f.write((json.dumps(dict(action=action, **args), ensure_ascii=False) + "\n").encode("utf-8"))
    f.flush()
    while True:
        line = f.readline()
        if not line:
            raise ConnectionError("Der Server hat die Verbindung ohne Antwort geschlossen")
        packet = json.loads(line.decode("utf-8"))
        if "event" in packet:
            print("Server-Nachricht: " + json.dumps(packet, ensure_ascii=False), file=sys.stderr)
            if packet["event"] == "kicked":
                raise ConnectionError("Sitzung vom Server beendet")
            continue
        return packet


def show_response(action, result):
    """Nur explizit angeforderte Antworten ausgeben."""
    print(json.dumps({"action": action, **result}, ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description="PythonBDE Testclient für localhost")
    parser.add_argument("--port", type=int, default=43650)
    parser.add_argument("--host", default="127.0.0.1", help="IP-Adresse des Servers")
    parser.add_argument("--ping", action="store_true", help="Zusätzlich Server-Ping anzeigen")
    parser.add_argument("--whoami", action="store_true", help="Benutzerdaten separat abfragen")
    parser.add_argument("--list-users", action="store_true", help="Benutzerliste abfragen (nur Admin)")
    parser.add_argument("--list-aliases", action="store_true", help="Verfügbare Aliasnamen abfragen")
    parser.add_argument("--select-alias", metavar="NAME", help="Alias für die Sitzung auswählen")
    parser.add_argument("--release-alias", metavar="NAME", help="Alias-Reservierung wieder freigeben")
    parser.add_argument("--listen", action="store_true", help="Verbunden bleiben und Server-Ereignisse empfangen")
    parser.add_argument("--ca-cert", default=str(Path(__file__).resolve().parent / "certificates" / "ca.crt"),
                        help="Verifiziertes CA-Zertifikat ca.crt (TLS ist Pflicht)")
    args = parser.parse_args(argv)

    trust = Path(args.ca_cert).expanduser()
    if not trust.is_file():
        parser.error(f"TLS-Zertifikat fehlt: {trust} (vorab vom Server kopieren und prüfen)")
    tls = ssl.create_default_context(cafile=str(trust))
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((args.host, args.port), timeout=5) as raw:
      with tls.wrap_socket(raw, server_hostname=args.host) as sock:
        with sock.makefile("rwb") as f:
            if args.ping:
                show_response("ping", send(sock, f, "ping"))

            hello = send(sock, f, "hello", clientPlatform="Python")
            if not hello.get("ok") or hello.get("data", {}).get("tls") is not True:
                raise ConnectionError("TLS-Protokoll nicht bestätigt")
            username = input("Benutzername: ")
            password = getpass.getpass("Passwort: ")
            result = send(sock, f, "login", username=username, password=password)
            show_response("login", result)

            if not result.get("ok"):
                return 1

            if args.whoami:
                show_response("whoami", send(sock, f, "whoami"))
            if args.list_users:
                if result.get("data", {}).get("ADMIN"):
                    show_response("list_users", send(sock, f, "list_users"))
                else:
                    print("Keine Administratorberechtigung für list_users")
            if args.list_aliases:
                show_response("list_aliases", send(sock, f, "list_aliases"))
            if args.select_alias:
                show_response("select_alias", send(sock, f, "select_alias", alias=args.select_alias))
            if args.release_alias:
                show_response("release_alias", send(sock, f, "release_alias", alias=args.release_alias))
            if args.listen:
                print("Warte auf Servernachrichten (Strg+C beendet)...", file=sys.stderr)
                try:
                    while True:
                        packet = f.readline()
                        if not packet:
                            break
                        print(packet.decode("utf-8").rstrip())
                        if json.loads(packet).get("event") == "kicked":
                            break
                except KeyboardInterrupt:
                    pass
            else:
                send(sock, f, "logout")   # Logout bestätigen, aber nicht zusätzlich ausgeben
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
