import os
import sys

from flask import Flask, request, jsonify

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from gitgrounded.llm import call
from gitgrounded.config import load_yaml, get_mode

app = Flask(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

CHATBOTS = ["ai-chatbot", "ai-chatbot2", "ai-chatbot3"]


def load_prompt(name):
    path = os.path.join(PROMPTS_DIR, f"{name}.txt")
    with open(path) as f:
        return f.read()


def load_model_config():
    cfg = load_yaml(os.path.join(BASE_DIR, "config", "model.yaml"))
    return cfg[get_mode()]


def load_providers_config():
    return load_yaml(os.path.join(BASE_DIR, "config", "providers.yaml"))


@app.route("/<name>", methods=["POST"])
def chat(name):
    if name not in CHATBOTS:
        return jsonify({"error": f"unknown chatbot '{name}'"}), 404

    body = request.get_json(force=True)
    message = body.get("message", "")

    system = load_prompt(name)
    model_cfg = load_model_config()
    providers_cfg = load_providers_config()

    raw = call(
        provider=model_cfg["provider"],
        model=model_cfg["model"],
        system=system,
        user=message,
        json_mode=False,
        providers_config=providers_cfg,
    )

    return jsonify({"answer": raw})


if __name__ == "__main__":
    app.run(host="localhost", port=8765)