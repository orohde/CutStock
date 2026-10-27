"""Lizenzverwaltung – offline-fähig mit Ed25519-Signaturen.

Ein Lizenzschlüssel ist ein Base64-kodierter String, der die Nutzdaten (JSON)
und eine Ed25519-Signatur enthält. Der öffentliche Schlüssel ist hier
eingebettet; der private Schlüssel bleibt beim Herausgeber.

Schlüsselformat (Base64-dekodiert):
    <64 Bytes Signatur><JSON-Payload>

JSON-Payload:
    {
        "type": "commercial",
        "holder": "Firma XY",
        "issued": "2026-10-27",
        "expires": "2027-10-27"   // optional, null = unbefristet
    }
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# Ed25519 aus der Python-Standardbibliothek (ab 3.6 über hashlib nicht
# verfügbar, aber über das `cryptography`-Paket, oder seit 3.13 in _hashlib).
# Wir nutzen die reine Python-Implementierung von PyNaCl/nacl ODER den
# Fallback über das `cryptography`-Paket. Beide sind leichtgewichtig.
# Falls keines installiert ist, funktioniert die Validierung nicht und
# die App läuft als Community-Edition weiter.

# Öffentlicher Schlüssel des Lizenz-Herausgebers (32 Bytes, hex).
# Dieser Schlüssel wird NUR zur Verifikation verwendet.
# Den zugehörigen privaten Schlüssel erzeugt `generate_keypair()`.
PUBLIC_KEY_HEX = ""

SIG_LENGTH = 64


@dataclass
class LicenseInfo:
    valid: bool
    license_type: str  # "community" | "commercial"
    holder: str
    issued: Optional[str] = None
    expires: Optional[str] = None
    error: Optional[str] = None


def _verify_ed25519(public_key_bytes: bytes, signature: bytes, message: bytes) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        pub.verify(signature, message)
        return True
    except Exception:
        pass

    try:
        import nacl.signing
        verify_key = nacl.signing.VerifyKey(public_key_bytes)
        verify_key.verify(message, signature)
        return True
    except Exception:
        pass

    return False


def validate_license_key(key: str) -> LicenseInfo:
    if not key or not key.strip():
        return LicenseInfo(valid=False, license_type="community", holder="",
                           error="no_key")

    if not PUBLIC_KEY_HEX:
        return LicenseInfo(valid=False, license_type="community", holder="",
                           error="no_public_key")

    try:
        raw = base64.b64decode(key.strip(), validate=True)
    except Exception:
        return LicenseInfo(valid=False, license_type="community", holder="",
                           error="invalid_format")

    if len(raw) <= SIG_LENGTH:
        return LicenseInfo(valid=False, license_type="community", holder="",
                           error="invalid_format")

    signature = raw[:SIG_LENGTH]
    payload_bytes = raw[SIG_LENGTH:]

    pub_bytes = bytes.fromhex(PUBLIC_KEY_HEX)
    if not _verify_ed25519(pub_bytes, signature, payload_bytes):
        return LicenseInfo(valid=False, license_type="community", holder="",
                           error="invalid_signature")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return LicenseInfo(valid=False, license_type="community", holder="",
                           error="invalid_payload")

    expires = payload.get("expires")
    if expires:
        try:
            exp_date = datetime.strptime(expires, "%Y-%m-%d").date()
            if exp_date < date.today():
                return LicenseInfo(
                    valid=False, license_type="expired", holder=payload.get("holder", ""),
                    issued=payload.get("issued"), expires=expires,
                    error="expired")
        except ValueError:
            pass

    return LicenseInfo(
        valid=True,
        license_type=payload.get("type", "commercial"),
        holder=payload.get("holder", ""),
        issued=payload.get("issued"),
        expires=expires,
    )


def get_license_info(settings_path: Path) -> LicenseInfo:
    from core.settings import Settings
    s = Settings(settings_path)
    key = s.value("license/key", "")
    if not key:
        return LicenseInfo(valid=False, license_type="community", holder="",
                           error="no_key")
    return validate_license_key(key)


def generate_keypair() -> tuple[str, str]:
    """Erzeugt ein Ed25519-Schlüsselpaar (privat_hex, öffentlich_hex).

    NUR für die Ersteinrichtung / das CLI-Tool des Herausgebers.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        private_key = Ed25519PrivateKey.generate()
        priv_bytes = private_key.private_bytes_raw()
        pub_bytes = private_key.public_key().public_bytes_raw()
        return priv_bytes.hex(), pub_bytes.hex()
    except ImportError:
        pass

    try:
        import nacl.signing
        signing_key = nacl.signing.SigningKey.generate()
        return signing_key.encode().hex(), signing_key.verify_key.encode().hex()
    except ImportError:
        pass

    raise RuntimeError(
        "Weder 'cryptography' noch 'PyNaCl' installiert. "
        "Installiere eines: pip install cryptography"
    )


def sign_license(private_key_hex: str, payload: dict) -> str:
    """Signiert einen Lizenz-Payload und gibt den Base64-Schlüssel zurück.

    NUR für das CLI-Tool des Herausgebers.
    """
    payload_bytes = json.dumps(payload, separators=(",", ":"),
                               ensure_ascii=False).encode("utf-8")

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
        signature = priv.sign(payload_bytes)
    except ImportError:
        import nacl.signing
        signing_key = nacl.signing.SigningKey(bytes.fromhex(private_key_hex))
        signed = signing_key.sign(payload_bytes)
        signature = signed.signature

    return base64.b64encode(signature + payload_bytes).decode("ascii")
