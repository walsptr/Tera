"""Molecule upgrade scenario (test only): summarize the VIP probe and the writer logs as JSON.

probe.log lines: "<epoch> ok|fail" (molecule/loadbalancer/files/probe.py).
writer.log lines: "<epoch> ok <node>" or "<epoch> fail <error>" (files/writer.sh).
Usage: check_upgrade.py <probe.log> <writer.log>
"""

import json
import sys


def longest_outage(lines):
    """Longest time between the last ok before a run of fails and the first ok after it."""
    longest, last_ok, failing = 0.0, None, False
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        ts, ok = float(parts[0]), parts[1] == "ok"
        if ok:
            if failing and last_ok is not None:
                longest = max(longest, ts - last_ok)
            last_ok, failing = ts, False
        else:
            failing = True
    return round(longest, 3)


def main(argv):
    with open(argv[1], encoding="utf-8") as fh:
        probe = fh.read().splitlines()
    with open(argv[2], encoding="utf-8") as fh:
        writer = fh.read().splitlines()
    oks = [line.split()[2] for line in writer if len(line.split()) > 2 and line.split()[1] == "ok"]
    fails = [line for line in writer if len(line.split()) > 1 and line.split()[1] == "fail"]
    writers = []
    for node in oks:
        if not writers or writers[-1] != node:
            writers.append(node)
    print(json.dumps({
        "probe_lines": len(probe),
        "probe_longest_outage_s": longest_outage(probe),
        "writer_ok": len(oks),
        "writer_fail": len(fails),
        "writer_fail_lines": fails[:10],
        "writer_longest_outage_s": longest_outage(writer),
        "writer_sequence": writers,
    }))


if __name__ == "__main__":
    main(sys.argv)
