"""Directory-based module grouping for map-reduce overview generation.

Pure, deterministic, no LLM calls: groups a repository's analyzed source
files into a small number of directory-shaped "modules" for the map step
in overview_mapreduce.py. Operates on file paths already known from the
dependency graph (Node.relative_path) — never reads file content itself.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List

# "Too few buckets to call them modules" — deepen the grouping while under this.
_MIN_BUCKETS = 3
# A bucket holding more than this fraction of all files gets split further.
_MAX_BUCKET_FRACTION = 0.25
# A bucket with fewer files than this merges into its parent directory's bucket.
_MIN_BUCKET_SIZE = 2

_ROOT_KEY = "(root)"


@dataclass(frozen=True)
class ModuleGroup:
    name: str
    files: List[str]


def _dir_parts(rel_path: str) -> List[str]:
    """Directory path segments only (excludes the filename itself)."""
    return rel_path.replace("\\", "/").split("/")[:-1]


def _bucket_key(rel_path: str, depth: int) -> str:
    parts = _dir_parts(rel_path)
    if not parts:
        return _ROOT_KEY
    return "/".join(parts[: max(depth, 1)])


def _group_at_depth(files: List[str], depth: int) -> Dict[str, List[str]]:
    buckets: Dict[str, List[str]] = defaultdict(list)
    for f in files:
        buckets[_bucket_key(f, depth)].append(f)
    return dict(buckets)


def _max_available_depth(files: List[str]) -> int:
    return max((len(_dir_parts(f)) for f in files), default=0)


def _split_oversized(buckets: Dict[str, List[str]], total_files: int) -> Dict[str, List[str]]:
    """Recursively split any bucket holding more than _MAX_BUCKET_FRACTION of
    all files, by regrouping that bucket's own files one directory level
    deeper. A bucket that can't be split further (its files already share
    the deepest available directory) is left as-is rather than looping."""
    threshold = max(total_files * _MAX_BUCKET_FRACTION, 1)
    result: Dict[str, List[str]] = {}
    for key, files in buckets.items():
        if len(files) <= threshold or key == _ROOT_KEY:
            result[key] = files
            continue
        current_depth = key.count("/") + 1
        deeper = _group_at_depth(files, current_depth + 1)
        if len(deeper) <= 1:
            result[key] = files
            continue
        result.update(_split_oversized(deeper, total_files))
    return result


def _merge_undersized(buckets: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Fold any bucket with fewer than _MIN_BUCKET_SIZE files into its parent
    directory's bucket (or the root bucket, if it has no parent)."""
    buckets = dict(buckets)
    changed = True
    while changed:
        changed = False
        for key, files in list(buckets.items()):
            if key == _ROOT_KEY or len(files) >= _MIN_BUCKET_SIZE or len(buckets) <= 1:
                continue
            parent = "/".join(key.split("/")[:-1]) or _ROOT_KEY
            buckets.setdefault(parent, [])
            buckets[parent].extend(files)
            del buckets[key]
            changed = True
            break
    return buckets


def _cap_buckets(buckets: Dict[str, List[str]], max_modules: int) -> Dict[str, List[str]]:
    """If still over the cap after splitting/merging, repeatedly fold the two
    smallest buckets together until at or under the cap."""
    buckets = dict(buckets)
    while len(buckets) > max_modules:
        ordered = sorted(buckets.items(), key=lambda kv: len(kv[1]))
        (key_a, files_a), (key_b, files_b) = ordered[0], ordered[1]
        merged_key = (
            f"{key_a} + {key_b}" if _ROOT_KEY not in (key_a, key_b) else _ROOT_KEY
        )
        del buckets[key_a]
        del buckets[key_b]
        buckets[merged_key] = files_a + files_b
    return buckets


def group_modules(files: List[str], max_modules: int = 40) -> List[ModuleGroup]:
    """Group a repository's source files into directory-shaped modules.

    Deterministic, LLM-free: start at directory depth 1, deepen while there
    are too few buckets to be useful module boundaries, split any bucket
    holding a disproportionate share of files, merge tiny buckets into their
    parent, then cap the total count.
    """
    unique_files = sorted(set(files))
    if not unique_files:
        return []

    depth = 1
    buckets = _group_at_depth(unique_files, depth)
    max_depth = _max_available_depth(unique_files)
    while len(buckets) < _MIN_BUCKETS and depth < max_depth:
        depth += 1
        deeper = _group_at_depth(unique_files, depth)
        if len(deeper) == len(buckets):
            break
        buckets = deeper

    buckets = _split_oversized(buckets, len(unique_files))
    buckets = _merge_undersized(buckets)
    buckets = _cap_buckets(buckets, max_modules)

    return [
        ModuleGroup(name=key, files=sorted(bucket_files))
        for key, bucket_files in sorted(buckets.items(), key=lambda kv: kv[0])
    ]
