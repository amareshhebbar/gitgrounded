import asyncio
import inspect
import json
import uuid
from typing import Any

KINDS = [
    "langgraph",
    "langchain",
    "strands",
    "crewai",
    "openai_agents",
    "pydantic_ai",
    "llamaindex",
    "autogen",
    "smolagents",
    "haystack",
    "dspy",
    "generic",
]


def _await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return asyncio.run(_wrap(value))
    return value


async def _wrap(aw):
    return await aw


def _messages(case_input: Any) -> list[dict[str, str]]:
    if isinstance(case_input, str):
        return [{"role": "user", "content": case_input}]
    return [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in case_input]


def _last_user(case_input: Any) -> str:
    if isinstance(case_input, str):
        return case_input
    users = [m.get("content", "") for m in case_input if m.get("role", "user") == "user"]
    return users[-1] if users else ""


def _transcript_text(case_input: Any) -> str:
    if isinstance(case_input, str):
        return case_input
    return "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in case_input)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, dict) and isinstance(c.get("text"), str):
                parts.append(c["text"])
        return "\n".join(parts)
    return "" if content is None else str(content)


def _render(template: Any, text: str) -> Any:
    if isinstance(template, str):
        return text if template == "{{input}}" else template.replace("{{input}}", text)
    if isinstance(template, dict):
        return {k: _render(v, text) for k, v in template.items()}
    if isinstance(template, list):
        return [_render(v, text) for v in template]
    return template


def _path(data: Any, path: str | None) -> Any:
    if not path:
        return data
    for part in path.split("."):
        data = _get(data, part)
    return data


def detect(obj: Any) -> str:
    mod = (type(obj).__module__ or "").lower()
    name = type(obj).__name__.lower()
    for key, kind in (
        ("langgraph", "langgraph"),
        ("strands", "strands"),
        ("crewai", "crewai"),
        ("pydantic_ai", "pydantic_ai"),
        ("llama_index", "llamaindex"),
        ("autogen", "autogen"),
        ("smolagents", "smolagents"),
        ("haystack", "haystack"),
        ("dspy", "dspy"),
        ("langchain", "langchain"),
    ):
        if key in mod:
            return kind
    if mod.split(".")[0] == "agents" and name == "agent":
        return "openai_agents"
    return "generic"


def _out(
    output: Any,
    calls: list[dict[str, Any]] | None = None,
    usage: dict[str, int] | None = None,
    context: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(output, (str, dict, list)) and output is not None:
        output = str(output)
    return {"output": output, "tool_calls": calls or [], "usage": usage or {}, "context": context or []}


def _lc_messages_result(msgs: list[Any]) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    final = ""
    for m in msgs:
        mtype = (_get(m, "type") or _get(m, "role") or "").lower()
        for tc in _get(m, "tool_calls") or []:
            calls.append(
                {
                    "name": _get(tc, "name", ""),
                    "arguments": _get(tc, "args") or _get(tc, "arguments") or {},
                    "id": _get(tc, "id"),
                }
            )
        if mtype in ("tool", "toolmessage"):
            tid = _get(m, "tool_call_id")
            for c in calls:
                if c.get("id") == tid and c.get("result") is None:
                    c["result"] = _content_text(_get(m, "content"))
        if mtype in ("ai", "assistant", "aimessage") and _content_text(_get(m, "content")).strip():
            final = _content_text(_get(m, "content"))
    usage: dict[str, int] = {}
    for m in msgs:
        u = _get(m, "usage_metadata") or {}
        usage["input_tokens"] = usage.get("input_tokens", 0) + int(_get(u, "input_tokens", 0) or 0)
        usage["output_tokens"] = usage.get("output_tokens", 0) + int(_get(u, "output_tokens", 0) or 0)
    return _out(final, [{k: v for k, v in c.items() if k != "id"} for c in calls], usage)


def run_langgraph(obj, case_input, options):
    payload = {options.get("messages_key", "messages"): _messages(case_input)}
    payload.update(options.get("extra_input", {}))
    config = {"configurable": {"thread_id": uuid.uuid4().hex}}
    res = _await(obj.ainvoke(payload, config=config)) if options.get("async") else obj.invoke(payload, config=config)
    msgs = _get(res, options.get("messages_key", "messages"))
    if isinstance(msgs, list):
        return _lc_messages_result(msgs)
    return _out(_path(res, options.get("output")))


def run_langchain(obj, case_input, options):
    inp = _render(options["input"], _last_user(case_input)) if "input" in options else _messages(case_input)
    res = obj.invoke(inp)
    if isinstance(res, dict) and isinstance(res.get("messages"), list):
        return _lc_messages_result(res["messages"])
    if options.get("output"):
        return _out(_path(res, options["output"]))
    if hasattr(res, "content"):
        r = _lc_messages_result([res])
        r["output"] = r["output"] or _content_text(res.content)
        return r
    if isinstance(res, dict) and "output" in res:
        return _out(res["output"])
    return _out(res)


def run_strands(obj, case_input, options):
    if hasattr(obj, "messages") and options.get("reset", True):
        try:
            obj.messages = []
        except Exception:
            pass
    res = None
    for m in _messages(case_input):
        if m["role"] == "user":
            res = obj(m["content"])
    calls = []
    for msg in getattr(obj, "messages", []) or []:
        for block in _get(msg, "content") or []:
            if isinstance(block, dict) and "toolUse" in block:
                tu = block["toolUse"]
                calls.append(
                    {"name": tu.get("name", ""), "arguments": tu.get("input") or {}, "id": tu.get("toolUseId")}
                )
            if isinstance(block, dict) and "toolResult" in block:
                tr = block["toolResult"]
                for c in calls:
                    if c.get("id") == tr.get("toolUseId"):
                        c["result"] = _content_text(tr.get("content"))
    usage = {}
    acc = _get(_get(res, "metrics"), "accumulated_usage") or {}
    if acc:
        usage = {
            "input_tokens": int(_get(acc, "inputTokens", 0) or 0),
            "output_tokens": int(_get(acc, "outputTokens", 0) or 0),
        }
    return _out(
        str(res).strip() if res is not None else "", [{k: v for k, v in c.items() if k != "id"} for c in calls], usage
    )


def run_crewai(obj, case_input, options):
    inputs = dict(options.get("inputs", {}))
    inputs[options.get("input_key", "input")] = _transcript_text(case_input)
    res = obj.kickoff(inputs=inputs)
    usage = {}
    tu = _get(res, "token_usage")
    if tu:
        usage = {
            "input_tokens": int(_get(tu, "prompt_tokens", 0) or 0),
            "output_tokens": int(_get(tu, "completion_tokens", 0) or 0),
        }
    return _out(_get(res, "raw") or str(res), usage=usage)


def run_openai_agents(obj, case_input, options):
    from agents import Runner

    inp = case_input if isinstance(case_input, str) else _messages(case_input)
    res = Runner.run_sync(obj, inp)
    calls = []
    for item in getattr(res, "new_items", []) or []:
        tname = type(item).__name__
        raw = getattr(item, "raw_item", None)
        if tname == "ToolCallItem":
            args = _get(raw, "arguments") or "{}"
            try:
                args = json.loads(args) if isinstance(args, str) else args
            except ValueError:
                args = {"raw": args}
            calls.append({"name": _get(raw, "name", ""), "arguments": args})
        elif tname == "ToolCallOutputItem" and calls:
            calls[-1]["result"] = _get(item, "output")
    return _out(
        res.final_output if isinstance(res.final_output, str) else json.dumps(res.final_output, default=str), calls
    )


def run_pydantic_ai(obj, case_input, options):
    res = obj.run_sync(_last_user(case_input))
    output = _get(res, "output", None)
    if output is None:
        output = _get(res, "data")
    calls = []
    try:
        for msg in res.all_messages():
            for part in _get(msg, "parts") or []:
                if _get(part, "part_kind") == "tool-call":
                    args = _get(part, "args") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            args = {"raw": args}
                    calls.append({"name": _get(part, "tool_name", ""), "arguments": args})
    except Exception:
        pass
    usage = {}
    try:
        u = res.usage()
        usage = {
            "input_tokens": int(_get(u, "input_tokens", 0) or _get(u, "request_tokens", 0) or 0),
            "output_tokens": int(_get(u, "output_tokens", 0) or _get(u, "response_tokens", 0) or 0),
        }
    except Exception:
        pass
    return _out(output if isinstance(output, str) else json.dumps(output, default=str), calls, usage)


def run_llamaindex(obj, case_input, options):
    text = _last_user(case_input)
    if hasattr(obj, "chat"):
        res = _await(obj.chat(text))
    elif hasattr(obj, "query"):
        res = _await(obj.query(text))
    else:
        res = _await(obj.run(user_msg=text))
    context = [str(_get(n, "text", "") or _get(_get(n, "node"), "text", "")) for n in (_get(res, "source_nodes") or [])]
    return _out(str(_get(res, "response", None) or res), context=[c for c in context if c])


def run_autogen(obj, case_input, options):
    res = _await(obj.run(task=_transcript_text(case_input)))
    msgs = _get(res, "messages") or []
    final = _content_text(_get(msgs[-1], "content")) if msgs else str(res)
    calls = []
    for m in msgs:
        content = _get(m, "content")
        if isinstance(content, list):
            for c in content:
                if _get(c, "name") and _get(c, "arguments") is not None:
                    args = _get(c, "arguments")
                    try:
                        args = json.loads(args) if isinstance(args, str) else args
                    except ValueError:
                        args = {"raw": args}
                    calls.append({"name": _get(c, "name"), "arguments": args})
    return _out(final, calls)


def run_smolagents(obj, case_input, options):
    return _out(
        obj.run(_transcript_text(case_input), reset=True)
        if "reset" in inspect.signature(obj.run).parameters
        else obj.run(_transcript_text(case_input))
    )


def run_haystack(obj, case_input, options):
    if "input" not in options:
        raise ValueError("haystack targets need options.input, for example {prompt_builder: {query: '{{input}}'}}")
    res = obj.run(_render(options["input"], _last_user(case_input)))
    out = _path(res, options.get("output"))
    if isinstance(out, list) and out:
        out = _get(out[0], "text") or _get(out[0], "content") or str(out[0])
    return _out(out)


def run_dspy(obj, case_input, options):
    field = options.get("input_field", "question")
    pred = obj(**{field: _last_user(case_input)})
    out_field = options.get("output_field")
    if out_field:
        return _out(_get(pred, out_field))
    store = getattr(pred, "_store", None) or (pred.toDict() if hasattr(pred, "toDict") else {})
    if isinstance(store, dict) and store:
        return _out(str(list(store.values())[-1]))
    return _out(str(pred))


def run_generic(obj, case_input, options):
    text = _last_user(case_input)
    inp = _render(options["input"], text) if "input" in options else text
    for method in options.get("methods", ["invoke", "run", "chat", "kickoff", "query"]):
        fn = getattr(obj, method, None)
        if callable(fn):
            res = _await(fn(inp))
            break
    else:
        if not callable(obj):
            raise TypeError(
                f"{type(obj).__name__} has no invoke, run, chat, kickoff or query method and is not callable"
            )
        res = _await(obj(inp))
    if isinstance(res, dict) and ("output" in res or "tool_calls" in res):
        return _out(res.get("output"), res.get("tool_calls"), res.get("usage"), res.get("context"))
    if hasattr(res, "content") and not isinstance(res, (str, dict)):
        return _lc_messages_result([res])
    return _out(_path(res, options.get("output")))


RUNNERS = {
    "langgraph": run_langgraph,
    "langchain": run_langchain,
    "strands": run_strands,
    "crewai": run_crewai,
    "openai_agents": run_openai_agents,
    "pydantic_ai": run_pydantic_ai,
    "llamaindex": run_llamaindex,
    "autogen": run_autogen,
    "smolagents": run_smolagents,
    "haystack": run_haystack,
    "dspy": run_dspy,
    "generic": run_generic,
}


def invoke(obj: Any, case_input: Any, kind: str = "auto", options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    kind = detect(obj) if kind in (None, "", "auto") else kind
    if kind not in RUNNERS:
        raise ValueError(f"unknown framework '{kind}', use one of: {', '.join(KINDS)}")
    out = RUNNERS[kind](obj, case_input, options)
    out["framework"] = kind
    return out
