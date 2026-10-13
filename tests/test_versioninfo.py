from gitgrounded.cli import versioninfo
from gitgrounded.cli.main import main


def test_render_states():
    assert "update: pip install --upgrade gitgrounded" in versioninfo.render("0.2.0", "0.3.0")
    assert "up to date" in versioninfo.render("0.3.0", "0.3.0")
    assert "skipped update check" in versioninfo.render("0.3.0", None)
    assert versioninfo.REPO_URL in versioninfo.render("0.3.0", None)


def test_flags_print_version(monkeypatch, capsys):
    monkeypatch.setattr(versioninfo, "latest_release", lambda timeout=3.0: None)
    for flag in ("--version", "-v", "-V"):
        try:
            main([flag])
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out
        assert out.startswith("gitgrounded ")
        assert "happy fixing" in out
