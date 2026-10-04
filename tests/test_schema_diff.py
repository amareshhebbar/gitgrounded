from gitgrounded.mcp.schema_diff import diff_tools

BASE = [
    {
        "name": "search",
        "description": "Search the product catalog by keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "limit": {"type": "integer"},
                "sort": {"type": "string", "enum": ["price", "rating"]},
            },
            "required": ["q"],
        },
    },
    {
        "name": "order",
        "description": "Place an order for a product id.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
]


def kinds(out):
    return {(c["level"], c["kind"]) for c in out["changes"]}


def test_identical_is_none():
    assert diff_tools(BASE, BASE)["summary"]["semver"] == "none"


def test_breaking_changes():
    new = [dict(BASE[0]), dict(BASE[1])]
    new[0] = {
        **BASE[0],
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "sort": {"type": "string", "enum": ["price"]},
                "region": {"type": "string"},
            },
            "required": ["q", "region"],
        },
    }
    out = diff_tools(BASE, new)
    k = kinds(out)
    assert ("breaking", "param_removed") in k
    assert ("breaking", "enum_value_removed") in k
    assert ("breaking", "required_param_added") in k
    assert out["summary"]["semver"] == "major"


def test_description_change_is_risky():
    new = [{**BASE[0], "description": "Look things up."}, BASE[1]]
    out = diff_tools(BASE, new)
    assert ("risky", "description_changed") in kinds(out)
    assert out["summary"]["semver"] == "minor"


def test_optional_param_is_safe_minor():
    new = [
        {
            **BASE[0],
            "inputSchema": {
                **BASE[0]["inputSchema"],
                "properties": {**BASE[0]["inputSchema"]["properties"], "page": {"type": "integer"}},
            },
        },
        BASE[1],
    ]
    out = diff_tools(BASE, new)
    assert ("safe", "optional_param_added") in kinds(out)
    assert out["summary"]["semver"] == "minor"


def test_rename_detected():
    new = [BASE[0], {**BASE[1], "name": "place_order"}]
    assert ("breaking", "tool_renamed") in kinds(diff_tools(BASE, new))
