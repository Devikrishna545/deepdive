"""Compact output-shape hints for LLM prompts.

A full `model_json_schema()` dump costs 150-600 prompt tokens per call. This renders the
same contract as one short line, e.g. for VerdictOut:

    {"label":"SUPPORTED|PARTIAL|UNSUPPORTED|CONTRADICTED","reason":str,"evidence_quote":str,"narrowed_claim":str|null}

Pydantic still validates the reply strictly, so nothing is lost by the shorter hint.
"""

from __future__ import annotations

import types
import typing
from enum import Enum
from functools import lru_cache

from pydantic import BaseModel


def _render(tp) -> str:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin in (typing.Union, types.UnionType):
        return "|".join(_render(a) for a in args)
    if origin is typing.Literal:
        return '"' + "|".join(str(a) for a in args) + '"'
    if origin in (list, tuple, set):
        return f"[{_render(args[0]) if args else 'any'}]"
    if origin is dict:
        return "{str:" + (_render(args[1]) if len(args) == 2 else "any") + "}"
    if tp is type(None):
        return "null"
    if isinstance(tp, type) and issubclass(tp, Enum):
        return '"' + "|".join(str(m.value) for m in tp) + '"'
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return _shape(tp)
    return getattr(tp, "__name__", str(tp))


def _shape(model: type[BaseModel]) -> str:
    hints = typing.get_type_hints(model)
    parts = [f'"{name}":{_render(hints[name])}' for name in model.model_fields]
    return "{" + ",".join(parts) + "}"


@lru_cache
def schema_hint(model: type[BaseModel]) -> str:
    return _shape(model)
