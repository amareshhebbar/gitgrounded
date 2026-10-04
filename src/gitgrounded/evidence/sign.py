import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from gitgrounded.canonical import sha256_hex
from gitgrounded.errors import EvidenceError


def default_key_path() -> Path:
    env = os.environ.get("GITGROUNDED_SIGNING_KEY")
    if env:
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "gitgrounded" / "keys" / "ed25519.pem"


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as e:
        raise EvidenceError("install gitgrounded[sign] (cryptography) for local signing") from e
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def load_or_create_key(path: Path):
    serialization, Ed25519PrivateKey, _ = _crypto()
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return key


def public_key_raw(key) -> bytes:
    serialization, _, _ = _crypto()
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(public_raw: bytes) -> str:
    return sha256_hex(public_raw)[:16]


class LocalSigner:
    kind = "local"

    def __init__(self, key_path: Path | None = None, scope: str = "self_signed", issuer: str | None = None):
        self.key_path = key_path or default_key_path()
        self.scope = scope
        self.issuer = issuer

    def public_key(self) -> dict[str, str]:
        pub = public_key_raw(load_or_create_key(self.key_path))
        return {"type": "ed25519", "key_id": key_id(pub), "public_key": base64.b64encode(pub).decode()}

    def sign(self, payload: bytes) -> tuple[dict[str, bytes], dict[str, Any]]:
        key = load_or_create_key(self.key_path)
        pub = public_key_raw(key)
        sig = key.sign(payload)
        doc = {
            "type": "ed25519",
            "scope": self.scope,
            "key_id": key_id(pub),
            "public_key": base64.b64encode(pub).decode(),
            "signature": base64.b64encode(sig).decode(),
            "signed_file": "manifest.json",
        }
        if self.issuer:
            doc["issuer"] = self.issuer
        return {"signature/local.json": json.dumps(doc, indent=2).encode()}, {
            "type": "ed25519",
            "key_id": doc["key_id"],
            "scope": self.scope,
        }


class SigstoreSigner:
    kind = "sigstore"

    def sign(self, payload: bytes) -> tuple[dict[str, bytes], dict[str, Any]]:
        with tempfile.TemporaryDirectory() as td:
            mpath = Path(td) / "manifest.json"
            bpath = Path(td) / "manifest.sigstore.json"
            mpath.write_bytes(payload)
            cmd = [sys.executable, "-m", "sigstore", "sign", "--bundle", str(bpath), str(mpath)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 or not bpath.exists():
                raise EvidenceError(f"sigstore signing failed: {r.stderr.strip()[-800:]}")
            data = bpath.read_bytes()
        identity = certificate_identity(json.loads(data))
        return {"signature/manifest.sigstore.json": data}, {"type": "sigstore", "identity": identity}


def certificate_identity(bundle: dict[str, Any]) -> dict[str, Any]:
    try:
        from cryptography import x509
    except ImportError:
        return {}
    vm = bundle.get("verificationMaterial", {})
    raw = None
    if isinstance(vm.get("certificate"), dict):
        raw = vm["certificate"].get("rawBytes")
    elif isinstance(vm.get("x509CertificateChain"), dict):
        certs = vm["x509CertificateChain"].get("certificates", [])
        raw = certs[0].get("rawBytes") if certs else None
    if not raw:
        return {}
    try:
        cert = x509.load_der_x509_certificate(base64.b64decode(raw))
        out: dict[str, Any] = {"not_before": cert.not_valid_before_utc.isoformat()}
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            uris = san.get_values_for_type(x509.UniformResourceIdentifier)
            emails = san.get_values_for_type(x509.RFC822Name)
            out["san"] = (uris or emails or [None])[0]
        except x509.ExtensionNotFound:
            pass
        for ext in cert.extensions:
            if ext.oid.dotted_string == "1.3.6.1.4.1.57264.1.1":
                out["issuer"] = ext.value.value.decode(errors="replace") if hasattr(ext.value, "value") else None
        return out
    except Exception:
        return {}


def in_github_oidc() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true" and bool(os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"))


def _has(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


def build_signer(mode: str):
    if mode == "none":
        return None
    if mode == "sigstore":
        if not _has("sigstore"):
            raise EvidenceError("install gitgrounded[sign] to sign with sigstore")
        return SigstoreSigner()
    if mode == "local":
        return LocalSigner()
    if in_github_oidc() and _has("sigstore"):
        return SigstoreSigner()
    if _has("cryptography"):
        return LocalSigner()
    return None
