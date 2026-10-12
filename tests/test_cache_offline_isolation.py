from gitgrounded.store.cache import Cache


def test_offline_and_live_keys_differ(tmp_path, monkeypatch):
    cache = Cache(tmp_path)
    monkeypatch.setenv("GITGROUNDED_OFFLINE", "1")
    offline = cache.key("transcript", "x", 1)
    monkeypatch.delenv("GITGROUNDED_OFFLINE")
    monkeypatch.delenv("GITGROUNDED_MODE", raising=False)
    live = cache.key("transcript", "x", 1)
    assert offline != live
