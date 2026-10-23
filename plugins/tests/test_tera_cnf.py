"""Tests for tera_cnf (ADR 0018: dynamic config changes through SET GLOBAL)."""

import pytest
from tera_cnf import (
    FilterModule,
    tera_dynamic_mismatch,
    tera_dynamic_order,
    tera_dynamic_plan,
    tera_mysql_literal,
    tera_mysql_norm,
)

WHITELIST = ["max_connections", "wait_timeout", "max_allowed_packet", "log_slow_query",
             "log_slow_query_time", "innodb_io_capacity", "innodb_io_capacity_max"]  # fmt: skip
ALIASES = {"slow_query_log": "log_slow_query", "long_query_time": "log_slow_query_time"}

OLD = """\
# Managed by Tera - JANGAN edit manual
# Sources: role:tera.cnf.j2

[mysqld]
max_connections = 500
wait_timeout = 600
skip_name_resolve

[galera]
wsrep_on = ON
wsrep_cluster_address = gcomm://10.0.0.1,10.0.0.2,10.0.0.3

[client]
port = 3306
"""


def plan(new, old=OLD):
    return tera_dynamic_plan(old, new, WHITELIST, ALIASES)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("512M", "536870912"),
        ("1k", "1024"),
        ("2G", "2147483648"),
        ("ON", "1"),
        ("off", "0"),
        ("TRUE", "1"),
        (None, "1"),
        ("0010", "10"),
        ("2", "2"),
        ("2.000000", "2"),
        ("0.5", "0.5"),
        ("'ROW'", "row"),
        ("STRICT_TRANS_TABLES", "strict_trans_tables"),
    ],
)
def test_norm(value, expected):
    assert tera_mysql_norm(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [("512M", "536870912"), ("ON", "1"), ("0.5", "0.5"), ("FULL", "'FULL'"), ("it's", "'it\\'s'")],
)
def test_literal(value, expected):
    assert tera_mysql_literal(value) == expected


def test_whitelisted_changes_are_dynamic():
    result = plan(OLD.replace("max_connections = 500", "max_connections = 700"))
    assert result["dynamic"] is True
    assert result["changes"] == [
        {"key": "max_connections", "variable": "max_connections", "old": "500", "new": "700"}
    ]


def test_added_whitelisted_key_is_dynamic():
    result = plan(OLD.replace("skip_name_resolve", "skip_name_resolve\nmax_allowed_packet = 512M"))
    assert result["dynamic"] is True
    assert result["changes"][0]["variable"] == "max_allowed_packet"


def test_alias_maps_to_the_canonical_variable():
    extra = "skip_name_resolve\nslow_query_log = ON\nlong_query_time = 2"
    result = plan(OLD.replace("skip_name_resolve", extra))
    assert result["dynamic"] is True
    assert {c["variable"] for c in result["changes"]} == {"log_slow_query", "log_slow_query_time"}


def test_same_value_written_differently_is_no_change():
    result = plan(OLD.replace("wait_timeout = 600", "wait_timeout = 0600"))
    assert result == {"dynamic": True, "reasons": [], "changes": []}


def test_comment_only_change_needs_no_restart():
    header = "# Sources: role:tera.cnf.j2"
    result = plan(OLD.replace(header, header + ", mariadb/x.cnf"))
    assert result == {"dynamic": True, "reasons": [], "changes": []}


def test_static_variable_forces_restart():
    result = plan(OLD.replace("skip_name_resolve", "skip_name_resolve\ninnodb_log_file_size = 1G"))
    assert result["dynamic"] is False
    assert "innodb_log_file_size bukan variabel dinamis" in result["reasons"]


def test_mixed_change_forces_restart():
    new = OLD.replace("max_connections = 500", "max_connections = 700").replace(
        "skip_name_resolve", "skip_name_resolve\ninnodb_log_file_size = 1G"
    )
    assert plan(new)["dynamic"] is False


def test_removed_key_forces_restart():
    result = plan(OLD.replace("wait_timeout = 600\n", ""))
    assert result["dynamic"] is False
    assert "wait_timeout dihapus" in result["reasons"]


def test_wsrep_change_forces_restart():
    result = plan(OLD.replace("10.0.0.1,10.0.0.2,10.0.0.3", "10.0.0.1,10.0.0.2"))
    assert result["dynamic"] is False


def test_non_server_section_forces_restart():
    result = plan(OLD.replace("port = 3306", "port = 3307"))
    assert result["dynamic"] is False
    assert "section [client] berubah" in result["reasons"]


def test_key_in_two_server_sections_forces_restart():
    result = plan(OLD.replace("wsrep_on = ON", "wsrep_on = ON\nmax_connections = 800").replace(
        "max_connections = 500", "max_connections = 700"))  # fmt: skip
    assert result["dynamic"] is False


def test_missing_old_config_forces_restart():
    assert plan(OLD, old="")["dynamic"] is False


def _changes(*pairs):
    return [{"key": k, "variable": k, "old": o, "new": n} for k, o, n in pairs]


def test_order_pair_when_raising():
    changes = _changes(
        ("innodb_io_capacity", "200", "3000"), ("innodb_io_capacity_max", "2000", "6000")
    )
    order = tera_dynamic_order(changes, {"innodb_io_capacity_max": "2000"})
    assert [c["variable"] for c in order] == ["innodb_io_capacity_max", "innodb_io_capacity"]


def test_order_pair_when_lowering():
    changes = _changes(
        ("innodb_io_capacity_max", "6000", "1000"), ("innodb_io_capacity", "3000", "500")
    )
    order = tera_dynamic_order(changes, {"innodb_io_capacity_max": "6000"})
    assert [c["variable"] for c in order] == ["innodb_io_capacity", "innodb_io_capacity_max"]


def test_order_keeps_others():
    changes = _changes(("max_connections", "1", "2"), ("wait_timeout", "1", "2"))
    assert tera_dynamic_order(changes, {}) == changes


def test_mismatch_reports_adjusted_and_missing_values():
    changes = _changes(("max_allowed_packet", "16M", "1000000"), ("wait_timeout", "600", "700"))
    changes += _changes(("log_slow_query", "OFF", "ON"))
    effective = {"max_allowed_packet": "999424", "wait_timeout": "700"}
    assert tera_dynamic_mismatch(changes, effective) == [
        {"variable": "max_allowed_packet", "requested": "1000000", "effective": "999424"},
        {"variable": "log_slow_query", "requested": "ON", "effective": None},
    ]


def test_mismatch_accepts_equal_forms():
    changes = _changes(("max_allowed_packet", "16M", "512M"), ("log_slow_query", "OFF", "ON"))
    effective = {"max_allowed_packet": "536870912", "log_slow_query": "1"}
    assert tera_dynamic_mismatch(changes, effective) == []


def test_filter_module():
    assert set(FilterModule().filters()) == {
        "tera_dynamic_plan", "tera_dynamic_order", "tera_dynamic_mismatch", "tera_mysql_norm",
        "tera_mysql_literal",
    }  # fmt: skip
