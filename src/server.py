"""Startpunkt: python server.py [--dbf PFAD] [--port PORT]."""
from __future__ import annotations

import argparse
import sys

from pythonbde.gui_errors import install_exception_handler

# Must be active before QApplication / PyQt5 is imported.
install_exception_handler(app_name="PythonBDE Server")


def main():
    from pythonbde.platform_support import default_dbf_path, file_lock_backend, operating_system, password_backend
    parser = argparse.ArgumentParser(description="PythonBDE Qt5 Server für Windows und Linux")
    parser.add_argument("--dbf", default=str(default_dbf_path()), help="DBF der Benutzerverwaltung")
    parser.add_argument("--check-platform", action="store_true", help="Plattform/Backend anzeigen, benötigt kein PyQt5")
    parser.add_argument("--port", type=int, default=None, help="Port nur für diesen Start überschreiben")
    parser.add_argument("--ip", default=None, help="Bind-IP nur für diesen Start überschreiben")
    args = parser.parse_args()
    if args.check_platform:
        print(f"Betriebssystem: {operating_system()}")
        print(f"Passwort-Backend: {password_backend()}")
        print(f"Dateisperre: {file_lock_backend()}")
        print(f"Benutzerdatei: {args.dbf}")
        return 0

    # Separate native Win32 watchdog must start *before* Qt is imported.
    from pythonbde.native_watchdog import start_watchdog
    start_watchdog(app_name="PythonBDE Server")

    from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox
    from pythonbde.single_instance import WindowsMutex, ActivationServer, signal_existing
    from pythonbde.auth import AuthError, UserManager
    from pythonbde.dbf import DBFStore
    from pythonbde.gui import CredentialDialog, MainWindow
    from pythonbde.settings import load_settings
    from dataclasses import replace

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)  # X versteckt während des Serverbetriebs, kein implizites Quit
    # Vor Öffnen der exklusiv gesperrten DBF auf weitere lokale Instanz prüfen.
    mutex = WindowsMutex()
    if mutex.existing:
        notified = signal_existing()
        QMessageBox.information(None, "PythonBDE", "Das Serverprogramm wurde bereits gestartet. " +
                                ("Das laufende Fenster wird wieder angezeigt." if notified else
                                 "Die laufende Instanz konnte nicht benachrichtigt werden."))
        mutex.close()
        return 0
    activation = None
    try:
        with DBFStore(args.dbf) as store:
            auth = UserManager(store)
            if not store.users:
                dlg = CredentialDialog(bootstrap=True)
                if dlg.exec_() != QDialog.Accepted:
                    return 1
                try:
                    auth.bootstrap(dlg.username.text().strip(), dlg.password.text())
                    admin_username = dlg.username.text().strip()
                except (AuthError, ValueError) as e:
                    QMessageBox.critical(None, "Administrator anlegen", str(e))
                    return 1
            else:
                authenticated = False
                for _ in range(3):
                    dlg = CredentialDialog()
                    if dlg.exec_() != QDialog.Accepted:
                        return 1
                    if auth.authenticate(dlg.username.text().strip(), dlg.password.text(), require_admin=True):
                        admin_username = dlg.username.text().strip()
                        authenticated = True
                        break
                    QMessageBox.warning(None, "Anmeldung", "Administrator-Anmeldung fehlgeschlagen")
                if not authenticated:
                    return 1
            config = load_settings()
            if args.port is not None or args.ip is not None:
                config = replace(config, port=args.port if args.port is not None else config.port,
                                 ip=args.ip if args.ip is not None else config.ip).validate()
            wnd = MainWindow(auth, config, admin_username=admin_username)
            if mutex.handle is not None:
                activation = ActivationServer(wnd.activate_from_second_instance)
            wnd.show()
            return app.exec_()
    except (OSError, ValueError) as e:
        QMessageBox.critical(None, "PythonBDE – Datei nicht geöffnet", str(e))
        return 2
    finally:
        if activation is not None:
            activation.close()
        mutex.close()


if __name__ == "__main__":
    raise SystemExit(main())
