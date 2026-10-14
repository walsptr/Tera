"""Check a Galera rolling restart from per-node monitor logs (Molecule reconfigure scenario).

Each log line: "<epoch.ns> <cluster_size> <cluster_status> <local_state>" or "<epoch.ns> down"
(written by tera-monitor.sh).
Usage: check_rolling.py <expected order, comma separated> <name>=<log> [<name>=<log> ...]

Checks:
- every Synced sample (local_state 4) reports a Primary cluster of size >= 2, except a node's own
  view within TRANSITION_S seconds of its own restart (leaving/joining);
- during every second of the run at least one node is Synced with size >= 2;
- each node has exactly one down interval, intervals do not overlap, and their order
  matches the expected order (one node restarted at a time).
"""

import math
import sys

# Seconds around a node's own down interval in which its own non-Primary view is tolerated.
TRANSITION_S = 5


def parse(path):
    samples = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if not parts:
                continue
            ts = float(parts[0])
            if parts[1:] == ["down"]:
                samples.append((ts, None, None, None))
            elif len(parts) == 4 and parts[1].isdigit() and parts[3].isdigit():
                samples.append((ts, int(parts[1]), parts[2], int(parts[3])))
            else:
                # Server answered but wsrep values are not available yet: up, not Synced.
                samples.append((ts, 0, "unknown", -1))
    return samples


def down_intervals(samples):
    intervals = []
    start = None
    last = None
    for ts, size, _status, _state in samples:
        if size is None:
            if start is None:
                start = ts
            last = ts
        elif start is not None:
            intervals.append((start, last))
            start = None
    if start is not None:
        intervals.append((start, last))
    return intervals


def main(argv):
    expected = argv[1].split(",")
    logs = dict(arg.split("=", 1) for arg in argv[2:])
    errors = []
    samples = {name: parse(path) for name, path in logs.items()}

    intervals_by_node = {name: down_intervals(rows) for name, rows in samples.items()}

    # A node that is shutting down or starting may briefly report its own view as non-Primary
    # (e.g. "Disconnected", size 0) while wsrep_local_state still reads 4. That is the restarting
    # node itself, not the cluster: tolerated only close to that node's own down interval.
    transitions = 0
    for name, rows in samples.items():
        for ts, size, status, state in rows:
            if state == 4 and (status != "Primary" or size < 2):
                own = intervals_by_node[name]
                if any(start - TRANSITION_S <= ts <= stop + TRANSITION_S for start, stop in own):
                    transitions += 1
                else:
                    errors.append(f"{name} at {ts:.3f}: Synced but status={status} size={size}")

    begin = max(rows[0][0] for rows in samples.values())
    end = min(rows[-1][0] for rows in samples.values())
    healthy_seconds = {
        math.floor(ts)
        for rows in samples.values()
        for ts, size, status, state in rows
        if state == 4 and status == "Primary" and size >= 2
    }
    for second in range(math.ceil(begin), math.floor(end)):
        if second not in healthy_seconds:
            errors.append(f"no Synced node with cluster size >= 2 during second {second}")

    windows = []
    for name, intervals in intervals_by_node.items():
        if len(intervals) != 1:
            errors.append(f"{name}: expected exactly one down interval, found {len(intervals)}")
        windows.extend((start, stop, name) for start, stop in intervals)
    windows.sort()
    for (_s1, stop1, name1), (start2, _s2, name2) in zip(windows, windows[1:], strict=False):
        if start2 <= stop1:
            errors.append(f"{name1} and {name2} were down at the same time")
    order = [name for _start, _stop, name in windows]
    if order != expected:
        errors.append(f"restart order {order}, expected {expected}")

    for error in errors[:20]:
        print(error)
    if len(errors) > 20:
        print(f"... {len(errors) - 20} more errors")
    print(f"down windows: {[(name, round(stop - start, 1)) for start, stop, name in windows]}")
    print(f"own-restart transition samples tolerated: {transitions}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
