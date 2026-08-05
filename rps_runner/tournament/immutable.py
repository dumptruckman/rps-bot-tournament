"""Deeply immutable JSON-compatible values."""

from __future__ import annotations

import math
from typing import Any


def _immutable(*args: object, **kwargs: object) -> None:
    raise TypeError("JSON value is immutable")


class FrozenJsonDict(dict):
    """A JSON object whose keys and nested values cannot be changed."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        source = dict(*args, **kwargs)
        if any(not isinstance(key, str) for key in source):
            raise TypeError("JSON object keys must be strings")
        dict.__init__(
            self,
            {key: freeze_json(item) for key, item in source.items()},
        )

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class FrozenJsonList(list):
    """A JSON array whose items and nested values cannot be changed."""

    def __init__(self, values: object = ()) -> None:
        list.__init__(self, (freeze_json(item) for item in values))

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable


def freeze_json(value: Any) -> Any:
    """Return a deeply immutable, JSON-serializable copy of ``value``."""

    if isinstance(value, FrozenJsonDict) or isinstance(value, FrozenJsonList):
        return value
    if isinstance(value, dict):
        return FrozenJsonDict(value)
    if isinstance(value, (list, tuple)):
        return FrozenJsonList(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    raise TypeError(f"Value is not JSON-compatible: {type(value).__name__}")


def thaw_json(value: Any) -> Any:
    """Return a detached mutable JSON-compatible copy of ``value``."""

    if isinstance(value, dict):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw_json(item) for item in value]
    return value
