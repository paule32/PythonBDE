"""TLS-Konfiguration und Zertifikatsprüfung ohne Qt-Abhängigkeiten.

Diese Hilfen prüfen PEM-Inhalte und Gültigkeit, NICHT die Peer-Vertrauensstellung:
Die Zertifikatskette und SAN/Hostname prüft QSslSocket beim Handshake.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import ipaddress
import os
from pathlib import Path
import platform
import re
import subprocess

DEFAULT_CERT = "certificates/server.crt"
DEFAULT_CA_CERT = "certificates/ca.crt"
DEFAULT_KEY = "certificates/server.key"
CERT_ENV = "PYTHONBDE_TLS_CA_FILE"


def resolve_certificate_file(filename, base):
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("TLS-Zertifikatpfad fehlt")
    candidate = Path(filename).expanduser()
    if not candidate.is_absolute():
        candidate = Path(base) / candidate
    return candidate.resolve(strict=True)


def validate_server_certificate(cert_file, key_file, *, now=None):
    """Prüft priv. Schlüssel, Zertifikat, PEM und Ablauf; liefert RSA/EC."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import load_pem_private_key, Encoding, PublicFormat
    from cryptography.hazmat.primitives.asymmetric import rsa, ec

    certificate = x509.load_pem_x509_certificate(Path(cert_file).read_bytes())
    key = load_pem_private_key(Path(key_file).read_bytes(), password=None)
    algorithm = 'RSA' if isinstance(key, rsa.RSAPrivateKey) else 'EC' if isinstance(key, ec.EllipticCurvePrivateKey) else None
    if not algorithm:
        raise ValueError('TLS unterstützt hier ausschließlich RSA/EC-Privatschlüssel')
    if key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo) != certificate.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo):
        raise ValueError('TLS-Zertifikat und privater Schlüssel gehören nicht zusammen')
    now = now or datetime.now(timezone.utc)
    valid_from = certificate.not_valid_before_utc
    valid_until = certificate.not_valid_after_utc
    if not valid_from <= now <= valid_until:
        raise ValueError('TLS-Zertifikat ist noch nicht oder nicht mehr gültig')
    try:
        san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if not san.get_values_for_type(x509.DNSName) and not san.get_values_for_type(x509.IPAddress):
            raise ValueError('TLS-Zertifikat hat keine DNS-/IP-SubjectAlternativeName-Einträge')
    except x509.ExtensionNotFound as exc:
        raise ValueError('TLS-Zertifikat benötigt SubjectAlternativeName (SAN)') from exc
    if os.name == 'posix' and (Path(key_file).stat().st_mode & 0o077):
        raise PermissionError('TLS-Privatschlüssel muss unter Linux Modus 0600 besitzen')
    return algorithm


def make_test_certificate(cert_file, key_file, dns_names=('localhost',), ip_addresses=('127.0.0.1',), days=365):
    """Erzeugt für lokalen Test RSA-3072 + self-signed SAN. Keine CA-Verwaltung."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    if not 1 <= int(days) <= 825:
        raise ValueError('Gültigkeit 1..825 Tage')
    san = []
    for name in dns_names:
        name = str(name).strip()
        if not name or len(name) > 253 or not re.fullmatch(r'[A-Za-z0-9._-]+', name):
            raise ValueError('Ungültiger DNS-Name')
        san.append(x509.DNSName(name))
    for value in ip_addresses:
        san.append(x509.IPAddress(ipaddress.ip_address(str(value))))
    if not san:
        raise ValueError('Mindestens eine DNS/IP SAN erforderlich')
    cert_file, key_file = Path(cert_file), Path(key_file)
    cert_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if cert_file.exists() or key_file.exists():
        raise FileExistsError('TLS-Zertifikat oder Schlüssel existiert bereits – wird nicht überschrieben')
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = datetime.now(timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_names[0] if dns_names else str(ip_addresses[0]))])
    cert = (x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=int(days)))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True,
                                    content_commitment=False, data_encipherment=False,
                                    key_agreement=False, key_cert_sign=False, crl_sign=False,
                                    encipher_only=False, decipher_only=False), critical=True)
        .sign(key, hashes.SHA256()))
    key_bytes = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption())
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    # Private key FIRST; if a subsequent write fails, do not leave partial valid pair.
    try:
        fd = os.open(str(key_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as fp:
            fp.write(key_bytes)
        if os.name == 'nt':
            # Do not silently leave an inherited, broadly readable Windows private key.
            account = os.environ.get('USERDOMAIN', '') + '\\' + os.environ.get('USERNAME', '') if os.environ.get('USERDOMAIN') else os.environ.get('USERNAME', '')
            if not account:
                raise PermissionError('Windows Benutzername für private Schlüssel-ACL nicht ermittelbar')
            result = subprocess.run(['icacls', str(key_file), '/inheritance:r', '/grant:r', f'{account}:F', 'SYSTEM:F'],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode:
                raise PermissionError('Windows NTFS-ACL konnte nicht gesetzt werden: ' + result.stderr.strip())
        fd = os.open(str(cert_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, 'wb') as fp:
            fp.write(cert_bytes)
    except BaseException:
        key_file.unlink(missing_ok=True)
        cert_file.unlink(missing_ok=True)
        raise
    validate_server_certificate(cert_file, key_file)
    return cert_file, key_file


# v0.5.9: Certificate Authority getrennt vom TLS-Endpunkt.
# Das alte make_test_certificate bleibt für historische Tests/Kompatibilität.
def validate_ca_bundle(filename):
    """Eine Trust-Datei muss CA-Zertifikate enthalten, nicht ein Server-Leaf."""
    from cryptography import x509
    raw = Path(filename).read_bytes()
    chunks = re.findall(br"-----BEGIN CERTIFICATE-----\s+.*?-----END CERTIFICATE-----", raw, re.S)
    if not chunks:
        raise ValueError("Kein PEM-Zertifikat in der CA-Datei gefunden")
    now = datetime.now(timezone.utc)
    count = 0
    for pem in chunks:
        cert = x509.load_pem_x509_certificate(pem)
        if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
            raise ValueError("CA-Zertifikat noch nicht oder nicht mehr gueltig")
        try:
            constraint = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
        except x509.ExtensionNotFound:
            constraint = None
        if constraint is None or not constraint.ca:
            raise ValueError("Die Trust-Datei enthaelt ein Serverzertifikat statt einer CA (BasicConstraints CA=False). "
                             "Bitte certificates/ca.crt verwenden, nicht server.crt")
        try:
            usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
            if not usage.key_cert_sign:
                raise ValueError("CA-Zertifikat darf keine Zertifikate signieren")
        except x509.ExtensionNotFound:
            pass
        count += 1
    return count


def make_ca_signed_server_certificates(cert_file, key_file, ca_cert_file, ca_key_file,
                                       dns_names=('localhost',), ip_addresses=('127.0.0.1',), days=365):
    """Erzeugt private Test-CA + Server-Leaf; bestehende Dateien nie überschreiben."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    days = int(days)
    if not 1 <= days <= 825:
        raise ValueError('Server-Zertifikat: Gueltigkeit 1..825 Tage')
    dns = tuple(str(name).strip() for name in dns_names)
    ips = tuple(str(value).strip() for value in ip_addresses)
    san = []
    for name in dns:
        if not name or len(name) > 253 or not re.fullmatch(r'[A-Za-z0-9._-]+', name):
            raise ValueError('Ungueltiger DNS-Name')
        san.append(x509.DNSName(name))
    for value in ips:
        san.append(x509.IPAddress(ipaddress.ip_address(value)))
    if not san:
        raise ValueError('Mindestens ein SAN-Name/IP erforderlich')

    paths = tuple(map(Path, (cert_file, key_file, ca_cert_file, ca_key_file)))
    if len({str(path.resolve()) for path in paths}) != 4:
        raise ValueError('Zertifikat- und Schluesseldateien muessen verschieden sein')
    for path in paths:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f'Vorhandene TLS-Datei wird NICHT ueberschrieben: {path}')

    root_private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    server_private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = datetime.now(timezone.utc)
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PythonBDE Private Test Root CA')])
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns[0] if dns else ips[0])])

    ca_cert = (x509.CertificateBuilder()
               .subject_name(root_name).issuer_name(root_name).public_key(root_private.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(now - timedelta(minutes=5))
               .not_valid_after(now + timedelta(days=3650))
               .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
               .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                       key_encipherment=False, data_encipherment=False, key_agreement=False,
                       key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_private.public_key()), critical=False)
               .sign(root_private, hashes.SHA256()))
    server_cert = (x509.CertificateBuilder()
                .subject_name(server_name).issuer_name(root_name).public_key(server_private.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(now + timedelta(days=days))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                        key_encipherment=True, data_encipherment=False, key_agreement=False,
                        key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.SubjectAlternativeName(san), critical=False)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_private.public_key()), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_private.public_key()), critical=False)
                .sign(root_private, hashes.SHA256()))

    def encode_key(key):
        return key.private_bytes(serialization.Encoding.PEM,
                                 serialization.PrivateFormat.TraditionalOpenSSL,
                                 serialization.NoEncryption())

    data = {paths[0]: server_cert.public_bytes(serialization.Encoding.PEM),
            paths[1]: encode_key(server_private),
            paths[2]: ca_cert.public_bytes(serialization.Encoding.PEM),
            paths[3]: encode_key(root_private)}

    def apply_win_acl(path):
        domain = os.environ.get('USERDOMAIN')
        username = os.environ.get('USERNAME', '')
        account = (domain + '\\' + username) if domain and username else username
        if not account:
            raise PermissionError('Windows-Konto fuer NTFS-Key-ACL fehlt')
        result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                                 f'{account}:F', 'SYSTEM:F'],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise PermissionError('NTFS-Key-ACL fehlgeschlagen: ' + result.stderr.strip())

    created = []
    try:
        for path, content in data.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            is_private = path in (paths[1], paths[3])
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if is_private else 0o644)
            created.append(path)
            with os.fdopen(fd, 'wb') as file:
                file.write(content)
            if is_private and os.name == 'nt':
                apply_win_acl(path)
        validate_server_certificate(paths[0], paths[1])
        validate_ca_bundle(paths[2])
        return paths
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
