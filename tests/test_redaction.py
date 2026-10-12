import json

from gitgrounded.evidence.bundle import Redactor


def test_secret_headers_always_redacted():
    r = Redactor([])
    rec = {
        "request": {
            "headers": {
                "Authorization": "Bearer sk-live-123",
                "X-Api-Key": "k-456",
                "Cookie": "s=1",
                "Content-Type": "application/json",
            }
        }
    }
    out = r.apply(rec)
    blob = json.dumps(out)
    assert "sk-live-123" not in blob
    assert "k-456" not in blob
    assert "s=1" not in blob
    assert out["request"]["headers"]["Content-Type"] == "application/json"
    assert r.count == 3


def test_redacted_value_is_hmac_token_not_reversible_by_guessing():
    a = Redactor([]).apply({"request": {"headers": {"authorization": "x"}}})
    b = Redactor([]).apply({"request": {"headers": {"authorization": "x"}}})
    assert a["request"]["headers"]["authorization"].startswith("redacted:hmac-sha256:")
    assert a["request"]["headers"]["authorization"] != b["request"]["headers"]["authorization"]


def test_same_value_same_token_within_run():
    r = Redactor([])
    assert r.token("abc") == r.token("abc")
    assert r.token("abc") != r.token("abd")


def test_configured_path_redacted():
    r = Redactor(["$.response.user.email"])
    out = r.apply({"response": {"user": {"email": "a@b.com", "name": "n"}}})
    assert "a@b.com" not in json.dumps(out)
    assert out["response"]["user"]["name"] == "n"


def test_missing_path_is_noop():
    r = Redactor(["$.nope.here"])
    rec = {"a": 1}
    assert r.apply(rec) == rec
    assert r.count == 0


def test_original_record_not_mutated():
    r = Redactor([])
    rec = {"request": {"headers": {"Authorization": "secret"}}}
    r.apply(rec)
    assert rec["request"]["headers"]["Authorization"] == "secret"
