"""Check VIP availability and ownership during the failover steps (Molecule loadbalancer scenario).

Usage: check_failover.py <max_downtime_s> <events.log> <probe.log> <name>=<vip-monitor.log> ...

events.log lines: "<epoch start> <epoch end> <event name>" (controller clock, like probe.log).
For each event: the longest run of consecutive failed probes inside [start, end] must be at most
<max_downtime_s>. Across all monitors: never two nodes holding the VIP at the same time (samples
closer than SKEW_S are compared, to absorb clock differences between VMs).
"""

import sys

SKEW_S = 0.3


def read_pairs(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) >= 2:
                rows.append((float(parts[0]), parts[1]))
    return rows


def longest_failure(probes, start, end):
    longest = 0.0
    fail_start = None
    last_ok = start
    for ts, state in probes:
        if ts < start or ts > end:
            continue
        if state == "fail":
            if fail_start is None:
                fail_start = last_ok
        else:
            if fail_start is not None:
                longest = max(longest, ts - fail_start)
                fail_start = None
            last_ok = ts
    if fail_start is not None:
        longest = max(longest, end - fail_start)
    return longest


def holders_overlap(monitors):
    held = []
    for name, rows in monitors.items():
        held.extend((ts, name) for ts, state in rows if state == "1")
    held.sort()
    clashes = []
    for (ts1, n1), (ts2, n2) in zip(held, held[1:], strict=False):
        if n1 != n2 and ts2 - ts1 < SKEW_S:
            clashes.append(f"{n1} and {n2} both held the VIP around {ts1:.3f}")
    return clashes


def main(argv):
    max_down = float(argv[1])
    with open(argv[2], encoding="utf-8") as handle:
        events = [line.split(maxsplit=2) for line in handle if line.strip()]
    probes = read_pairs(argv[3])
    monitors = {arg.split("=", 1)[0]: read_pairs(arg.split("=", 1)[1]) for arg in argv[4:]}

    errors = []
    for start, end, name in events:
        down = longest_failure(probes, float(start), float(end))
        print(f"{name.strip()}: downtime {down:.1f} s")
        if down > max_down:
            errors.append(f"{name.strip()}: downtime {down:.1f} s > {max_down:.0f} s")
    clashes = holders_overlap(monitors)
    errors.extend(clashes[:10])
    print(f"split brain samples: {len(clashes)}")
    for error in errors:
        print(f"ERROR {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
