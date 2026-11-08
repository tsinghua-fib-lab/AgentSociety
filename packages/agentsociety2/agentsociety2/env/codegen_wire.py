"""Data-only wire format for generated-code workers; never unpickle worker data."""

from __future__ import annotations

import base64
import importlib.util
import json
import math
import sys
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction


def _numpy_module():
    # SDK hosts already loaded NumPy. Standalone workers defer its module body
    # until an array is decoded or generated code actually uses its namespace.
    module = sys.modules.get("numpy")
    if module is not None:
        return module
    spec = importlib.util.find_spec("numpy")
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError("NumPy is required for generated-code workers")
    spec.loader = importlib.util.LazyLoader(spec.loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["numpy"] = module
    spec.loader.exec_module(module)
    return module


np = _numpy_module()

MAX_MESSAGE_BYTES = 8 * 1024 * 1024


class Record:
    """Attribute view of typed response data; contains no parent model methods."""

    def __init__(self, fields):
        self._fields = fields

    def __getattr__(self, name):
        try:
            return self._fields[name]
        except KeyError:
            raise AttributeError(name) from None

    def model_dump(self):
        return decode(encode(self._fields))

    def __iter__(self):
        return iter(self._fields.items())

    def __repr__(self):
        return repr(self._fields)


def _charge(value, remaining, depth):
    remaining[0] -= 1
    if remaining[0] < 0 or depth > 64:
        raise ValueError("Worker value exceeds 65536 nodes or 64 nesting levels")
    if isinstance(value, (str, bytes)):
        remaining[1] -= len(value)
        if remaining[1] < 0:
            raise ValueError("Worker value exceeds 8 MiB of scalar data")


def encode(value):
    return _encode(value, [65536, MAX_MESSAGE_BYTES], 0)


def _encode(value, remaining, depth):
    _charge(value, remaining, depth)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"t": "float", "v": str(value)}
    if isinstance(value, complex):
        return {
            "t": "complex",
            "v": [
                _encode(value.real, remaining, depth + 1),
                _encode(value.imag, remaining, depth + 1),
            ],
        }
    if isinstance(value, Decimal):
        text = str(value)
        _charge(text, remaining, depth)
        return {"t": "decimal", "v": text}
    if isinstance(value, Fraction):
        return {"t": "fraction", "v": [value.numerator, value.denominator]}
    if isinstance(value, Record):
        return {"t": "record", "v": _encode(value._fields, remaining, depth + 1)}
    if isinstance(value, list):
        return [_encode(item, remaining, depth + 1) for item in value]
    if isinstance(value, dict):
        # Reserve "t" for typed values. Ordinary string-key mappings can stay
        # JSON objects; other mappings retain explicit key/value pairs.
        if "t" not in value and all(isinstance(key, str) for key in value):
            encoded = {}
            for key, item in value.items():
                _charge(key, remaining, depth + 1)
                encoded[key] = _encode(item, remaining, depth + 1)
            return encoded
        return {
            "t": "dict",
            "v": [
                [_encode(k, remaining, depth + 1), _encode(v, remaining, depth + 1)]
                for k, v in value.items()
            ],
        }
    if isinstance(value, tuple):
        return {
            "t": "tuple",
            "v": [_encode(item, remaining, depth + 1) for item in value],
        }
    if isinstance(value, (set, frozenset)):
        return {
            "t": "frozenset" if isinstance(value, frozenset) else "set",
            "v": [_encode(item, remaining, depth + 1) for item in value],
        }
    if isinstance(value, bytes):
        return {"t": "bytes", "v": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime):
        return {"t": "datetime", "v": value.isoformat()}
    if isinstance(value, date):
        return {"t": "date", "v": value.isoformat()}
    if isinstance(value, np.generic):
        item = value.item()
        if isinstance(item, np.generic):
            if value.dtype.hasobject or value.dtype.fields is not None:
                raise TypeError("Worker scalars require a non-object scalar dtype")
            return {
                "t": "numpy_scalar",
                "dtype": value.dtype.str,
                "v": base64.b64encode(value.tobytes()).decode("ascii"),
            }
        return _encode(item, remaining, depth + 1)
    if isinstance(value, np.ndarray):
        remaining[1] -= value.nbytes
        if remaining[1] < 0:
            raise ValueError("Worker value exceeds 8 MiB of scalar data")
        if value.dtype.hasobject or value.dtype.fields is not None:
            raise TypeError("Worker arrays must have a non-object scalar dtype")
        if value.nbytes > MAX_MESSAGE_BYTES // 2:
            raise ValueError("Worker array exceeds transfer limit")
        return {
            "t": "array",
            "dtype": value.dtype.str,
            "shape": value.shape,
            "v": base64.b64encode(value.tobytes(order="C")).decode("ascii"),
        }
    # The SDK already loaded pydantic in the parent. Workers never import it:
    # model code stays in the parent and only explicit field data crosses.
    pydantic = sys.modules.get("pydantic")
    if pydantic is not None and isinstance(value, pydantic.BaseModel):
        names = tuple(type(value).model_fields) + tuple(
            type(value).model_computed_fields
        )
        fields = {name: getattr(value, name) for name in names}
        fields.update(value.model_extra or {})
        return {"t": "record", "v": _encode(fields, remaining, depth + 1)}
    raise TypeError(f"Unsupported worker value type: {type(value).__name__}")


def decode(value, *, records=False):
    return _decode(value, [65536, MAX_MESSAGE_BYTES], 0, records)


def _decode(value, remaining, depth, records):
    _charge(value, remaining, depth)
    if isinstance(value, list):
        return [_decode(item, remaining, depth + 1, records) for item in value]
    if not isinstance(value, dict):
        return value
    if "t" not in value:
        decoded = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Native worker mapping keys must be strings")
            _charge(key, remaining, depth + 1)
            decoded[key] = _decode(item, remaining, depth + 1, records)
        return decoded
    kind, data = value["t"], value["v"]
    if kind == "record":
        fields = _decode(data, remaining, depth + 1, records)
        if not isinstance(fields, dict):
            raise ValueError("Invalid record fields")
        return Record(fields) if records else fields
    if kind == "numpy_scalar":
        dtype = np.dtype(value["dtype"])
        raw = base64.b64decode(data, validate=True)
        if dtype.hasobject or dtype.fields is not None or len(raw) != dtype.itemsize:
            raise ValueError("Invalid worker scalar dtype/size")
        return np.frombuffer(raw, dtype=dtype)[0]
    if kind == "complex":
        return complex(
            _decode(data[0], remaining, depth + 1, records),
            _decode(data[1], remaining, depth + 1, records),
        )
    if kind == "decimal":
        return Decimal(data)
    if kind == "fraction":
        return Fraction(*data)
    if kind == "dict":
        return {
            _decode(k, remaining, depth + 1, records): _decode(
                v, remaining, depth + 1, records
            )
            for k, v in data
        }
    if kind == "tuple":
        return tuple(_decode(item, remaining, depth + 1, records) for item in data)
    if kind in {"set", "frozenset"}:
        items = {_decode(item, remaining, depth + 1, records) for item in data}
        return frozenset(items) if kind == "frozenset" else items
    if kind == "bytes":
        return base64.b64decode(data, validate=True)
    if kind == "float":
        if data not in {"nan", "inf", "-inf"}:
            raise ValueError("Invalid special float")
        return float(data)
    if kind == "datetime":
        return datetime.fromisoformat(data)
    if kind == "date":
        return date.fromisoformat(data)
    if kind == "array":
        dtype = np.dtype(value["dtype"])
        if dtype.hasobject or dtype.fields is not None:
            raise ValueError("Worker arrays must have a non-object scalar dtype")
        shape = value["shape"]
        if any(type(size) is not int or size < 0 for size in shape):
            raise ValueError("Invalid worker array shape")
        raw = base64.b64decode(data, validate=True)
        if math.prod(shape) * dtype.itemsize != len(raw):
            raise ValueError("Worker array shape/size mismatch")
        return np.frombuffer(raw, dtype=dtype).reshape(shape).copy()
    raise ValueError(f"Unknown worker value tag: {kind}")


def pack(message):
    payload = (
        json.dumps(
            message, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ).encode()
        + b"\n"
    )
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("Worker message exceeds 8 MiB")
    return payload
