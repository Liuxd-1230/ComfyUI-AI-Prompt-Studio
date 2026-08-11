"""Canonical comparisons for slash-delimited semantic Plan paths."""
from __future__ import annotations

from collections.abc import Iterable


def paths_overlap(left: str, right: str) -> bool:
    """Return whether either normalized path contains the other."""
    left = str(left).strip().strip("/")
    right = str(right).strip().strip("/")
    return bool(left and right and (
        left == right or left.startswith(right + "/")
        or right.startswith(left + "/")))


def path_within(path: str, roots: Iterable[str]) -> bool:
    """Return whether path equals or descends from one allowed root."""
    path = str(path).strip().strip("/")
    return bool(path and any(
        path == root or path.startswith(root + "/")
        for item in roots if (root := str(item).strip().strip("/"))))
