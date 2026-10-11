"""Lossless producer dictionary shared with AR-app's ar-history-dag-v1 codec."""
from __future__ import annotations

import json
import math

FORMAT = "ar-history-dag-v1"
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
MAX_NODES, MAX_EDGES, MAX_DEPTH, MAX_KEYS = 1_000_000, 4_000_000, 64, 10_000
MAX_CHARACTERS, MAX_EXPANSION = 64 * 1024 * 1024, 128 * 1024 * 1024


class PackedBudgetError(ValueError):
    """An optional packed projection exceeds the phone's processing budget."""


def _references(refs):
    parts = []
    for ref in refs:
        while True:
            part, ref = ref & 31, ref >> 5
            parts.append(ALPHABET[part | (32 if ref else 0)])
            if not ref:
                break
    return "".join(parts)


def pack(value):
    """Intern identical immutable values; every reference points backwards."""
    nodes, interned, ancestors = [], {}, set()

    def intern(node):
        signature = json.dumps(node, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if signature in interned:
            return interned[signature]
        if len(nodes) >= MAX_NODES:
            raise PackedBudgetError("Historical dictionary node budget exceeded")
        result = len(nodes)
        interned[signature] = result
        nodes.append(node)
        return result

    def visit(item, depth):
        if depth > MAX_DEPTH:
            raise PackedBudgetError("Historical dictionary depth exceeded")
        if item is None or type(item) in (bool, str, int, float):
            return intern(item)
        if type(item) not in (list, dict) or id(item) in ancestors:
            raise ValueError("Historical dictionary requires acyclic JSON values")
        ancestors.add(id(item))
        if isinstance(item, list):
            node = [0, _references(visit(child, depth + 1) for child in item)]
        else:
            if len(item) > MAX_KEYS:
                raise PackedBudgetError("Historical dictionary object keys exceed budget")
            if any(type(key) is not str for key in item):
                raise ValueError("Historical dictionary object keys must be strings")
            shape = intern([0, _references(visit(key, depth + 1) for key in item)])
            node = [1, shape, _references(visit(child, depth + 1) for child in item.values())]
        ancestors.remove(id(item))
        return intern(node)

    root = visit(value, 0)
    result = {"format": FORMAT, "root": root, "nodes": nodes}
    # Producer acceptance exercises the same bounded structure as the consumer.
    if unpack(result) != value:
        raise ValueError("Historical dictionary round trip differs")
    return result


def _decode_references(encoded, limit):
    if type(encoded) is not str:
        raise ValueError("Historical dictionary references must be a string")
    if len(encoded) > MAX_EDGES * 4:
        raise PackedBudgetError("Historical dictionary references exceed budget")
    ref, shift = 0, 0
    for character in encoded:
        part = ALPHABET.find(character)
        if part < 0 or shift > 15:
            raise ValueError("Historical dictionary reference is invalid")
        ref += (part & 31) << shift
        if part & 32:
            shift += 5
            continue
        if ref >= limit or (shift > 0 and part & 31 == 0):
            raise ValueError("Historical dictionary reference is not canonical or earlier")
        yield ref
        ref, shift = 0, 0
    if shift:
        raise ValueError("Historical dictionary reference is truncated")


def unpack(packed):
    if (type(packed) is not dict or set(packed) != {"format", "root", "nodes"}
            or packed["format"] != FORMAT or type(packed["nodes"]) is not list
            or not 0 < len(packed["nodes"]) <= MAX_NODES or type(packed["root"]) is not int
            or packed["root"] != len(packed["nodes"]) - 1):
        raise ValueError("Historical dictionary schema is invalid")
    values, sizes, depths = [], [], []
    edges, characters = 0, 0
    for node in packed["nodes"]:
        size, depth, decoded = 1, 0, node
        if isinstance(node, str):
            length = len(node.encode("utf-16-le")) // 2
            characters += length
            size += length
        elif type(node) is list:
            if not node or type(node[0]) is not int or node[0] not in (0, 1) or len(node) != (2 if node[0] == 0 else 3):
                raise ValueError("Historical dictionary container is invalid")
            keys = None
            if node[0] == 1:
                shape = node[1]
                if type(shape) is not int or not 0 <= shape < len(values):
                    raise ValueError("Historical dictionary shape reference is invalid")
                keys = values[shape]
                if (type(keys) is not list or len(keys) > MAX_KEYS
                        or any(type(key) is not str for key in keys) or len(set(keys)) != len(keys)):
                    raise ValueError("Historical dictionary keys are invalid")
                size += sizes[shape]
            children = []
            for ref in _decode_references(node[-1], len(values)):
                edges += 1
                size += sizes[ref]
                depth = max(depth, depths[ref] + 1)
                if edges > MAX_EDGES or size > MAX_EXPANSION or depth > MAX_DEPTH:
                    raise PackedBudgetError("Historical dictionary expansion budget exceeded")
                children.append(values[ref])
            if keys is not None and len(keys) != len(children):
                raise ValueError("Historical dictionary shape length differs")
            decoded = children if keys is None else dict(zip(keys, children))
        elif node is not None:
            try:
                finite = type(node) in (bool, int, float) and math.isfinite(node)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("Historical dictionary primitive is invalid")
        if characters > MAX_CHARACTERS or size > MAX_EXPANSION:
            raise PackedBudgetError("Historical dictionary character budget exceeded")
        values.append(decoded)
        sizes.append(size)
        depths.append(depth)
    return values[packed["root"]]
