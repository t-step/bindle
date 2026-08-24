#!/usr/bin/env python3
"""settings_json.py — structural JSON helper for install-guardrails.sh.

Replaces jq as the Claude-layer settings.local.json merge engine, so
`bindle init`/`bindle remove`/`bindle migrate-legacy-global` need only the
interpreter already running Bindle itself (see docs/DECISIONS.md D032's
"jq elimination" amendment) — no external `jq` binary. This script is a
package-owned runtime asset, resolved and invoked exactly like the sibling
shell scripts in this directory, and deliberately has no dependency on the
`bindle` package itself (stdlib only), so it runs under any interpreter
install-guardrails.sh is told to use ($BINDLE_PYTHON, falling back to
`python3` on PATH for direct/test invocation).

Every verb is a narrow, single-purpose operation mirroring exactly one jq
filter the shell installer used to run — this is not a general JSON-patch
framework. The canonical secret/deny-policy data (FILE_DENY_GLOBS, etc.)
stays declared in install-guardrails.sh; this script only ever receives an
already-expanded manifest as a JSON array argument.

Every mutating verb writes atomically: build the new document, write it to
a temp file in the destination's own directory, then os.replace() into
place. On any failure, the destination is left completely untouched, the
temp file is cleaned up, and nothing is printed — same contract as the
jq_atomic_write bash helper it replaces.

Usage: settings_json.py VERB [ARGS...]
"""

from __future__ import annotations

import json
import os
import sys
import tempfile


def _load(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_write(path: str, text: str) -> None:
    dest_dir = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".bindle-jsontmp.", dir=dest_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _dump(doc) -> str:
    return json.dumps(doc, indent=2) + "\n"


def _pretooluse_matches(doc, matcher: str, cmd: str) -> bool:
    hooks = doc.get("hooks") or {}
    entries = hooks.get("PreToolUse") or []
    for entry in entries:
        if entry.get("matcher") != matcher:
            continue
        for h in entry.get("hooks") or []:
            if h.get("command") == cmd:
                return True
    return False


def _filter_pretooluse(doc, matcher: str, cmd: str):
    hooks = doc.get("hooks") or {}
    entries = hooks.get("PreToolUse") or []

    def keep(entry):
        if entry.get("matcher") != matcher:
            return True
        return not any(h.get("command") == cmd for h in entry.get("hooks") or [])

    return [entry for entry in entries if keep(entry)]


# --- verbs -------------------------------------------------------------


def cmd_valid_json(args):
    (path,) = args
    try:
        _load(path)
    except (OSError, ValueError):
        return 1
    return 0


def cmd_read_array(args):
    (path,) = args
    if not os.path.isfile(path):
        print("[]")
        return 0
    try:
        data = _load(path)
    except (OSError, ValueError):
        return 1
    if not isinstance(data, list):
        return 1
    print(json.dumps(data, separators=(",", ":")))
    return 0


def cmd_pretooluse_present(args):
    path, matcher, cmd = args
    try:
        doc = _load(path)
    except (OSError, ValueError):
        return 1
    if not isinstance(doc, dict):
        return 1
    return 0 if _pretooluse_matches(doc, matcher, cmd) else 1


def cmd_remove_pretooluse(args):
    path, matcher, cmd = args
    try:
        doc = _load(path)
        if not isinstance(doc, dict):
            return 1
        doc.setdefault("hooks", {})["PreToolUse"] = _filter_pretooluse(doc, matcher, cmd)
        _atomic_write(path, _dump(doc))
    except (OSError, ValueError):
        return 1
    return 0


def cmd_add_pretooluse(args):
    path, matcher, cmd, timeout = args
    try:
        doc = _load(path)
        if not isinstance(doc, dict):
            return 1
        hooks = doc.setdefault("hooks", {})
        entries = hooks.get("PreToolUse") or []
        entries.append(
            {
                "matcher": matcher,
                "hooks": [{"type": "command", "command": cmd, "timeout": int(timeout)}],
            }
        )
        hooks["PreToolUse"] = entries
        _atomic_write(path, _dump(doc))
    except (OSError, ValueError):
        return 1
    return 0


def cmd_remove_deny(args):
    path, remove_json = args
    try:
        doc = _load(path)
        if not isinstance(doc, dict):
            return 1
        remove = json.loads(remove_json)
        permissions = doc.setdefault("permissions", {})
        existing = permissions.get("deny") or []
        permissions["deny"] = [x for x in existing if x not in remove]
        _atomic_write(path, _dump(doc))
    except (OSError, ValueError):
        return 1
    return 0


def cmd_deny_diff(args):
    path, manifest_json = args
    try:
        doc = _load(path)
        if not isinstance(doc, dict):
            return 1
        manifest = json.loads(manifest_json)
        existing = doc.get("permissions", {}).get("deny") or []
        added = [x for x in manifest if x not in existing]
    except (OSError, ValueError):
        return 1
    print(json.dumps(added, separators=(",", ":")))
    return 0


def cmd_merge_deny(args):
    path, manifest_json = args
    try:
        doc = _load(path)
        if not isinstance(doc, dict):
            return 1
        manifest = json.loads(manifest_json)
        permissions = doc.setdefault("permissions", {})
        existing = permissions.get("deny") or []
        to_add = [x for x in manifest if x not in existing]
        permissions["deny"] = existing + to_add
        _atomic_write(path, _dump(doc))
    except (OSError, ValueError):
        return 1
    return 0


def cmd_array_union(args):
    a_json, b_json = args
    try:
        combined = json.loads(a_json) + json.loads(b_json)
    except ValueError:
        return 1
    print(json.dumps(sorted(set(combined)), separators=(",", ":")))
    return 0


def cmd_write_json(args):
    path, value_json = args
    try:
        value = json.loads(value_json)
        _atomic_write(path, _dump(value))
    except (OSError, ValueError):
        return 1
    return 0


def cmd_length(args):
    (value_json,) = args
    try:
        value = json.loads(value_json)
    except ValueError:
        return 1
    print(len(value))
    return 0


def cmd_lines_to_json_array(args):
    assert args == []
    lines = [line.rstrip("\n") for line in sys.stdin]
    print(json.dumps(lines, separators=(",", ":")))
    return 0


def _is_effectively_empty(value) -> bool:
    """True iff VALUE is None, an empty container, or a (nested) structure
    made up of nothing but empty containers. A non-empty list or a scalar
    (including False/0/"") is never effectively empty — any of those
    represents real content, even if falsy."""
    if value is None:
        return True
    if isinstance(value, dict):
        return all(_is_effectively_empty(v) for v in value.values())
    if isinstance(value, list):
        return len(value) == 0
    return False


def cmd_doc_is_empty(args):
    """Exit 0 iff the settings document at PATH holds nothing but empty
    containers (e.g. {}, {"hooks": {"PreToolUse": []}}) once Bindle's own
    entries have already been removed from it — used by --uninstall to
    decide whether the file itself (and its ignore rule) is safe to remove
    entirely, versus still holding unrelated user content that must be
    preserved untouched."""
    (path,) = args
    try:
        doc = _load(path)
    except (OSError, ValueError):
        return 1
    if not isinstance(doc, dict):
        return 1
    return 0 if _is_effectively_empty(doc) else 1


_VERBS = {
    "valid-json": cmd_valid_json,
    "read-array": cmd_read_array,
    "pretooluse-present": cmd_pretooluse_present,
    "remove-pretooluse": cmd_remove_pretooluse,
    "add-pretooluse": cmd_add_pretooluse,
    "remove-deny": cmd_remove_deny,
    "deny-diff": cmd_deny_diff,
    "merge-deny": cmd_merge_deny,
    "array-union": cmd_array_union,
    "write-json": cmd_write_json,
    "length": cmd_length,
    "lines-to-json-array": cmd_lines_to_json_array,
    "doc-is-empty": cmd_doc_is_empty,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in _VERBS:
        print(f"usage: {sys.argv[0]} {{{'|'.join(_VERBS)}}} [args...]", file=sys.stderr)
        return 2
    return _VERBS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
