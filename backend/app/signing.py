"""Ed25519 signing for GitLab bindings: the server keeps the public key, the CI
job holds the private one and signs each sync manifest."""

from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def generate_keypair() -> tuple[str, str]:
    """Generate a fresh Ed25519 keypair. Returns (private_pem, public_pem).

    Private key is unencrypted: caller must hand it to the user exactly
    once and never persist it on the server.
    """
    sk = Ed25519PrivateKey.generate()
    private_pem = sk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = (
        sk.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    return private_pem, public_pem


def sign(data: bytes, private_pem: str) -> str:
    """Sign bytes with the PEM-encoded private key. Returns base64 url-safe
    signature suitable for transport."""
    sk = serialization.load_pem_private_key(private_pem.encode("ascii"), password=None)
    if not isinstance(sk, Ed25519PrivateKey):
        raise ValueError("not an Ed25519 private key")
    sig = sk.sign(data)
    return base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")


def verify(data: bytes, signature_b64: str, public_pem: str) -> bool:
    """Verify a base64 url-safe signature against PEM-encoded public key.
    Returns True/False; never raises on bad signatures."""
    try:
        pk = serialization.load_pem_public_key(public_pem.encode("ascii"))
        if not isinstance(pk, Ed25519PublicKey):
            return False
        # Restore padding stripped by sign().
        pad = "=" * (-len(signature_b64) % 4)
        sig = base64.urlsafe_b64decode(signature_b64 + pad)
        pk.verify(sig, data)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
