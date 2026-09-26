import gitgrounded.cache as cache


def test_set_then_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path / ".cache"))
    cache.set("ns", {"a": 1}, "key-part-1", "key-part-2")
    result = cache.get("ns", "key-part-1", "key-part-2")
    assert result == {"a": 1}


def test_get_missing_key_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path / ".cache"))
    assert cache.get("ns", "does-not-exist") is None


def test_different_parts_produce_different_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path / ".cache"))
    cache.set("ns", {"v": "one"}, "diff-a")
    cache.set("ns", {"v": "two"}, "diff-b")
    assert cache.get("ns", "diff-a") == {"v": "one"}
    assert cache.get("ns", "diff-b") == {"v": "two"}