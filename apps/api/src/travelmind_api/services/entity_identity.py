import re
from functools import lru_cache
from opencc import OpenCC

_converter = OpenCC("t2s")


@lru_cache(maxsize=4096)
def normalize_identity(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", _converter.convert(str(value or "")).casefold())


def entity_matches(name: str, text: str) -> bool:
    key, source = normalize_identity(name), normalize_identity(text)
    return bool(key and len(key) >= 2 and key in source)
