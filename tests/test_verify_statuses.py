import base64
import io
import json
import zipfile
from pathlib import Path

import pytest

from gitgrounded.canonical import canonical_bytes, sha256_hex
from gitgrounded.evidence.bundle import RECORD_FILES, _zip_bytes, leaves_from_files
from gitgrounded.evidence.merkle import merkle_root
from gitgrounded.evidence.sign import LocalSigner
from gitgrounded.evidence.verify import MAX_FILES, read_bundle, verify_bundle

RECORDS = {
    "records/cases.jsonl": b'{"case_id":"a"}\n{"case_id":"b"}\n',
    "records/transcripts.jsonl": b'{"case_id":"a","text":"hi"}\n',
    "records/judgements.jsonl": b"",
    "records/assertions.jsonl": b'{"case_id":"a","ok":true}\n',
}


def make_files(signer=None, extra=None):
    files = dict(RECORDS)
    root = merkle_root(leaves_from_files(files))
    summary = canonical_bytes({"verdict": "PASS"})
    files["summary.json"] = summary
    files["merkle.json"] = canonical_bytes({"algorithm": "sha256", "files": RECORD_FILES, "root": root})
    for name, data in (extra or {}).items():
        files[name] = data
    manifest = {
        "verdict": "PASS",
        "merkle_root": root,
        "summary_sha256": sha256_hex(summary),
        "files": {n: sha256_hex(d) for n, d in sorted(files.items())},
    }
    manifest_bytes = canonical_bytes(manifest)
    files["manifest.json"] = manifest_bytes
    if signer is not None:
        sig_files, _ = signer.sign(manifest_bytes)
        files.update(sig_files)
    return files


def write(tmp_path, files, name="b.ggb"):
    p = tmp_path / name
    p.write_bytes(_zip_bytes(files))
    return p


@pytest.fixture
def signer(tmp_path):
    return LocalSigner(key_path=tmp_path / "key.pem")


def failed(res):
    return [c["check"] for c in res.checks if not c["ok"]]


def test_unsigned(tmp_path):
    res = verify_bundle(write(tmp_path, make_files()))
    assert res.status == "VERIFIED_UNSIGNED"
    assert not failed(res)


def test_self_signed(tmp_path, signer):
    res = verify_bundle(write(tmp_path, make_files(signer)))
    assert res.status == "VERIFIED_SELF_SIGNED"
    assert res.signature["type"] == "ed25519"


def test_independent_scope_requires_pinned_key(tmp_path):
    s = LocalSigner(key_path=tmp_path / "k.pem", scope="independent", issuer="svc")
    p = write(tmp_path, make_files(s))
    assert verify_bundle(p).status == "VERIFIED_SELF_SIGNED"
    assert verify_bundle(p, public_key=s.public_key()["key_id"]).status == "VERIFIED_INDEPENDENT"


def test_pinned_key_matches(tmp_path, signer):
    p = write(tmp_path, make_files(signer))
    pub = signer.public_key()["public_key"]
    assert verify_bundle(p, public_key=pub).status.startswith("VERIFIED")
    assert verify_bundle(p, public_key=signer.public_key()["key_id"]).status.startswith("VERIFIED")


def test_pinned_wrong_key(tmp_path, signer):
    p = write(tmp_path, make_files(signer))
    other = LocalSigner(key_path=tmp_path / "other.pem").public_key()["public_key"]
    assert verify_bundle(p, public_key=other).status == "SIGNATURE_INVALID"


def test_signature_bytes_edited(tmp_path, signer):
    files = make_files(signer)
    doc = json.loads(files["signature/local.json"])
    sig = bytearray(base64.b64decode(doc["signature"]))
    sig[0] ^= 1
    doc["signature"] = base64.b64encode(bytes(sig)).decode()
    files["signature/local.json"] = json.dumps(doc).encode()
    assert verify_bundle(write(tmp_path, files)).status == "SIGNATURE_INVALID"


def test_signature_swapped_to_other_key(tmp_path, signer):
    files = make_files(signer)
    other = LocalSigner(key_path=tmp_path / "other.pem")
    sig_files, _ = other.sign(b"different payload")
    files.update(sig_files)
    assert verify_bundle(write(tmp_path, files)).status == "SIGNATURE_INVALID"


def test_missing_listed_file(tmp_path):
    files = make_files()
    del files["records/cases.jsonl"]
    res = verify_bundle(write(tmp_path, files))
    assert res.status == "TAMPERED"
    assert "file:records/cases.jsonl" in failed(res)


def test_extra_unlisted_file(tmp_path):
    files = make_files()
    files["evil.txt"] = b"x"
    res = verify_bundle(write(tmp_path, files))
    assert res.status == "TAMPERED"
    assert "no_unlisted_files" in failed(res)


def test_renamed_file(tmp_path):
    files = make_files()
    files["records/renamed.jsonl"] = files.pop("records/cases.jsonl")
    assert verify_bundle(write(tmp_path, files)).status == "TAMPERED"


def test_record_edit_breaks_hash_and_merkle(tmp_path):
    files = make_files()
    files["records/cases.jsonl"] = b'{"case_id":"a"}\n{"case_id":"z"}\n'
    res = verify_bundle(write(tmp_path, files))
    assert res.status == "TAMPERED"
    assert "merkle_root" in failed(res)
    assert "file:records/cases.jsonl" in failed(res)


def test_edit_with_rehash_still_caught_by_signature(tmp_path, signer):
    files = make_files(signer)
    files["records/cases.jsonl"] = b'{"case_id":"a"}\n{"case_id":"z"}\n'
    manifest = json.loads(files["manifest.json"])
    manifest["files"]["records/cases.jsonl"] = sha256_hex(files["records/cases.jsonl"])
    manifest["merkle_root"] = merkle_root(leaves_from_files(files))
    files["manifest.json"] = canonical_bytes(manifest)
    mj = json.loads(files["merkle.json"])
    mj["root"] = manifest["merkle_root"]
    files["merkle.json"] = canonical_bytes(mj)
    manifest["files"]["merkle.json"] = sha256_hex(files["merkle.json"])
    files["manifest.json"] = canonical_bytes(manifest)
    res = verify_bundle(write(tmp_path, files))
    assert res.status == "SIGNATURE_INVALID"


def test_manifest_not_canonical(tmp_path):
    files = make_files()
    files["manifest.json"] = json.dumps(json.loads(files["manifest.json"]), indent=2).encode()
    res = verify_bundle(write(tmp_path, files))
    assert res.status == "TAMPERED"
    assert "manifest_canonical" in failed(res)


def test_manifest_missing(tmp_path):
    files = make_files()
    del files["manifest.json"]
    assert verify_bundle(write(tmp_path, files)).status == "TAMPERED"


def test_manifest_invalid_json(tmp_path):
    files = make_files()
    files["manifest.json"] = b"{not json"
    assert verify_bundle(write(tmp_path, files)).status == "TAMPERED"


def test_not_a_zip(tmp_path):
    p = tmp_path / "x.ggb"
    p.write_bytes(b"not a zip at all")
    assert verify_bundle(p).status == "TAMPERED"


def test_missing_file(tmp_path):
    assert verify_bundle(tmp_path / "nope.ggb").status == "TAMPERED"


def test_merkle_json_mismatch(tmp_path):
    files = make_files()
    files["merkle.json"] = canonical_bytes({"root": "00", "files": RECORD_FILES})
    res = verify_bundle(write(tmp_path, files))
    assert res.status == "TAMPERED"


def test_zip_slip_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.txt", b"x")
        z.writestr("manifest.json", b"{}")
    p = tmp_path / "slip.ggb"
    p.write_bytes(buf.getvalue())
    with pytest.raises(ValueError):
        read_bundle(p)
    assert verify_bundle(p).status == "TAMPERED"


@pytest.mark.parametrize("name", ["/abs.txt", "a\\b.txt", "x/../../y"])
def test_unsafe_names(tmp_path, name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, b"x")
    p = tmp_path / "u.ggb"
    p.write_bytes(buf.getvalue())
    assert verify_bundle(p).status == "TAMPERED"


def test_too_many_entries(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(MAX_FILES + 1):
            z.writestr(f"f{i}.txt", b"")
    p = tmp_path / "many.ggb"
    p.write_bytes(buf.getvalue())
    assert verify_bundle(p).status == "TAMPERED"


def test_oversized_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("gitgrounded.evidence.verify.MAX_FILE_BYTES", 10)
    files = make_files()
    assert verify_bundle(write(tmp_path, files)).status == "TAMPERED"


def test_duplicate_entries(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", b"{}")
        with pytest.warns(UserWarning):
            z.writestr("manifest.json", b"{}")
    p = tmp_path / "dup.ggb"
    p.write_bytes(buf.getvalue())
    assert verify_bundle(p).status == "TAMPERED"


def test_nested_bundle_ok(tmp_path, signer):
    inner = _zip_bytes(make_files(signer))
    files = make_files(extra={"pair/inner.ggb": inner})
    res = verify_bundle(write(tmp_path, files))
    assert res.status.startswith("VERIFIED")
    assert any(c["check"] == "nested:pair/inner.ggb" and c["ok"] for c in res.checks)


def test_nested_bundle_tampered(tmp_path):
    inner_files = make_files()
    inner_files["records/cases.jsonl"] = b"changed\n"
    inner = _zip_bytes(inner_files)
    files = make_files(extra={"pair/inner.ggb": inner})
    assert verify_bundle(write(tmp_path, files)).status == "TAMPERED"


def test_nested_bundle_bad_signature(tmp_path, signer):
    inner_files = make_files(signer)
    doc = json.loads(inner_files["signature/local.json"])
    sig = bytearray(base64.b64decode(doc["signature"]))
    sig[0] ^= 1
    doc["signature"] = base64.b64encode(bytes(sig)).decode()
    inner_files["signature/local.json"] = json.dumps(doc).encode()
    files = make_files(extra={"pair/inner.ggb": _zip_bytes(inner_files)})
    assert verify_bundle(write(tmp_path, files)).status == "SIGNATURE_INVALID"


def test_sigstore_present_without_identity(tmp_path):
    files = make_files()
    files["signature/manifest.sigstore.json"] = b"{}"
    res = verify_bundle(write(tmp_path, files))
    assert res.status == "VERIFIED_INTEGRITY_SIGNATURE_PRESENT"


def test_sigstore_identity_runs_subprocess(tmp_path, monkeypatch):
    files = make_files()
    files["signature/manifest.sigstore.json"] = b"{}"
    calls = {}

    class R:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        return R()

    monkeypatch.setattr("gitgrounded.evidence.verify.subprocess.run", fake_run)
    res = verify_bundle(write(tmp_path, files), identity="me@example.com")
    assert res.status == "VERIFIED"
    assert "--cert-identity" in calls["cmd"]
    R.returncode = 1
    R.stderr = "bad"
    assert verify_bundle(write(tmp_path, files), identity="me@example.com").status == "SIGNATURE_INVALID"


def test_to_dict(tmp_path):
    d = verify_bundle(write(tmp_path, make_files())).to_dict()
    assert d["status"] == "VERIFIED_UNSIGNED"
    assert isinstance(d["checks"], list)


def test_path_type_independent_of_cwd(tmp_path, monkeypatch):
    p = write(tmp_path, make_files())
    monkeypatch.chdir(Path("/"))
    assert verify_bundle(p).status == "VERIFIED_UNSIGNED"
