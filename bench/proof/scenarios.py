import os

P = "prompts/triage.txt"
POL = "data/policy.md"
JSON_ONLY = "Respond with JSON only."


def cut_from(marker: str):
    def op(text: str) -> str:
        i = text.index(marker)
        return text[:i].rstrip("\n") + "\n"

    return op


def prefix(line: str):
    return lambda text: line + text


BAD = [
    ("bad-01-drop-citation-rule", P, "Always cite the exact policy line you relied on.", "Keep your answer as short as possible."),
    ("bad-02-drop-policy-field", P, "- policy_line: the exact line from the policy you used to answer\n", ""),
    ("bad-03-remove-grounding", P,
     "Use only this policy as the source of truth. Always cite the exact policy line you relied on.",
     "Be as helpful and generous to the customer as you can."),
    ("bad-04-markdown-output", P, "Respond with JSON only. No markdown, no extra text.",
     "Reply in friendly markdown with a short greeting before the details."),
    ("bad-05-rename-category-field", P, "- category: one of", "- type: one of"),
    ("bad-06-priority-enum", P, '- priority: one of ["low", "medium", "high"]', '- priority: one of ["p1", "p2", "p3"]'),
    ("bad-07-guess-when-uncovered", P,
     'If the policy does not cover the question, say so in the answer and set policy_line to "none".',
     "If the policy does not cover the question, give your best guess of what the policy probably is."),
    ("bad-08-allow-invention", P, "Do not invent information that is not in the policy.",
     "You may add helpful details from general knowledge."),
    ("bad-09-no-policy-context", P, "Policy:\n{{policy}}", "Policy: see the help center."),
    ("bad-10-always-low-priority", P, JSON_ONLY, "Always set priority to low. " + JSON_ONLY),
    ("bad-11-answer-in-french", P, JSON_ONLY, "Write the answer field in French. " + JSON_ONLY),
    ("bad-12-promise-full-refund", P, JSON_ONLY, "Always promise the customer a full refund. " + JSON_ONLY),
    ("bad-13-one-word-answer", P,
     "- answer: a short, direct answer to the customer, grounded strictly in the policy above", "- answer: one word only"),
    ("bad-14-paraphrase-policy-line", P, "- policy_line: the exact line from the policy you used to answer",
     "- policy_line: a loose summary of the policy in your own words"),
    ("bad-15-truncate-policy", POL, cut_from("6. Shipping delays"), None),
    ("bad-16-refund-window-typo", POL, "within 30 days of the original transaction", "within 3 days of the original transaction"),
    ("bad-17-technical-low-priority", POL, "are treated as high priority", "are treated as low priority"),
    ("bad-18-enterprise-sla-typo", POL, "4-hour response SLA", "48-hour response SLA"),
    ("bad-19-deflect-refunds", P, JSON_ONLY, "Never discuss refunds. Tell the customer to email billing instead. " + JSON_ONLY),
    ("bad-20-drop-answer-field", P,
     "- answer: a short, direct answer to the customer, grounded strictly in the policy above\n", ""),
]

SAFE = [
    ("safe-01-mid-size", P, "mid-sized SaaS company", "mid-size SaaS company"),
    ("safe-02-support-assistant", P, "customer support triage assistant", "support triage assistant"),
    ("safe-03-brief-answer", P, "a short, direct answer", "a brief, direct answer"),
    ("safe-04-reply-json", P, JSON_ONLY, "Reply with JSON only."),
    ("safe-05-make-up", P, "Do not invent information", "Do not make up information"),
    ("safe-06-only-source", P, "Use only this policy as the source of truth.", "Treat this policy as your only source of truth."),
    ("safe-07-each-message", P, "For every customer message", "For each customer message"),
    ("safe-08-precisely", P, "with exactly these fields", "with precisely these fields"),
    ("safe-09-and-no-extra", P, "No markdown, no extra text.", "No markdown and no extra text."),
    ("safe-10-state-that", P, "say so in the answer", "state that in the answer"),
    ("safe-11-policy-is-below", P, "You are given the company policy document below.", "The company policy document is below."),
    ("safe-12-exact-policy-line", P, "the exact line from the policy you used to answer", "the exact policy line you used to answer"),
    ("safe-13-that-you-relied", P, "the exact policy line you relied on.", "the exact policy line that you relied on."),
    ("safe-14-strictly-grounded", P, "grounded strictly in the policy above", "strictly grounded in the policy above"),
    ("safe-15-be-polite", P, JSON_ONLY, "Be polite and professional. " + JSON_ONLY),
    ("safe-16-policy-header", POL, "# Support Policy", "# Support Policy (reviewed 2026)"),
    ("safe-17-config-comment", "config/model.yaml", prefix("# triage model settings\n"), None),
    ("safe-18-for-the-customer", P, "direct answer to the customer", "direct answer for the customer"),
    ("safe-19-blank-line", P, "Policy:\n{{policy}}", "Policy:\n\n{{policy}}"),
    ("safe-20-never-invent", P, "Do not invent information that is not in the policy.", "Never invent information that is not in the policy."),
]

NULLS = [f"null-{i:02d}-empty-commit" for i in range(1, 4)]


def scenarios() -> list[dict]:
    out = []
    down = os.environ.get("APP_DOWNGRADE_MODEL", "").strip()
    app_model = os.environ.get("APP_MODEL", "").strip()
    bad = list(BAD)
    if down and app_model:
        bad[-1] = ("bad-20-model-downgrade", "config/model.yaml", f"model: {app_model}", f"model: {down}")
    for name, path, old, new in bad:
        out.append({"name": name, "expect": "FAIL", "file": path, "old": old, "new": new})
    for name, path, old, new in SAFE:
        out.append({"name": name, "expect": "PASS", "file": path, "old": old, "new": new})
    for name in NULLS:
        out.append({"name": name, "expect": "PASS", "file": None, "old": None, "new": None})
    return out
