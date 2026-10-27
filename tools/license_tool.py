#!/usr/bin/env python3
"""CLI-Tool zum Erzeugen und Verwalten von CutStock-Lizenzen.

Nutzung:
    # Schlüsselpaar erzeugen (einmalig)
    python tools/license_tool.py keygen

    # Lizenz erzeugen
    python tools/license_tool.py create --holder "Firma XY" \
        --private-key <hex> [--expires 2027-12-31]

    # Lizenz prüfen
    python tools/license_tool.py verify <lizenzschlüssel>
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.license import generate_keypair, sign_license, validate_license_key


def cmd_keygen(_args: argparse.Namespace) -> None:
    priv, pub = generate_keypair()
    print("=== Ed25519-Schlüsselpaar ===")
    print()
    print(f"Privater Schlüssel (GEHEIM HALTEN!):\n  {priv}")
    print()
    print(f"Öffentlicher Schlüssel (in core/license.py eintragen):\n  {pub}")
    print()
    print("Den öffentlichen Schlüssel als PUBLIC_KEY_HEX in")
    print("core/license.py eintragen, dann können Lizenzen verifiziert werden.")


def cmd_create(args: argparse.Namespace) -> None:
    if not args.private_key:
        print("Fehler: --private-key ist erforderlich.", file=sys.stderr)
        sys.exit(1)

    payload = {
        "type": "commercial",
        "holder": args.holder,
        "issued": date.today().isoformat(),
    }
    if args.expires:
        payload["expires"] = args.expires

    key = sign_license(args.private_key, payload)
    print("=== Lizenzschlüssel ===")
    print()
    print(key)
    print()
    print(f"Inhaber: {args.holder}")
    print(f"Ausgestellt: {payload['issued']}")
    if args.expires:
        print(f"Gültig bis: {args.expires}")
    else:
        print("Gültig: unbefristet")


def cmd_verify(args: argparse.Namespace) -> None:
    info = validate_license_key(args.key)
    print(f"Gültig:     {info.valid}")
    print(f"Typ:        {info.license_type}")
    print(f"Inhaber:    {info.holder}")
    if info.issued:
        print(f"Ausgestellt: {info.issued}")
    if info.expires:
        print(f"Gültig bis: {info.expires}")
    if info.error:
        print(f"Fehler:     {info.error}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CutStock Lizenz-Tool")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("keygen", help="Ed25519-Schlüsselpaar erzeugen")

    p_create = sub.add_parser("create", help="Lizenz erzeugen")
    p_create.add_argument("--holder", required=True, help="Name des Lizenznehmers")
    p_create.add_argument("--private-key", required=True, help="Privater Schlüssel (hex)")
    p_create.add_argument("--expires", help="Ablaufdatum (YYYY-MM-DD), leer = unbefristet")

    p_verify = sub.add_parser("verify", help="Lizenzschlüssel prüfen")
    p_verify.add_argument("key", help="Der Lizenzschlüssel (Base64)")

    args = parser.parse_args()
    if args.command == "keygen":
        cmd_keygen(args)
    elif args.command == "create":
        cmd_create(args)
    elif args.command == "verify":
        cmd_verify(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
