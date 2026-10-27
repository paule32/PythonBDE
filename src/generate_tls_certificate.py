"""PythonBDE TLS: erstelle eine private CA und getrenntes Serverzertifikat."""
import argparse
from pathlib import Path
from pythonbde.settings import application_dir
from pythonbde.tls_security import make_ca_signed_server_certificates


def main(argv=None):
    parser = argparse.ArgumentParser(description='PythonBDE: CA und Server-TLS-Zertifikat generieren')
    parser.add_argument('--dns', action='append', default=[], help='DNS-Name, mehrfach moeglich')
    parser.add_argument('--ip', action='append', default=[], help='IP-Adresse, mehrfach moeglich')
    parser.add_argument('--days', type=int, default=365)
    parser.add_argument('--cert', default='certificates/server.crt')
    parser.add_argument('--key', default='certificates/server.key')
    parser.add_argument('--ca-cert', default='certificates/ca.crt')
    parser.add_argument('--ca-key', default='certificates/ca.key')
    args = parser.parse_args(argv)
    base = application_dir()
    paths = []
    for value in (args.cert, args.key, args.ca_cert, args.ca_key):
        path = Path(value).expanduser()
        paths.append(path if path.is_absolute() else base / path)
    try:
        cert, key, ca_cert, ca_key = make_ca_signed_server_certificates(
            *paths, dns_names=args.dns or ['localhost'],
            ip_addresses=args.ip or ['127.0.0.1'], days=args.days)
    except FileExistsError as exc:
        parser.error(str(exc) + '\nBitte alte Dateien vorher an einem sicheren Ort sichern oder neue Pfade mit --cert/--key/--ca-cert/--ca-key verwenden.')
    print('Server-Zertifikat:', cert)
    print('Server-Schluessel (GEHEIM):', key)
    print('CA-Zertifikat (an Clients verteilen):', ca_cert)
    print('CA-Schluessel (STRENG GEHEIM; offline aufbewahren):', ca_key)
    print('RPC-Client: --ca-cert', ca_cert.name)
    print('Fingerprint vergleichen: openssl x509 -in "' + str(ca_cert) + '" -noout -fingerprint -sha256')


if __name__ == '__main__':
    main()
