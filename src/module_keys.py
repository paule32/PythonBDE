"""Prepare .cpy signing keys for a PythonBDE server (Qt5 not required).

Usage: python module_keys.py --dbf <same path used by server.py>
Public key must be copied to trusted_module_signing_public.pem on the client
via a trusted channel, after verifying the displayed SHA-256 fingerprint.
"""
from __future__ import annotations

import argparse
from pythonbde.platform_support import default_dbf_path
from pythonbde.cpy_modules import ModuleSigner


def main():
    parser = argparse.ArgumentParser(description='Prepare PythonBDE .cpy Ed25519 publisher identity')
    parser.add_argument('--dbf', default=str(default_dbf_path()),
                        help='The exact users.dbf path used by the server')
    args = parser.parse_args()
    signer = ModuleSigner(args.dbf)
    print('Server module signing public key:', signer.public_path)
    print('Public-key SHA-256 fingerprint:', signer.key_id)
    print('Copy/verify this public key OUT-OF-BAND to the RPC client as:')
    print('    trusted_module_signing_public.pem')
    print('Never copy the private module_signing_private.key to clients.')


if __name__ == '__main__':
    main()
