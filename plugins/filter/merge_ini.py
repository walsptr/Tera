"""merge_ini filter: merge MariaDB option files into one deterministic drop-in.

Behaviour is specified in docs/CUSTOM-CONFIG.md; every CC-xx example there has a test in
plugins/tests/test_merge_ini.py.

Usage in a task:

    {{ base_text | merge_ini(sources) }}

``base_text`` is the rendered role template. ``sources`` is an ordered list of
``{"path": <path relative to tera_config_dir>, "content": <rendered text>}``; later
sources win.
"""

from __future__ import annotations

from ansible.errors import AnsibleFilterError

BASE_NAME = "role:tera.cnf.j2"
REMOVE = "__remove__"
HEADER = (
    "# Managed by Tera - JANGAN edit manual",
    "# Ubah lewat custom config: config/mariadb/",
)


def _normalize_key(key):
    return key.strip().lower().replace("-", "_")


def _error(name, lineno, msg):
    return AnsibleFilterError(f"{name}: line {lineno}: {msg}")


def _apply(sections, text, name):
    """Parse ``text`` and apply its entries onto ``sections`` in place."""
    current = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("!"):
            raise _error(
                name,
                lineno,
                f"'{line.split()[0]}' tidak didukung; salin isi file tersebut ke config/mariadb/",
            )
        if line.startswith("["):
            if not line.endswith("]") or not line[1:-1].strip():
                raise _error(name, lineno, f"header section tidak valid: {line!r}")
            current = line[1:-1].strip()
            sections.setdefault(current, {})
            continue

        if "=" in line:
            raw_key, value = line.split("=", 1)
            value = value.strip()
        else:
            raw_key, value = line, None
        key = _normalize_key(raw_key)
        if not key:
            raise _error(name, lineno, f"key kosong: {line!r}")
        if current is None:
            raise _error(
                name,
                lineno,
                f"key '{raw_key.strip()}' found before any [section] header; "
                "tambahkan header section (mis. [mysqld]) di atasnya",
            )
        if value == REMOVE:
            sections[current].pop(key, None)
        else:
            sections[current][key] = value


def _render(sections, names):
    lines = list(HEADER)
    lines.append("# Sources: " + ", ".join(names))
    for section, entries in sections.items():
        if not entries:
            continue
        lines.append("")
        lines.append(f"[{section}]")
        for key, value in entries.items():
            lines.append(key if value is None else f"{key} = {value}")
    return "\n".join(lines) + "\n"


def merge_ini(base, sources=None, base_name=BASE_NAME):
    """Merge ``sources`` onto ``base`` and return the rendered option file."""
    if not isinstance(base, str):
        raise AnsibleFilterError("merge_ini: base harus berupa string")
    sources = sources or []
    if not isinstance(sources, list):
        raise AnsibleFilterError("merge_ini: sources harus berupa list")

    sections = {}
    names = [base_name]
    _apply(sections, base, base_name)
    for src in sources:
        if not isinstance(src, dict) or "path" not in src or "content" not in src:
            raise AnsibleFilterError("merge_ini: setiap source wajib punya 'path' dan 'content'")
        path = str(src["path"])
        if path.startswith("/") or path.startswith(".."):
            raise AnsibleFilterError(
                f"merge_ini: path source harus relatif terhadap tera_config_dir: {path}"
            )
        _apply(sections, str(src["content"]), path)
        names.append(path)
    return _render(sections, names)


class FilterModule:
    def filters(self):
        return {"merge_ini": merge_ini}
