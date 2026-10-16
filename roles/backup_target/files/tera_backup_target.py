#!/usr/bin/env python3
"""tera-backup-target: checks and retention on a Tera backup host (ADR 0012).

Nodes can only write here (rrsync -wo -no-del), so this host verifies what arrived and applies the
retention itself. State lives outside the directories the nodes can write to, so a node cannot fake
a verification.

Commands (run as the backup user):
  run                      verify new backups (sha256sum -c) and prune old chains, every cluster
  list --cluster C --host H
                           verified backups of one node as JSON
  select --cluster C --host H --backup ID
                           verified chain needed to restore ID, as JSON (used by tera restore)

Python 3.9 compatible (EL9). Uses tera_backup.py (same file as on the nodes) for chain logic.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, "/usr/local/lib/tera")
import tera_backup as tb  # noqa: E402

CONFIG_DIR = "/etc/tera/backup-target"


def state_path(cfg: dict, cluster: str, host: str, chain_id: str, name: str, kind: str) -> str:
    return os.path.join(cfg["state_dir"], cluster, host, chain_id, f"{name}.{kind}")


def verified_chains(cfg: dict, cluster: str, host: str) -> list:
    """Chains of a node keeping only backups that passed the checksum check."""
    chains = tb.scan(os.path.join(cfg["dir"], cluster, host))
    for chain in chains:
        chain["backups"] = [
            b
            for b in chain["backups"]
            if os.path.exists(
                state_path(cfg, cluster, host, chain["chain_id"], b["name"], "verified")
            )
        ]
    return chains


def verify_new(cfg: dict, cluster: str, host: str) -> list:
    results = []
    for chain in tb.scan(os.path.join(cfg["dir"], cluster, host)):
        for backup in chain["backups"]:
            ok_path = state_path(cfg, cluster, host, chain["chain_id"], backup["name"], "verified")
            bad_path = state_path(cfg, cluster, host, chain["chain_id"], backup["name"], "failed")
            if os.path.exists(ok_path) or os.path.exists(bad_path):
                continue
            os.makedirs(os.path.dirname(ok_path), exist_ok=True)
            check = subprocess.run(
                ["sha256sum", "--quiet", "-c", tb.SUMS],
                cwd=backup["path"], capture_output=True, text=True,
            )  # fmt: skip
            target = ok_path if check.returncode == 0 else bad_path
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(check.stdout)
            results.append(
                (f"{cluster}/{host}/{chain['chain_id']}/{backup['name']}", check.returncode)
            )
    return results


def prune(cfg: dict, cluster: str, host: str) -> list:
    removed = []
    for chain in tb.plan_prune(verified_chains(cfg, cluster, host), int(cfg["keep_full"])):
        shutil.rmtree(chain["path"])
        shutil.rmtree(
            os.path.join(cfg["state_dir"], cluster, host, chain["chain_id"]), ignore_errors=True
        )
        removed.append(f"{cluster}/{host}/{chain['chain_id']}")
    return removed


def configs(config_dir: str) -> dict:
    out = {}
    for path in sorted(glob.glob(os.path.join(config_dir, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        out[cfg["cluster"]] = cfg
    return out


def cmd_run(args) -> int:
    rc = 0
    for cluster, cfg in configs(args.config_dir).items():
        cluster_dir = os.path.join(cfg["dir"], cluster)
        if not os.path.isdir(cluster_dir):
            continue
        for host in sorted(os.listdir(cluster_dir)):
            for name, code in verify_new(cfg, cluster, host):
                print(f"{name}: {'OK' if code == 0 else 'CHECKSUM GAGAL'}")
                rc = rc or (1 if code else 0)
            for name in prune(cfg, cluster, host):
                print(f"{name}: dihapus oleh retensi")
    return rc


def cmd_list(args) -> int:
    cfg = configs(args.config_dir).get(args.cluster)
    if cfg is None:
        print(f"cluster {args.cluster} tidak dikenal di host backup ini", file=sys.stderr)
        return 1
    out = []
    for chain in verified_chains(cfg, args.cluster, args.host):
        prefix = {b["name"] for b in tb.valid_prefix(chain)}
        out.append(
            {
                "chain_id": chain["chain_id"],
                "path": chain["path"],
                "backups": [
                    {
                        "name": b["name"],
                        "path": b["path"],
                        "valid": b["name"] in prefix,
                        "meta": b["meta"],
                    }
                    for b in chain["backups"]
                ],
            }  # fmt: skip
        )
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def cmd_select(args) -> int:
    cfg = configs(args.config_dir).get(args.cluster)
    if cfg is None:
        print(f"cluster {args.cluster} tidak dikenal di host backup ini", file=sys.stderr)
        return 1
    try:
        out = tb.selection(verified_chains(cfg, args.cluster, args.host), args.backup)
    except tb.BackupError as exc:
        print(f"tera-backup-target: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tera-backup-target")
    parser.add_argument("--config-dir", default=CONFIG_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    lst = sub.add_parser("list")
    lst.add_argument("--cluster", required=True)
    lst.add_argument("--host", required=True)
    sel = sub.add_parser("select")
    sel.add_argument("--cluster", required=True)
    sel.add_argument("--host", required=True)
    sel.add_argument("--backup", required=True)
    args = parser.parse_args(argv)
    os.umask(0o027)
    return {"run": cmd_run, "list": cmd_list, "select": cmd_select}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
