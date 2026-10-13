import re
import shlex
from pathlib import Path

import pytest

from gitgrounded.cli.main import build_parser

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
FENCE = re.compile(r"```(?:bash|sh|shell)\n(.*?)```", re.S)


def commands():
    out = []
    for f in FILES:
        for block in FENCE.findall(f.read_text(encoding="utf-8")):
            joined = block.replace("\\\n", " ")
            for line in joined.splitlines():
                line = line.strip()
                if line.startswith("gitgrounded ") and "..." not in line and "<" not in line:
                    out.append((f.name, line))
    return out


CMDS = commands()


def test_docs_contain_commands():
    assert len(CMDS) > 10


@pytest.mark.parametrize("source,line", CMDS)
def test_documented_command_parses(source, line):
    try:
        argv = shlex.split(line.split("#")[0].split("|")[0].split("&&")[0])[1:]
    except ValueError:
        pytest.skip("not shell parseable")
    parser = build_parser()
    try:
        parser.parse_args(argv)
    except SystemExit as e:
        if e.code not in (0, None):
            pytest.fail(f"{source}: `{line}` does not parse")
