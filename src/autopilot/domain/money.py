"""Monetary/price types. No ``float`` for money or price — ever (mirrors
kospi-watcher ADR-008). ``DecimalNoFloat`` raises at validation time on a raw
``float`` so a lossy binary price can never enter the system.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):  # bool is an int subclass — reject explicitly
        raise ValueError("bool is not a valid monetary value")
    if isinstance(value, float):
        raise ValueError(
            "float is forbidden for monetary/price fields; pass a str, int, or Decimal"
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, str)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid Decimal literal: {value!r}") from exc
    raise ValueError(f"unsupported type for a Decimal field: {type(value).__name__}")


# A Decimal that refuses to be built from a float.
DecimalNoFloat = Annotated[Decimal, BeforeValidator(_to_decimal)]
