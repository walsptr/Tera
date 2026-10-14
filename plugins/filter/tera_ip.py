"""IPv4 checks for prechecks (stdlib ipaddress only, no netaddr).

Usage in a task:

    {{ tera_vip_address | tera_is_ipv4 }}
    {{ mariadb_client_sources | map('tera_is_ipv4_network') | list }}
    {{ tera_vip_address | tera_ipv4_in_network('10.77.0.0/24') }}
    {{ mariadb_client_sources | map('tera_fw_rich_rule', '3306/tcp') | list }}

The checks return a boolean and never raise on bad input, so prechecks can print a clear message
instead of a Python traceback. tera_fw_rich_rule formats a firewalld rich rule exactly as firewalld
lists it back, so roles can compare expected and current rules as text (ADR 0011).
Tests: plugins/tests/test_tera_ip.py.
"""

from __future__ import annotations

import ipaddress


def tera_is_ipv4(value):
    """True for a single IPv4 address such as "10.0.0.5" (no prefix)."""
    if not isinstance(value, str) or "/" in value:
        return False
    try:
        ipaddress.IPv4Address(value.strip())
    except ValueError:
        return False
    return True


def tera_is_ipv4_network(value):
    """True for an IPv4 network in CIDR form without host bits ("10.0.0.0/24").

    A single address is accepted as a /32 network ("10.0.0.5"). "10.0.0.5/24" is refused because
    the host bits are set: write "10.0.0.0/24" or "10.0.0.5/32".
    """
    if not isinstance(value, str):
        return False
    try:
        ipaddress.IPv4Network(value.strip(), strict=True)
    except ValueError:
        return False
    return True


def tera_ipv4_in_network(address, network):
    """True when ``address`` is inside ``network``.

    ``network`` may be "10.0.0.0/24", "10.0.0.0/255.255.255.0" (Ansible facts give network and
    netmask) or carry host bits ("10.0.0.7/24", as an interface address).
    """
    if not tera_is_ipv4(address) or not isinstance(network, str):
        return False
    try:
        net = ipaddress.IPv4Network(network.strip(), strict=False)
    except ValueError:
        return False
    return ipaddress.IPv4Address(address.strip()) in net


def tera_fw_rich_rule(source, port_spec=None):
    """firewalld rich rule accepting ``port_spec`` ("3306/tcp") from ``source`` (IPv4 or CIDR).

    ``source`` may also be a ``[source, port_spec]`` pair (e.g. from ``product``).
    """
    if port_spec is None and isinstance(source, (list, tuple)) and len(source) == 2:
        source, port_spec = source
    port, _, proto = str(port_spec).partition("/")
    return (
        f'rule family="ipv4" source address="{str(source).strip()}" '
        f'port port="{port}" protocol="{proto or "tcp"}" accept'
    )


class FilterModule:
    def filters(self):
        return {
            "tera_is_ipv4": tera_is_ipv4,
            "tera_is_ipv4_network": tera_is_ipv4_network,
            "tera_ipv4_in_network": tera_ipv4_in_network,
            "tera_fw_rich_rule": tera_fw_rich_rule,
        }
