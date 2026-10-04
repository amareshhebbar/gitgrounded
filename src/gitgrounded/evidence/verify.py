import base64
import json
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from gitgrounded.canonical import canonical_bytes, sha256_hex
from gitgrounded.evidence.bundle import RECORD_FILES, leaves_from_files
from gitgrounded.evidence.merkle import merkle_root
from gitgrounded.evidence.sign import certificate_identity, key_id

MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_FILES = 2000


@dataclass
class VerifyResult:
    status: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    signature: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"check": name, "ok": ok, "detail": detail})
        return ok

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_name(name: str) -> bool:
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts and "\\" not in name and not name.startswith("/")


def read_bundle(path: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > MAX_FILES:
            raise ValueError("bundle has too many entries")
        for info in infos:
            if info.is_dir():
                continue
            if not _safe_name(info.filename):
                raise ValueError(f"unsafe path in bundle: {info.filename}")
            if info.file_size > MAX_FILE_BYTES:
                raise ValueError(f"entry too large: {info.filename}")
            if info.filename in files:
                raise ValueError(f"duplicate entry: {info.filename}")
            files[info.filename] = z.read(info)
    return files


def verify_bundle(
    path: Path,
    identity: str | None = None,
    issuer: str = "https://token.actions.githubusercontent.com",
    public_key: str | None = None,
) -> VerifyResult:
    res = VerifyResult(status="TAMPERED")
    try:
        files = read_bundle(path)
    except (zipfile.BadZipFile, ValueError, OSError) as e:
        res.add("read", False, str(e))
        return res
    if "manifest.json" not in files:
        res.add("manifest", False, "manifest.json missing")
        return res
    try:
        manifest = json.loads(files["manifest.json"])
    except ValueError as e:
        res.add("manifest", False, f"manifest.json invalid: {e}")
        return res
    res.manifest = manifest
    ok = res.add(
        "manifest_canonical", canonical_bytes(manifest) == files["manifest.json"], "manifest.json is canonical JSON"
    )
    listed = manifest.get("files", {})
    for name, digest in sorted(listed.items()):
        data = files.get(name)
        if data is None:
            ok &= res.add(f"file:{name}", False, "listed in manifest but missing")
            continue
        actual = sha256_hex(data)
        ok &= res.add(
            f"file:{name}",
            actual == digest,
            "hash matches" if actual == digest else f"hash mismatch: expected {digest[:16]}, got {actual[:16]}",
        )
    unlisted = [n for n in files if n not in listed and n != "manifest.json" and not n.startswith("signature/")]
    ok &= res.add(
        "no_unlisted_files", not unlisted, f"unlisted files: {unlisted}" if unlisted else "all files are listed"
    )
    root = merkle_root(leaves_from_files(files))
    ok &= res.add("merkle_root", root == manifest.get("merkle_root"), f"recomputed {root[:16]}")
    if "merkle.json" in files:
        try:
            mj = json.loads(files["merkle.json"])
            consistent = mj.get("root") == root and mj.get("files") == RECORD_FILES
            ok &= res.add(
                "merkle_json",
                consistent,
                "merkle.json consistent" if consistent else "merkle.json does not match the records",
            )
        except ValueError:
            ok &= res.add("merkle_json", False, "merkle.json invalid")
    if "summary.json" in files:
        ok &= res.add("summary", sha256_hex(files["summary.json"]) == manifest.get("summary_sha256"), "summary hash")
    nested_sig_bad = False
    for name in sorted(n for n in files if n.endswith(".ggb") and n in listed):
        with tempfile.TemporaryDirectory() as td:
            nested = Path(td) / "nested.ggb"
            nested.write_bytes(files[name])
            sub = verify_bundle(nested, public_key=public_key)
        ok &= res.add(f"nested:{name}", sub.status != "TAMPERED", sub.status)
        nested_sig_bad |= sub.status == "SIGNATURE_INVALID"
    sig_ok, sig_level = _verify_signature(files, res, identity, issuer, public_key)
    if nested_sig_bad:
        sig_ok = False
    if not ok:
        res.status = "TAMPERED"
    elif sig_ok is False:
        res.status = "SIGNATURE_INVALID"
    elif sig_level == "ci":
        res.status = "VERIFIED"
    elif sig_level == "ci_unchecked_identity":
        res.status = "VERIFIED_INTEGRITY_SIGNATURE_PRESENT"
    elif sig_level == "independent":
        res.status = "VERIFIED_INDEPENDENT"
    elif sig_level == "self":
        res.status = "VERIFIED_SELF_SIGNED"
    else:
        res.status = "VERIFIED_UNSIGNED"
    return res


def _verify_signature(
    files: dict[str, bytes], res: VerifyResult, identity: str | None, issuer: str, public_key: str | None
) -> tuple[bool | None, str]:
    payload = files["manifest.json"]
    if "signature/local.json" in files:
        try:
            doc = json.loads(files["signature/local.json"])
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            pub = base64.b64decode(doc["public_key"])
            Ed25519PublicKey.from_public_bytes(pub).verify(base64.b64decode(doc["signature"]), payload)
            kid = key_id(pub)
            scope = doc.get("scope", "self_signed")
            res.signature = {"type": "ed25519", "key_id": kid, "scope": scope, "issuer": doc.get("issuer")}
            if public_key:
                expected = public_key.strip()
                match = expected in (kid, doc["public_key"])
                res.add(
                    "signature", match, f"ed25519 key {kid} {'matches' if match else 'does not match'} expected key"
                )
                return match, "independent" if scope == "independent" else "self"
            res.add("signature", True, f"valid ed25519 signature by key {kid} (self signed, pass --public-key to pin)")
            return True, "self"
        except ImportError:
            res.add("signature", False, "install cryptography to verify ed25519 signatures")
            return None, "none"
        except Exception as e:
            res.add("signature", False, f"invalid ed25519 signature: {type(e).__name__}")
            return False, "self"
    if "signature/manifest.sigstore.json" in files:
        bundle_bytes = files["signature/manifest.sigstore.json"]
        try:
            info = certificate_identity(json.loads(bundle_bytes))
        except ValueError:
            info = {}
        res.signature = {"type": "sigstore", **info}
        if not identity:
            res.add(
                "signature",
                True,
                f"sigstore bundle present for {info.get('san', 'unknown identity')}; pass --identity to verify cryptographically",
            )
            return None, "ci_unchecked_identity"
        with tempfile.TemporaryDirectory() as td:
            m = Path(td) / "manifest.json"
            b = Path(td) / "manifest.sigstore.json"
            m.write_bytes(payload)
            b.write_bytes(bundle_bytes)
            cmd = [
                sys.executable,
                "-m",
                "sigstore",
                "verify",
                "identity",
                "--bundle",
                str(b),
                "--cert-identity",
                identity,
                "--cert-oidc-issuer",
                issuer,
                str(m),
            ]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
            except FileNotFoundError:
                res.add("signature", False, "sigstore is not installed")
                return None, "none"
            ok = r.returncode == 0
            res.add(
                "signature",
                ok,
                "sigstore signature verified for " + identity
                if ok
                else (r.stderr.strip()[-500:] or "sigstore verification failed"),
            )
            return ok, "ci"
    res.add("signature", True, "bundle is unsigned")
    return None, "none"
