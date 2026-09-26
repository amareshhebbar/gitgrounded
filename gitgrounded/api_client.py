import requests


def call_endpoint(url, message, timeout=60):
    resp = requests.post(url, json={"message": message}, timeout=timeout)
    resp.raise_for_status()
    raw_text = resp.text
    try:
        parsed = resp.json()
        valid_json = True
    except ValueError:
        parsed = None
        valid_json = False
    return {"raw": raw_text, "parsed": parsed, "valid_json": valid_json}