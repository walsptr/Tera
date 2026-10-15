"""Molecule loadbalancer scenario (test only): probe the VIP from the Molecule host.

Every 0.2 s open a TCP connection to <host>:<port> and read the MariaDB greeting (sent by the
backend through HAProxy). Each line: "<epoch> ok" or "<epoch> fail". Runs until killed.
Usage: probe.py <host> <port> <log>
"""

import socket
import sys
import time


def probe(host, port):
    try:
        with socket.create_connection((host, port), timeout=1) as conn:
            conn.settimeout(1)
            return b"MariaDB" in conn.recv(256)
    except OSError:
        return False


def main(argv):
    host, port, path = argv[1], int(argv[2]), argv[3]
    with open(path, "w", encoding="utf-8", buffering=1) as log:
        while True:
            log.write(f"{time.time():.3f} {'ok' if probe(host, port) else 'fail'}\n")
            time.sleep(0.2)


if __name__ == "__main__":
    main(sys.argv)
