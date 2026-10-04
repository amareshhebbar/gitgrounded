import os

POLICY = {
    "refund": "Refunds up to 100 USD within 30 days of purchase.",
    "shipping": "Shipping delays over 7 days get a 10 USD credit.",
}
SYSTEM_PROMPT = (
    "You are a support agent. Always call lookup_policy before answering refund or shipping questions. "
    "Answer only from the policy text. Decline anything else."
)


def topic_of(text: str) -> str | None:
    t = text.lower()
    if any(w in t for w in ("refund", "money", "charge", "return")):
        return "refund"
    if any(w in t for w in ("ship", "late", "deliver", "package", "parcel")):
        return "shipping"
    return None


def lookup_policy(topic: str) -> str:
    """Return the support policy text for a topic: refund or shipping."""
    return POLICY.get(topic, "No policy for that topic.")


def answer_from(policy_text: str | None) -> str:
    if policy_text is None:
        return "I can only help with refunds and shipping."
    return f"Per our policy: {policy_text}"


def real_model() -> str | None:
    return os.environ.get("SUPPORT_MODEL") or None
