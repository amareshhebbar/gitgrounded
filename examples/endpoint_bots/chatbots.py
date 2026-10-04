import os
import re
from pathlib import Path

from flask import Flask, jsonify, request

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
CHATBOTS = ["ai-chatbot", "ai-chatbot2", "ai-chatbot3"]
MODEL = os.environ.get("BOT_MODEL", "openai/gpt-oss-120b")

app = Flask(__name__)


def offline() -> bool:
    return os.environ.get("GITGROUNDED_OFFLINE", "").lower() in ("1", "true", "yes")


def mock_answer(system: str, message: str) -> str:
    limit = re.search(r"under (\d+) words", system)
    words = f"You asked about {message}. Here is a helpful, complete answer based on our guidelines.".split()
    if limit:
        words = words[: int(limit.group(1))]
    return " ".join(words)


def live_answer(system: str, message: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": message}],
        temperature=0,
    )
    return resp.choices[0].message.content or ""


@app.route("/<name>", methods=["POST"])
def chat(name: str):
    if name not in CHATBOTS:
        return jsonify({"error": f"unknown chatbot '{name}'"}), 404
    message = (request.get_json(force=True) or {}).get("message", "")
    system = (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
    answer = mock_answer(system, message) if offline() else live_answer(system, message)
    return jsonify({"answer": answer})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765)
