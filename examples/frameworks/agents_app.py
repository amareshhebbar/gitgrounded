import re

POLICY = {"refund": "Refunds up to 100 USD within 30 days.", "shipping": "Shipping delays over 7 days get a credit."}


def _topic(text):
    t = text.lower()
    if "refund" in t or "money" in t or "charge" in t:
        return "refund"
    if "ship" in t or "late" in t or "deliver" in t or "package" in t:
        return "shipping"
    return None


class GraphLike:
    def invoke(self, payload, config=None):
        text = payload["messages"][-1]["content"]
        topic = _topic(text)
        msgs = [{"type": "human", "content": text}]
        if topic:
            msgs.append(
                {
                    "type": "ai",
                    "content": "",
                    "tool_calls": [{"name": "lookup_policy", "args": {"topic": topic}, "id": "c1"}],
                }
            )
            msgs.append({"type": "tool", "content": POLICY[topic], "tool_call_id": "c1"})
            msgs.append({"type": "ai", "content": f"Per policy: {POLICY[topic]}"})
        else:
            msgs.append({"type": "ai", "content": "I can only help with refunds and shipping."})
        return {"messages": msgs}


class StrandsLike:
    def __init__(self):
        self.messages = []

    def __call__(self, prompt):
        topic = _topic(prompt)
        self.messages.append({"role": "user", "content": [{"text": prompt}]})
        if topic:
            self.messages.append(
                {
                    "role": "assistant",
                    "content": [{"toolUse": {"toolUseId": "t1", "name": "lookup_policy", "input": {"topic": topic}}}],
                }
            )
            self.messages.append(
                {"role": "user", "content": [{"toolResult": {"toolUseId": "t1", "content": [{"text": POLICY[topic]}]}}]}
            )
            return f"{POLICY[topic]}"
        return "Sorry, I cannot help with that."


def build_strands():
    return StrandsLike()


def weak_bot(text):
    return re.sub(r"\s+", " ", f"Thanks for reaching out about: {text}. Someone will contact you.")
