"""Tests for merge_ini. One test per CC-xx example in docs/CUSTOM-CONFIG.md."""

import os

import pytest
from ansible.errors import AnsibleFilterError
from merge_ini import FilterModule, merge_ini

BASE = """\
[mysqld]
max_connections = 500
skip_name_resolve

[galera]
wsrep_on = ON
"""

HEADER = """\
# Managed by Tera - JANGAN edit manual
# Ubah lewat custom config: config/mariadb/
"""


def src(path, content):
    return {"path": path, "content": content}


CC01_GLOBAL = src(
    "mariadb/my.cnf",
    """\
[mysqld]
max-connections = 1000
innodb_io_capacity = 2000
""",
)
CC01_DB01 = src(
    "mariadb/db01/my.cnf",
    """\
[mysqld]
innodb_io_capacity = 4000

[mariadb]
log_warnings = 3
""",
)
CC01_DB01_OUT = (
    HEADER
    + """\
# Sources: role:tera.cnf.j2, mariadb/my.cnf, mariadb/db01/my.cnf

[mysqld]
max_connections = 1000
skip_name_resolve
innodb_io_capacity = 4000

[galera]
wsrep_on = ON

[mariadb]
log_warnings = 3
"""
)


def test_cc01_global_and_host():
    assert merge_ini(BASE, [CC01_GLOBAL, CC01_DB01]) == CC01_DB01_OUT
    assert (
        merge_ini(BASE, [CC01_GLOBAL])
        == HEADER
        + """\
# Sources: role:tera.cnf.j2, mariadb/my.cnf

[mysqld]
max_connections = 1000
skip_name_resolve
innodb_io_capacity = 2000

[galera]
wsrep_on = ON
"""
    )


def test_cc02_remove_key():
    out = merge_ini(BASE, [src("mariadb/my.cnf", "[mysqld]\nskip_name_resolve = __remove__\n")])
    assert (
        out
        == HEADER
        + """\
# Sources: role:tera.cnf.j2, mariadb/my.cnf

[mysqld]
max_connections = 500

[galera]
wsrep_on = ON
"""
    )


def test_cc02_remove_missing_key_is_not_error():
    out = merge_ini(BASE, [src("mariadb/my.cnf", "[mysqld]\nnot_there = __remove__\n")])
    assert "not_there" not in out


def test_cc03_key_normalized_to_lowercase():
    out = merge_ini(BASE, [src("mariadb/my.cnf", "[mysqld]\nMax-Connections = 800\n")])
    assert (
        out
        == HEADER
        + """\
# Sources: role:tera.cnf.j2, mariadb/my.cnf

[mysqld]
max_connections = 800
skip_name_resolve

[galera]
wsrep_on = ON
"""
    )


def test_cc03_section_name_is_case_sensitive():
    out = merge_ini(BASE, [src("mariadb/my.cnf", "[MySQLd]\nfoo = 1\n")])
    assert "[MySQLd]\nfoo = 1\n" in out
    assert "[mysqld]\nmax_connections = 500\n" in out


def test_cc04_duplicate_key_last_wins():
    out = merge_ini(
        BASE, [src("mariadb/my.cnf", "[mysqld]\nmax_connections = 600\nmax_connections = 700\n")]
    )
    assert (
        out
        == HEADER
        + """\
# Sources: role:tera.cnf.j2, mariadb/my.cnf

[mysqld]
max_connections = 700
skip_name_resolve

[galera]
wsrep_on = ON
"""
    )


def test_cc05_quoted_value_with_equals():
    out = merge_ini(
        BASE,
        [
            src(
                "mariadb/galera.cnf",
                '[galera]\nwsrep_provider_options = "gcache.size=2G; gcs.fc_limit=256"\n',
            )
        ],
    )
    assert (
        out
        == HEADER
        + """\
# Sources: role:tera.cnf.j2, mariadb/galera.cnf

[mysqld]
max_connections = 500
skip_name_resolve

[galera]
wsrep_on = ON
wsrep_provider_options = "gcache.size=2G; gcs.fc_limit=256"
"""
    )


def test_cc06_key_before_section_errors_with_relative_path():
    bad = src("mariadb/bad.cnf", "max_connections = 1000\n\n[mysqld]\nskip_name_resolve\n")
    with pytest.raises(AnsibleFilterError) as exc:
        merge_ini(BASE, [bad])
    msg = str(exc.value)
    assert msg.startswith(
        "mariadb/bad.cnf: line 1: key 'max_connections' found before any [section] header"
    )
    assert "[mysqld]" in msg  # tells the user how to fix it


def test_cc07_empty_section_not_written():
    out = merge_ini(BASE, [src("mariadb/client.cnf", "[client]\n# belum ada isi\n")])
    assert (
        out
        == HEADER
        + """\
# Sources: role:tera.cnf.j2, mariadb/client.cnf

[mysqld]
max_connections = 500
skip_name_resolve

[galera]
wsrep_on = ON
"""
    )


def test_cc07_section_emptied_by_remove_not_written():
    out = merge_ini(BASE, [src("mariadb/my.cnf", "[galera]\nwsrep_on = __remove__\n")])
    assert "[galera]" not in out


def test_cc08_no_custom_config():
    assert (
        merge_ini(BASE, [])
        == HEADER
        + """\
# Sources: role:tera.cnf.j2

[mysqld]
max_connections = 500
skip_name_resolve

[galera]
wsrep_on = ON
"""
    )
    assert merge_ini(BASE) == merge_ini(BASE, [])


def _sources_from_dir(config_dir, host):
    """Mimic roles/mariadb/tasks/config.yml: global then host files, alphabetical, relative."""
    out = []
    for sub in ("mariadb", os.path.join("mariadb", host)):
        d = os.path.join(config_dir, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            if name.endswith(".cnf") and os.path.isfile(p):
                with open(p) as fh:
                    out.append(src(os.path.relpath(p, config_dir), fh.read()))
    return out


def test_cc09_deterministic_across_runs_and_repo_paths(tmp_path):
    outputs = []
    for repo in ("home/a/tera", "srv/tera"):
        config_dir = tmp_path / repo / "inventory" / "prod-a" / "config"
        (config_dir / "mariadb" / "db01").mkdir(parents=True)
        (config_dir / "mariadb" / "my.cnf").write_text(CC01_GLOBAL["content"])
        (config_dir / "mariadb" / "db01" / "my.cnf").write_text(CC01_DB01["content"])
        (config_dir / "mariadb" / "README.txt").write_text("ignored")
        for _ in range(2):
            outputs.append(merge_ini(BASE, _sources_from_dir(str(config_dir), "db01")))
    assert all(o == CC01_DB01_OUT for o in outputs)
    assert str(tmp_path) not in outputs[0]


def test_cc10_empty_value_differs_from_flag():
    out = merge_ini(BASE, [src("mariadb/my.cnf", "[mysqld]\ninit_connect =\n")])
    assert (
        out
        == HEADER
        + """\
# Sources: role:tera.cnf.j2, mariadb/my.cnf

[mysqld]
max_connections = 500
skip_name_resolve
init_connect = {trailing}

[galera]
wsrep_on = ON
""".format(trailing="")
    )
    assert "\ninit_connect = \n" in out
    assert "\ninit_connect\n" not in out


@pytest.mark.parametrize("directive", ["!include /etc/foo.cnf", "!includedir /etc/my.cnf.d"])
def test_include_directives_error(directive):
    with pytest.raises(AnsibleFilterError) as exc:
        merge_ini(BASE, [src("mariadb/inc.cnf", f"[mysqld]\n{directive}\n")])
    msg = str(exc.value)
    assert msg.startswith("mariadb/inc.cnf: line 2:")
    assert directive.split()[0] in msg


def test_comments_are_dropped_and_no_inline_comments():
    out = merge_ini(
        BASE, [src("mariadb/my.cnf", "# comment\n; other\n[mysqld]\nfoo = bar # not a comment\n")]
    )
    assert "# comment" not in out
    assert "; other" not in out
    assert "foo = bar # not a comment\n" in out


def test_absolute_source_path_rejected():
    with pytest.raises(AnsibleFilterError, match="relatif"):
        merge_ini(BASE, [src("/home/a/tera/inventory/x/config/mariadb/my.cnf", "[mysqld]\n")])


def test_filter_registered():
    assert FilterModule().filters()["merge_ini"] is merge_ini
