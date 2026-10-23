"""Filters for dynamic config changes through SET GLOBAL (ADR 0018).

    {{ old_text | tera_dynamic_plan(new_text, whitelist, aliases) }}
    {{ plan.changes | tera_dynamic_order(running) }}
    {{ changes | tera_dynamic_mismatch(effective) }}   values the server did not take as asked
    {{ value | tera_mysql_norm }}            comparable form of a config or server value
    {{ value | tera_mysql_literal }}         SQL literal for SET GLOBAL

Texts are rendered 99-tera.cnf files (merge_ini output: "[section]" headers, "key = value" or a bare
key; keys already normalized). Tests: plugins/tests/test_tera_cnf.py.
"""

from __future__ import annotations

import re

SERVER_SECTIONS = ("mysqld", "mariadb", "server", "galera")
SIZE_RE = re.compile(r"^(\d+)([kmgt])$", re.IGNORECASE)
INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)(e[+-]?\d+)?$", re.IGNORECASE)
TRUE_WORDS = ("on", "true", "yes")
FALSE_WORDS = ("off", "false", "no")
# (lower, upper): the server refuses lower > upper, so the order of SET depends on the direction.
PAIRS = (("innodb_io_capacity", "innodb_io_capacity_max"),)


def _key(key):
    return str(key).strip().lower().replace("-", "_")


def _parse(text):
    """{section: {key: value}} and the keys seen per section, in file order."""
    sections = {}
    current = None
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            sections.setdefault(current, {})
            continue
        if current is None:
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            sections[current][_key(key)] = value.strip()
        else:
            sections[current][_key(line)] = None
    return sections


def _unquote(value):
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def tera_mysql_norm(value):
    """Comparable form: sizes in bytes, booleans 1/0, numbers without padding, text lower case."""
    if value is None:
        return "1"  # a bare key in an option file means ON
    text = _unquote(value)
    low = text.lower()
    if low in TRUE_WORDS:
        return "1"
    if low in FALSE_WORDS:
        return "0"
    match = SIZE_RE.match(text)
    if match:
        power = "kmgt".index(match.group(2).lower()) + 1
        return str(int(match.group(1)) * 1024**power)
    if INT_RE.match(text):
        return str(int(text))
    if FLOAT_RE.match(text):
        number = float(text)
        return str(int(number)) if number.is_integer() else repr(number)
    return low


def tera_mysql_literal(value):
    """SQL literal for SET GLOBAL: numbers bare (sizes converted), anything else quoted."""
    norm = tera_mysql_norm(value)
    if INT_RE.match(norm) or FLOAT_RE.match(norm):
        return norm
    text = _unquote(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def tera_dynamic_plan(old_text, new_text, whitelist, aliases=None):
    """Decide whether the change from old_text to new_text can be applied with SET GLOBAL.

    Returns {"dynamic": bool, "reasons": [...], "changes": [{"key", "variable", "old", "new"}]}.
    "key" is the name in the config, "variable" the canonical server variable (aliases resolved).
    Dynamic only when every changed key is in a server section, in the whitelist (after aliases),
    set (not removed), and present in a single server section.
    """
    aliases = {_key(k): _key(v) for k, v in (aliases or {}).items()}
    allowed = {_key(v) for v in whitelist or []}
    old = _parse(old_text)
    new = _parse(new_text)
    reasons = []
    changes = []
    if not str(old_text or "").strip():
        return {"dynamic": False, "reasons": ["config lama belum ada"], "changes": []}

    for section in sorted(set(old) | set(new)):
        before, after = old.get(section, {}), new.get(section, {})
        if before == after:
            continue
        if section not in SERVER_SECTIONS:
            reasons.append(f"section [{section}] berubah")
            continue
        for key in sorted(set(before) | set(after)):
            same = key in before and key in after
            if same and tera_mysql_norm(before[key]) == tera_mysql_norm(after[key]):
                continue
            if key not in after:
                reasons.append(f"{key} dihapus")
                continue
            variable = aliases.get(key, key)
            if variable not in allowed:
                reasons.append(f"{key} bukan variabel dinamis")
                continue
            changes.append(
                {"key": key, "variable": variable, "old": before.get(key), "new": after[key]}
            )

    seen = {}
    for section in SERVER_SECTIONS:
        for key in new.get(section, {}):
            seen.setdefault(aliases.get(key, key), []).append(section)
    for change in changes:
        if len(seen.get(change["variable"], [])) > 1:
            reasons.append(f"{change['key']} ada di lebih dari satu section")
    return {"dynamic": not reasons, "reasons": reasons, "changes": changes}


def tera_dynamic_order(changes, running=None):
    """Order changes so each SET GLOBAL is valid on its own: for a (lower, upper) pair, the upper
    bound goes first when it rises and last when it falls. running: {variable: current value}."""
    running = running or {}
    ordered = list(changes)
    for lower, upper in PAIRS:
        names = [c["variable"] for c in ordered]
        if lower not in names or upper not in names:
            continue
        upper_change = ordered[names.index(upper)]
        current = tera_mysql_norm(running.get(upper, upper_change.get("old") or "0"))
        rising = float(tera_mysql_norm(upper_change["new"])) >= float(current or 0)
        lower_change = ordered.pop(names.index(lower))
        names = [c["variable"] for c in ordered]
        index = names.index(upper)
        ordered.insert(index + 1 if rising else index, lower_change)
    return ordered


def tera_dynamic_mismatch(changes, effective):
    """Changes whose value read back (effective: {variable: value}) differs after normalization,
    as [{"variable", "requested", "effective"}]; a missing value counts as a difference."""
    out = []
    for change in changes:
        value = (effective or {}).get(change["variable"])
        if value is None or tera_mysql_norm(value) != tera_mysql_norm(change["new"]):
            out.append(
                {"variable": change["variable"], "requested": change["new"], "effective": value}
            )
    return out


class FilterModule:
    def filters(self):
        return {
            "tera_dynamic_plan": tera_dynamic_plan,
            "tera_dynamic_order": tera_dynamic_order,
            "tera_dynamic_mismatch": tera_dynamic_mismatch,
            "tera_mysql_norm": tera_mysql_norm,
            "tera_mysql_literal": tera_mysql_literal,
        }
