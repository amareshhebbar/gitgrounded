import json

from gitgrounded.assertions.builtin import run_assertions
from gitgrounded.cases.model import Case
from gitgrounded.jsonpath import jsonpath_get, jsonpath_get_all
from gitgrounded.targets.base import ToolCall, Transcript


def tr(output, **kw):
    raw = output if isinstance(output, str) else json.dumps(output)
    return Transcript(case_id="c", variant="v", trial=0, request={}, raw_output=raw, output=output, **kw)


CASE = Case(id="c", input="hi")


def results(specs, t):
    return {r.type: r.passed for r in run_assertions(specs, t, CASE)}


def test_json_checks():
    t = tr({"category": "billing", "priority": "urgent", "items": [{"n": 1}]})
    r = results(
        [
            {"type": "json_valid"},
            {"type": "one_of", "path": "$.category", "values": ["billing"]},
            {"type": "jsonpath_equals", "path": "$.items[0].n", "value": 1},
            {
                "type": "json_schema",
                "schema": {"type": "object", "properties": {"priority": {"enum": ["low", "high"]}}},
            },
        ],
        t,
    )
    assert r == {"json_valid": True, "one_of": True, "jsonpath_equals": True, "json_schema": False}


def test_text_checks():
    t = tr("Sorry, I can't help with that request.")
    r = results(
        [
            {"type": "refusal"},
            {"type": "contains", "value": "help"},
            {"type": "not_contains", "value": "password"},
            {"type": "max_length", "value": 10, "unit": "words"},
            {"type": "regex", "pattern": "^Sorry"},
        ],
        t,
    )
    assert all(r.values())


def test_tool_checks():
    t = tr("done", tool_calls=[ToolCall("search"), ToolCall("order")])
    r = results(
        [
            {"type": "tool_called", "tool": "order"},
            {"type": "tool_not_called", "tool": "refund"},
            {"type": "tool_call_order", "tools": ["search", "order"]},
            {"type": "max_steps", "value": 1},
        ],
        t,
    )
    assert r == {"tool_called": True, "tool_not_called": True, "tool_call_order": True, "max_steps": False}


def test_error_transcript_fails():
    t = tr("", error="boom")
    out = run_assertions([{"type": "json_valid"}], t, CASE)
    assert len(out) == 1 and not out[0].passed


def test_unknown_assertion():
    out = run_assertions([{"type": "nope"}], tr("x"), CASE)
    assert not out[0].passed


def test_jsonpath():
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    assert jsonpath_get(data, "$.a.b[1].c") == 2
    assert jsonpath_get_all(data, "$.a.b[*].c") == [1, 2]
    assert jsonpath_get(data, "a.b[0].c") == 1
