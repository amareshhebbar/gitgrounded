import json

import pytest

from gitgrounded.cli.main import main


def test_removed_flags():
    with pytest.raises(SystemExit) as e:
        main(["--old", "main", "--new", "feat"])
    assert "gitgrounded run --base" in str(e.value.code)
    with pytest.raises(SystemExit) as e:
        main(["--labels"])
    assert "history list" in str(e.value.code)


def run_cli(args):
    with pytest.raises(SystemExit) as e:
        main(args)
    return e.value.code


def test_init(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run_cli(["init"]) == 0
    assert (tmp_path / "gitgrounded.yml").exists()
    assert ".gitgrounded/cache/" in (tmp_path / ".gitignore").read_text()
    assert run_cli(["init"]) == 1


def test_schema(capsys):
    assert run_cli(["schema"]) == 0
    assert "properties" in json.loads(capsys.readouterr().out)


def test_run_cli_exit_codes(demo_repo):
    assert (
        run_cli(["run", "--base", "baseline", "--head", "test/safe-wording-tweak", "--format", "json", "--no-generate"])
        == 0
    )
    assert (
        run_cli(
            [
                "run",
                "--base",
                "baseline",
                "--head",
                "test/drop-citation-rule",
                "--format",
                "json",
                "--no-generate",
                "--bundle",
                "--sign",
                "local",
            ]
        )
        == 1
    )
    assert (
        run_cli(
            [
                "run",
                "--base",
                "baseline",
                "--head",
                "test/drop-citation-rule",
                "--format",
                "json",
                "--no-generate",
                "--fail-on",
                "never",
            ]
        )
        == 0
    )
    assert run_cli(["report", "--format", "markdown"]) == 0


def test_mcp_diff_files(tmp_path):
    old = tmp_path / "a.json"
    new = tmp_path / "b.json"
    old.write_text(
        json.dumps({"tools": [{"name": "t", "description": "d", "inputSchema": {"type": "object", "properties": {}}}]})
    )
    new.write_text(json.dumps({"tools": []}))
    assert run_cli(["mcp", "diff", "--old-file", str(old), "--new-file", str(new)]) == 1
