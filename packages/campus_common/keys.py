"""Idempotently create the JWT signing key pair and a self-signed local TLS certificate.

Usage: python -m packages.campus_common.keys <private_dir> <public_dir> <tls_dir>
"""
import datetime
import ipaddress
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

RUNTIME_UID = 10001


def write(path: Path, data: bytes, mode: int, owner: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.chmod(path, mode)
    if owner is not None and hasattr(os, "chown"):
        os.chown(path, owner, owner)


def jwt_keys(private_dir: Path, public_dir: Path) -> None:
    private_path, public_path = private_dir / "private.pem", public_dir / "public.pem"
    if private_path.exists() and public_path.exists():
        print("JWT key pair already present")
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    owner = RUNTIME_UID if os.name != "nt" and os.geteuid() == 0 else None
    write(private_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()), 0o400, owner)
    write(public_path, key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo), 0o444)
    print("Generated JWT key pair")


def tls_certificate(tls_dir: Path) -> None:
    cert_path, key_path = tls_dir / "cert.pem", tls_dir / "key.pem"
    if cert_path.exists() and key_path.exists():
        print("TLS certificate already present")
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Campus ERP (development)")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
                   .not_valid_after(now + datetime.timedelta(days=397))
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .sign(key, hashes.SHA256()))
    # Development-only certificate; the gateway's unprivileged user must be able to read it.
    write(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()), 0o444)
    write(cert_path, certificate.public_bytes(serialization.Encoding.PEM), 0o444)
    print("Generated self-signed TLS certificate for localhost")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    jwt_keys(Path(sys.argv[1]), Path(sys.argv[2]))
    tls_certificate(Path(sys.argv[3]))
