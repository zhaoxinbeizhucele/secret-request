"""Non-secret request schema shared by relay and standalone client."""
import json
import re

FIELD_TYPES = {"text", "password", "textarea", "email", "url"}


def validate_agent(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 100 or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError("invalid agent label")
    return value.strip()


def validate_fields(fields):
    if fields is None:
        return None  # Legacy request: raw UTF-8, not JSON.
    if not isinstance(fields, list) or not 1 <= len(fields) <= 16:
        raise ValueError("invalid fields")
    result, ids = [], set()
    for field in fields:
        if not isinstance(field, dict) or set(field) - {"id", "label", "type", "required"}:
            raise ValueError("invalid field definition")
        key, label, kind = field.get("id"), field.get("label"), field.get("type")
        required = field.get("required", True)
        if (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key)
                or key in ids or key in {"__proto__", "constructor", "prototype"}
                or not isinstance(label, str) or not 1 <= len(label) <= 100 or not label.strip()
                or any(ord(c) < 32 for c in label) or not isinstance(kind, str) or kind not in FIELD_TYPES
                or type(required) is not bool):
            raise ValueError("invalid field definition")
        ids.add(key)
        result.append({"id": key, "label": label.strip(), "type": kind, "required": required})
    return result


def validate_values(secret, fields):
    """Validate after decryption, before starting any consumer. Preserve bytes."""
    if fields is None:
        return secret
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result
    value = json.loads(secret, object_pairs_hook=unique)
    if not isinstance(value, dict) or set(value) != {f["id"] for f in fields}:
        raise ValueError("invalid field values")
    for field in fields:
        item = value[field["id"]]
        if (not isinstance(item, str) or "\x00" in item or (field["required"] and not item)
                or (field["type"] != "textarea" and any(c in item for c in "\r\n"))):
            raise ValueError("invalid field values")
    return secret
