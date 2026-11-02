"""Decode one complete model JSON object without choosing among conflicting outputs.

Only non-semantic wrappers may be removed. Broken/truncated objects are never
searched recursively for a convenient valid child, and duplicate keys fail closed.
"""
from __future__ import annotations
import hashlib
import json
import logging
import math
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)
_MAX_RESPONSE_CHARS = 1_000_000


class ModelJsonError(ValueError):
    def __init__(self, code: str, *, offset: int | None = None):
        self.code = code
        self.offset = offset
        super().__init__(f"Model JSON rejected: {code}" + (f" at offset {offset}" if offset is not None else ""))


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelJsonError("duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ModelJsonError("non_finite_number")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ModelJsonError("non_finite_number")
    return result


def parse_model_json_object(content: str) -> dict[str, Any]:
    if not isinstance(content, str) or not content.strip():
        raise ModelJsonError("empty_response")
    if len(content) > _MAX_RESPONSE_CHARS:
        raise ModelJsonError("response_too_large")
    candidate = content.lstrip("\ufeff").strip()
    opening = re.search(r"[\[{]", candidate)
    if opening is None:
        raise ModelJsonError("missing_object")
    start = opening.start()
    if start > 4096:
        raise ModelJsonError("prefix_too_large")
    if candidate[start] != "{":
        raise ModelJsonError("root_not_object", offset=start)
    decoder = json.JSONDecoder(object_pairs_hook=_unique_keys, parse_constant=_reject_constant, parse_float=_finite_float)
    try:
        payload, end = decoder.raw_decode(candidate, start)
    except json.JSONDecodeError as exc:
        raise ModelJsonError("invalid_or_truncated_json", offset=exc.pos) from None
    except (RecursionError, OverflowError):
        raise ModelJsonError("invalid_json_complexity") from None
    except ModelJsonError:
        raise
    except ValueError:
        raise ModelJsonError("invalid_json_value") from None
    if not isinstance(payload, dict):
        raise ModelJsonError("root_not_object", offset=start)
    suffix = candidate[end:].strip()
    suffix = re.sub(r"```(?:json)?", "", suffix, flags=re.I).strip()
    recovery = []
    if "{" in suffix or "[" in suffix:
        raise ModelJsonError("multiple_or_conflicting_objects", offset=end)
    if suffix:
        # A complete object plus at most two redundant matching closers is
        # unambiguous. Do not remove braces from inside the JSON itself.
        if re.fullmatch(r"\}{1,2}", suffix):
            recovery.append("redundant_root_closer")
        elif any(symbol in suffix for symbol in ('}', ']', '"', ':', '`')) or len(suffix) > 512:
            raise ModelJsonError("invalid_trailing_structure", offset=end)
        else:
            recovery.append("trailing_prose")
    if start:
        recovery.append("leading_wrapper")
    if recovery:
        # Only shape and a digest are logged; never log model text or credentials.
        _LOGGER.warning("model_json_wrapper_recovered codes=%s response_chars=%d response_sha256=%s",
                        ",".join(recovery), len(content), hashlib.sha256(content.encode()).hexdigest())
    return payload
