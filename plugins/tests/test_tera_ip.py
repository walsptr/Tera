"""Tests for the tera_ip filters (IPv4, CIDR, address in subnet)."""

import pytest
from tera_ip import (
    FilterModule,
    tera_fw_rich_rule,
    tera_ipv4_in_network,
    tera_is_ipv4,
    tera_is_ipv4_network,
)


@pytest.mark.parametrize("value", ["10.0.0.5", "192.168.121.1", "0.0.0.0", " 10.0.0.5 "])
def test_is_ipv4_valid(value):
    assert tera_is_ipv4(value) is True


@pytest.mark.parametrize(
    "value",
    ["", "10.0.0", "10.0.0.256", "10.0.0.5/32", "fe80::1", "db01", None, 10, ["10.0.0.5"]],
)
def test_is_ipv4_invalid(value):
    assert tera_is_ipv4(value) is False


@pytest.mark.parametrize("value", ["10.0.0.0/24", "0.0.0.0/0", "10.0.0.5/32", "10.0.0.5"])
def test_is_ipv4_network_valid(value):
    assert tera_is_ipv4_network(value) is True


@pytest.mark.parametrize(
    "value",
    ["10.0.0.5/24", "10.0.0.0/33", "10.0.0.0/255.255.255.0.0", "fe80::/64", "any", "", None, 24],
)
def test_is_ipv4_network_invalid(value):
    assert tera_is_ipv4_network(value) is False


@pytest.mark.parametrize(
    ("address", "network"),
    [
        ("10.77.0.100", "10.77.0.0/24"),
        ("10.77.0.100", "10.77.0.0/255.255.255.0"),
        ("10.77.0.100", "10.77.0.11/24"),
        ("10.77.0.100", "0.0.0.0/0"),
        ("10.77.0.100", "10.77.0.100/32"),
    ],
)
def test_in_network_true(address, network):
    assert tera_ipv4_in_network(address, network) is True


@pytest.mark.parametrize(
    ("address", "network"),
    [
        ("10.78.0.100", "10.77.0.0/24"),
        ("10.77.0.100", "10.77.0.101/32"),
        ("10.77.0.100/32", "10.77.0.0/24"),
        ("not-an-ip", "10.77.0.0/24"),
        ("10.77.0.100", "not-a-network"),
        ("10.77.0.100", None),
        (None, "10.77.0.0/24"),
    ],
)
def test_in_network_false(address, network):
    assert tera_ipv4_in_network(address, network) is False


def test_filter_module_exports():
    expected = {"tera_is_ipv4", "tera_is_ipv4_network", "tera_ipv4_in_network", "tera_fw_rich_rule"}
    assert set(FilterModule().filters()) == expected


def test_fw_rich_rule_matches_firewalld_listing():
    # Same text firewall-cmd --list-all prints (checked on Rocky 9 in the galera scenario).
    assert tera_fw_rich_rule("192.168.121.38", "4567/tcp") == (
        'rule family="ipv4" source address="192.168.121.38" port port="4567" protocol="tcp" accept'
    )


def test_fw_rich_rule_pair_and_cidr():
    assert tera_fw_rich_rule(["10.0.0.0/24", "4567/udp"]) == (
        'rule family="ipv4" source address="10.0.0.0/24" port port="4567" protocol="udp" accept'
    )


def test_fw_rich_rule_int_port_defaults_to_tcp():
    assert tera_fw_rich_rule("10.0.0.5", 3306).endswith('port port="3306" protocol="tcp" accept')
