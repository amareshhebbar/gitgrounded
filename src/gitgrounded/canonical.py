import hashlib
import json
import math
from typing import Any

FLOAT_DIGITS = 6


def _normalize(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        rounded = round(value, FLOAT_DIGITS)
        if rounded == int(rounded) and abs(rounded) < 2**53:
            return int(rounded)
        return rounded
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if hasattr(value, "model_dump"):
        return _normalize(value.model_dump(mode="json"))
    return str(value)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def canonical_str(value: Any) -> str:
    return canonical_bytes(value).decode("utf-8")


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))
