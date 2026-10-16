#!/usr/bin/env python3
"""tera-backup: MariaDB backups with mariabackup (docs/decisions/0012-backup-mariabackup.md).

Installed by Tera as /usr/local/sbin/tera-backup; configuration in /etc/tera/backup/config.json.
Do not edit on the node: changes are overwritten by the next deploy.

Commands:
  run full|incremental   take a backup (incremental falls back to full without a valid chain)
  push                   send backups that are not on every target yet
  verify [--backup ID]   level-2 check: unpack, prepare, start a throwaway mariadbd, CHECK TABLE
  prepare --root DIR --backup ID --out DIR
                         unpack and prepare a chain for restore, then check it like verify
  list                   local backups as JSON
  select --backup ID     the chain needed to restore ID (latest or <chain_id>/<seq>) as JSON
  status                 the status file as JSON

Python 3.9 compatible (EL9).
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

CONFIG_PATH = "/etc/tera/backup/config.json"
FORMAT_VERSION = 1
PAYLOAD = "backup.mbstream.zst"
META = "tera-backup.json"
SUMS = "SHA256SUMS"
CHAIN_RE = re.compile(r"^\d{8}T\d{6}Z$")
BACKUP_RE = re.compile(r"^(\d{2})-(full|incremental)-(\d{8}T\d{6}Z)$")
GIB = 1024**3


class BackupError(Exception):
    """A failure with a message for the operator (Indonesian, like the rest of Tera's output)."""


# --- Pure helpers (unit tested in plugins/tests/test_tera_backup.py) ----------------------------


def stamp(dt: datetime.datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_kv(text: str) -> dict:
    """Parse mariabackup's "key = value" files (mariadb_backup_checkpoints, mariadb_backup_info)."""
    out = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


def valid_prefix(chain: dict) -> list:
    """Backups of a chain that can be restored: 00 full, then incrementals with continuous LSNs."""
    good = []
    for index, backup in enumerate(chain["backups"]):
        meta = backup["meta"]
        if backup["seq"] != index:
            break
        if index == 0:
            if backup["type"] != "full" or meta.get("type") != "full":
                break
        else:
            if backup["type"] != "incremental" or meta.get("type") != "incremental":
                break
            if int(meta.get("from_lsn", -1)) != int(good[-1]["meta"].get("to_lsn", -2)):
                break
        good.append(backup)
    return good


def is_complete(chain: dict) -> bool:
    return len(valid_prefix(chain)) > 0


def plan_prune(chains: list, keep: int) -> list:
    """Chains to delete: everything older than the oldest of the `keep` newest complete chains.

    Count based, never age based (ADR 0012): without enough complete chains nothing is deleted.
    """
    complete = [c for c in chains if is_complete(c)]
    if keep < 1 or len(complete) < keep:
        return []
    oldest_kept = complete[-keep]["chain_id"]
    return [c for c in chains if c["chain_id"] < oldest_kept]


def plan_next(chains: list, requested: str, needs_full: bool) -> dict:
    """Type, chain and parent of the next backup. Incremental needs an intact newest chain."""
    if requested == "incremental" and not needs_full and chains:
        last = chains[-1]
        prefix = valid_prefix(last)
        if prefix and len(prefix) == len(last["backups"]):
            parent = prefix[-1]
            return {
                "type": "incremental",
                "chain_id": last["chain_id"],
                "seq": parent["seq"] + 1,
                "parent": parent,
            }
    return {"type": "full", "chain_id": None, "seq": 0, "parent": None}


def find_backup(chains: list, wanted: str) -> tuple:
    """Resolve "latest" or "<chain_id>/<sequence>" to (chain, prefix up to that backup)."""
    usable = [c for c in chains if is_complete(c)]
    if not usable:
        raise BackupError("tidak ada rantai backup yang lengkap")
    if wanted == "latest":
        chain = usable[-1]
        return chain, valid_prefix(chain)
    chain_id, _, seq = wanted.partition("/")
    if not seq.isdigit():
        raise BackupError(
            f"id backup '{wanted}' tidak valid; gunakan latest atau <chain_id>/<sequence>"
        )
    for chain in chains:
        if chain["chain_id"] == chain_id:
            prefix = valid_prefix(chain)
            if int(seq) < len(prefix):
                return chain, prefix[: int(seq) + 1]
            raise BackupError(
                f"backup {wanted} tidak ada atau rantainya terputus sebelum backup itu "
                f"(bagian rantai yang utuh: {len(prefix)} backup)"
            )
    raise BackupError(f"rantai {chain_id} tidak ditemukan")


def check_tables_output(text: str) -> list:
    """Rows of CHECK TABLE (-N -B) whose result is not OK: [(table, msg_type, msg_text)]."""
    bad = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        table, _op, msg_type, msg_text = parts[:4]
        if msg_type == "status" and msg_text != "OK":
            bad.append((table, msg_type, msg_text))
        elif msg_type == "error":
            bad.append((table, msg_type, msg_text))
    return bad


# --- Filesystem -------------------------------------------------------------------------------


def scan(root: str) -> list:
    """Chains under <backup_dir>/<cluster>, oldest first. Backups without metadata are ignored."""
    chains = []
    if not os.path.isdir(root):
        return chains
    for name in sorted(os.listdir(root)):
        cpath = os.path.join(root, name)
        if not CHAIN_RE.match(name) or not os.path.isdir(cpath):
            continue
        backups = []
        for bname in sorted(os.listdir(cpath)):
            match = BACKUP_RE.match(bname)
            meta_path = os.path.join(cpath, bname, META)
            if not match or not os.path.isfile(meta_path):
                continue
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
            backups.append(
                {
                    "name": bname,
                    "seq": int(match.group(1)),
                    "type": match.group(2),
                    "path": os.path.join(cpath, bname),
                    "meta": meta,
                }
            )
        chains.append({"chain_id": name, "path": cpath, "backups": backups})
    return chains


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    fsync_dir(os.path.dirname(path))


def fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def dir_size(path: str) -> int:
    out = subprocess.run(["du", "-sb", path], capture_output=True, text=True, check=True).stdout
    return int(out.split()[0])


def write_sums(backup_dir: str, payload_name: str) -> str:
    lines = [f"{sha256_file(os.path.join(backup_dir, payload_name))}  {payload_name}"]
    for name in sorted(os.listdir(os.path.join(backup_dir, "lsn"))):
        lines.append(f"{sha256_file(os.path.join(backup_dir, 'lsn', name))}  lsn/{name}")
    with open(os.path.join(backup_dir, SUMS), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return lines[0].split()[0]


def check_sums(backup_dir: str) -> None:
    result = subprocess.run(
        ["sha256sum", "--quiet", "-c", SUMS], cwd=backup_dir, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise BackupError(f"checksum tidak cocok di {backup_dir}: {result.stdout.strip()}")


def relabel(path: str) -> None:
    """Apply the SELinux labels of the policy (mysqld_db_t for .verify/.restore/.incoming, set by
    Tera with semanage fcontext) to directories created here. No-op without SELinux."""
    if shutil.which("selinuxenabled") and subprocess.run(["selinuxenabled"]).returncode == 0:
        subprocess.run(["restorecon", "-R", path], check=True)


def payload_name(meta: dict) -> str:
    return PAYLOAD + (".gpg" if meta.get("encrypted") else "")


# --- Node state -------------------------------------------------------------------------------


class Node:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.root = os.path.join(cfg["backup_dir"], cfg["cluster"])

    def query(self, sql: str) -> str:
        return subprocess.run(
            ["mariadb", "-N", "-B", "-e", sql], capture_output=True, text=True, check=True
        ).stdout

    def global_status(self, names: list) -> dict:
        quoted = ", ".join(f"'{n}'" for n in names)
        out = self.query(f"SHOW GLOBAL STATUS WHERE Variable_name IN ({quoted})")
        return dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)

    def preflight(self) -> None:
        marker = self.cfg["restore_marker"]
        if os.path.exists(marker):
            raise BackupError(
                f"restore sedang berjalan atau terputus (marker {marker} ada). Backup tidak "
                "dibuat dari data yang belum pasti. Selesaikan ./tera restore, atau hapus marker "
                "setelah keadaan "
                "dipastikan."
            )
        try:
            if self.cfg["mode"] == "galera":
                st = self.global_status(["wsrep_local_state", "wsrep_cluster_status"])
                if (
                    st.get("wsrep_local_state") != "4"
                    or st.get("wsrep_cluster_status") != "Primary"
                ):
                    raise BackupError(
                        "node tidak Synced/Primary (wsrep_local_state="
                        f"{st.get('wsrep_local_state')}, wsrep_cluster_status="
                        f"{st.get('wsrep_cluster_status')}); backup dicoba lagi pada "
                        "jadwal berikutnya"
                    )
            else:
                self.query("SELECT 1")
        except subprocess.CalledProcessError as exc:
            raise BackupError(f"MariaDB tidak bisa dihubungi: {exc.stderr.strip()}") from exc

    def lock(self):
        fh = open(self.cfg["lock_path"], "a")  # noqa: SIM115 - held until the process exits
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupError(
                f"backup lain atau operasi Tera lain memegang {self.cfg['lock_path']}"
            ) from exc
        return fh

    # --- status file ---

    def status(self) -> dict:
        try:
            with open(self.cfg["status_path"], encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def update_status(self, fn) -> None:
        data = self.status()
        data.setdefault("format_version", FORMAT_VERSION)
        data["cluster"] = self.cfg["cluster"]
        data["host"] = self.cfg["host"]
        fn(data)
        write_json(self.cfg["status_path"], data)

    def record(self, section: str, key: str, entry: dict) -> None:
        def apply(data):
            data.setdefault(section, {})[key] = entry
            if section == "last" and entry.get("result") == "ok":
                data.setdefault("last_success", {})[key] = entry

        self.update_status(apply)

    # --- backups ---

    def gpg_encrypt_cmd(self) -> list:
        return [
            "gpg", "--homedir", self.cfg["gpg_homedir"], "--batch", "--yes", "--quiet",
            "--trust-model", "always", "--compress-algo", "none",
            "--encrypt", "--recipient", self.cfg["gpg_fingerprint"], "--output", "-",
        ]  # fmt: skip

    def clean_partials(self) -> None:
        for chain in sorted(os.listdir(self.root)) if os.path.isdir(self.root) else []:
            cpath = os.path.join(self.root, chain)
            if not os.path.isdir(cpath) or not CHAIN_RE.match(chain):
                continue
            for name in os.listdir(cpath):
                if name.endswith(".partial"):
                    shutil.rmtree(os.path.join(cpath, name), ignore_errors=True)
            if not os.listdir(cpath):
                os.rmdir(cpath)

    def disk_check(self, plan: dict, chains: list) -> int:
        datadir_size = dir_size(self.cfg["datadir"])
        if plan["type"] == "full":
            need = datadir_size
        else:
            last_inc = [
                b["meta"].get("size_bytes", 0) for c in chains[-1:] for b in c["backups"][1:]
            ]
            need = max(GIB, 2 * (last_inc[-1] if last_inc else 0))
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        free = shutil.disk_usage(self.root).free
        if free < need:
            raise BackupError(
                f"ruang bebas di {self.cfg['backup_dir']} {free // 1024**2} MiB, butuh minimal "
                f"{need // 1024**2} MiB untuk backup {plan['type']}; backup tidak dimulai"
            )
        return datadir_size

    def take(self, plan: dict, datadir_size: int) -> dict:
        started = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        chain_id = plan["chain_id"] or stamp(started)
        name = f"{plan['seq']:02d}-{plan['type']}-{stamp(started)}"
        chain_dir = os.path.join(self.root, chain_id)
        os.makedirs(chain_dir, mode=0o700, exist_ok=True)
        work = os.path.join(chain_dir, name + ".partial")
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(os.path.join(work, "lsn"))
        tmpdir = os.path.join(work, "tmp")
        os.makedirs(tmpdir)
        encrypted = bool(self.cfg["encrypt_local"])
        pname = PAYLOAD + (".gpg" if encrypted else "")

        cmd = [
            "mariabackup", "--backup", "--user=root", "--stream=mbstream",
            f"--target-dir={tmpdir}", f"--extra-lsndir={work}/lsn",
        ]  # fmt: skip
        if self.cfg["mode"] == "galera":
            cmd.append("--galera-info")
        if plan["type"] == "incremental":
            cmd.append(f"--incremental-basedir={plan['parent']['path']}/lsn")
        if self.cfg.get("throttle"):
            cmd.append(f"--throttle={int(self.cfg['throttle'])}")

        log_path = os.path.join(work, "mariabackup.log")
        with open(log_path, "w") as log, open(os.path.join(work, pname), "wb") as out:
            procs = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log)]
            zstd_out = subprocess.PIPE if encrypted else out
            procs.append(
                subprocess.Popen(
                    ["zstd", "-q", "-T0", "-c"], stdin=procs[0].stdout, stdout=zstd_out
                )
            )
            procs[0].stdout.close()
            if encrypted:
                procs.append(
                    subprocess.Popen(self.gpg_encrypt_cmd(), stdin=procs[1].stdout, stdout=out)
                )
                procs[1].stdout.close()
            rcs = [p.wait() for p in procs]
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            log_text = fh.read()
        if any(rcs) or "completed OK!" not in log_text:
            tail = " | ".join(log_text.strip().splitlines()[-3:])
            raise BackupError(f"backup gagal (rc mariabackup/zstd/gpg = {rcs}): {tail}")
        shutil.rmtree(tmpdir)

        with open(os.path.join(work, "lsn", "mariadb_backup_checkpoints"), encoding="utf-8") as fh:
            checkpoints = parse_kv(fh.read())
        with open(os.path.join(work, "lsn", "mariadb_backup_info"), encoding="utf-8") as fh:
            info = parse_kv(fh.read())
        if plan["type"] == "incremental":
            parent_to = int(plan["parent"]["meta"]["to_lsn"])
            if int(checkpoints["from_lsn"]) != parent_to:
                raise BackupError(
                    f"from_lsn {checkpoints['from_lsn']} tidak sama dengan to_lsn parent "
                    f"{parent_to}"
                )
        sha = write_sums(work, pname)
        finished = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        meta = {
            "format_version": FORMAT_VERSION,
            "cluster": self.cfg["cluster"],
            "mode": self.cfg["mode"],
            "host": self.cfg["host"],
            "type": plan["type"],
            "chain_id": chain_id,
            "sequence": plan["seq"],
            "parent": (f"{chain_id}/{plan['parent']['name']}" if plan["parent"] else None),
            "started_at": iso(started),
            "finished_at": iso(finished),
            "mariadb_version": info.get("server_version", ""),
            "from_lsn": int(checkpoints["from_lsn"]),
            "to_lsn": int(checkpoints["to_lsn"]),
            "compression": "zstd",
            "encrypted": encrypted,
            "gpg_fingerprint": self.cfg["gpg_fingerprint"] if encrypted else None,
            "size_bytes": os.path.getsize(os.path.join(work, pname)),
            "sha256": sha,
            "datadir_size_bytes": datadir_size,
        }
        write_json(os.path.join(work, META), meta)
        # Level 1: read the payload back and compare with the recorded checksums.
        check_sums(work)
        final = os.path.join(chain_dir, name)
        os.rename(work, final)
        fsync_dir(chain_dir)
        return {"name": name, "seq": plan["seq"], "type": plan["type"], "path": final, "meta": meta}

    def prune(self) -> list:
        removed = []
        for chain in plan_prune(scan(self.root), int(self.cfg["keep_full"])):
            shutil.rmtree(chain["path"])
            removed.append(chain["chain_id"])
        return removed

    # --- targets ---

    def push_all(self) -> dict:
        """Push every valid backup that is not on a target yet. Returns {target: error or None}."""
        results = {}
        for target in self.cfg["targets"]:
            try:
                count = 0
                for chain in scan(self.root):
                    for backup in valid_prefix(chain):
                        marker = os.path.join(backup["path"], f".pushed-{target['name']}")
                        if os.path.exists(marker):
                            continue
                        self.push_one(target, chain, backup)
                        with open(marker, "w", encoding="utf-8") as fh:
                            fh.write(iso(datetime.datetime.now(datetime.timezone.utc)) + "\n")
                        count += 1
                results[target["name"]] = None
                self.record(
                    "targets", target["name"],
                    {"result": "ok", "at": iso(datetime.datetime.now(datetime.timezone.utc)),
                     "pushed": count},
                )  # fmt: skip
            except (BackupError, OSError, subprocess.CalledProcessError) as exc:
                results[target["name"]] = str(exc)
                self.record(
                    "targets", target["name"],
                    {"result": "failed", "at": iso(datetime.datetime.now(datetime.timezone.utc)),
                     "message": str(exc)},
                )  # fmt: skip
        return results

    def push_one(self, target: dict, chain: dict, backup: dict) -> None:
        rel = f"{chain['chain_id']}/{backup['name']}"
        outgoing = os.path.join(self.cfg["backup_dir"], ".outgoing")
        try:
            if backup["meta"].get("encrypted"):
                root = self.root
            else:
                # Remote copies are always encrypted (ADR 0012): encrypt into .outgoing first.
                root = outgoing
                self.encrypt_copy(backup, os.path.join(outgoing, rel))
            env = dict(os.environ)
            env.update(
                {
                    "TERA_TARGET_ADDRESS": target["address"],
                    "TERA_TARGET_USER": target["user"],
                    "TERA_TARGET_PORT": str(target.get("port", 22)),
                    "TERA_TARGET_SSH_KEY": self.cfg["ssh_key"],
                    "TERA_TARGET_KNOWN_HOSTS": self.cfg["known_hosts"],
                }
            )
            script = os.path.join(self.cfg["target_bin_dir"], target["type"])
            result = subprocess.run(
                [script, "push", root, rel], env=env, capture_output=True, text=True
            )
            if result.returncode != 0:
                raise BackupError(
                    f"push {rel} ke {target['name']} gagal: {result.stderr.strip()[-500:]}"
                )
        finally:
            shutil.rmtree(os.path.join(outgoing, chain["chain_id"]), ignore_errors=True)

    def encrypt_copy(self, backup: dict, out: str) -> None:
        size = backup["meta"]["size_bytes"]
        free = shutil.disk_usage(self.cfg["backup_dir"]).free
        if free < size * 1.05:
            raise BackupError(
                f"ruang bebas {free // 1024**2} MiB tidak cukup untuk salinan terenkripsi "
                f"{size // 1024**2} MiB di .outgoing"
            )
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out, mode=0o700)
        shutil.copytree(os.path.join(backup["path"], "lsn"), os.path.join(out, "lsn"))
        enc_name = PAYLOAD + ".gpg"
        with open(os.path.join(backup["path"], PAYLOAD), "rb") as src:
            with open(os.path.join(out, enc_name), "wb") as dst:
                result = subprocess.run(
                    self.gpg_encrypt_cmd(), stdin=src, stdout=dst, stderr=subprocess.PIPE
                )
        if result.returncode != 0:
            raise BackupError(
                f"enkripsi gpg gagal: {result.stderr.decode(errors='replace').strip()[-300:]}"
            )
        meta = dict(backup["meta"])
        meta["encrypted"] = True
        meta["gpg_fingerprint"] = self.cfg["gpg_fingerprint"]
        meta["size_bytes"] = os.path.getsize(os.path.join(out, enc_name))
        meta["sha256"] = write_sums(out, enc_name)
        write_json(os.path.join(out, META), meta)

    # --- level 2 ---

    def restore_chain(self, prefix: list, workdir: str, gpg_homedir: str | None) -> str:
        """Unpack and prepare a chain into workdir/00. Returns the prepared directory."""
        for backup in prefix:
            meta = backup["meta"]
            payload = os.path.join(backup["path"], payload_name(meta))
            if sha256_file(payload) != meta["sha256"]:
                raise BackupError(f"sha256 payload {backup['name']} tidak cocok dengan metadata")
            dest = os.path.join(workdir, f"{backup['seq']:02d}")
            os.makedirs(dest)
            with open(payload, "rb") as src:
                stages = []
                if meta.get("encrypted"):
                    if not gpg_homedir:
                        raise BackupError(
                            f"{backup['name']} terenkripsi; butuh private key gpg untuk membukanya"
                        )
                    stages.append(["gpg", "--homedir", gpg_homedir, "--batch", "--quiet",
                                   "--decrypt"])  # fmt: skip
                stages.append(["zstd", "-q", "-dc"])
                stages.append(["mbstream", "-x", "-C", dest])
                procs = []
                stdin = src
                for index, cmd in enumerate(stages):
                    last = index == len(stages) - 1
                    proc = subprocess.Popen(
                        cmd, stdin=stdin, stdout=None if last else subprocess.PIPE
                    )
                    if procs:
                        procs[-1].stdout.close()
                    procs.append(proc)
                    stdin = proc.stdout
                rcs = [p.wait() for p in procs]
            if any(rcs):
                raise BackupError(f"gagal membongkar {backup['name']} (rc {rcs})")
        full = os.path.join(workdir, "00")
        self.mariabackup_prepare(full, None)
        for backup in prefix[1:]:
            self.mariabackup_prepare(full, os.path.join(workdir, f"{backup['seq']:02d}"))
        return full

    @staticmethod
    def mariabackup_prepare(target: str, incremental: str | None) -> None:
        cmd = ["mariabackup", "--prepare", f"--target-dir={target}"]
        if incremental:
            cmd.append(f"--incremental-dir={incremental}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            tail = " | ".join(result.stderr.strip().splitlines()[-3:])
            raise BackupError(f"mariabackup --prepare gagal: {tail}")

    def check_with_server(self, datadir: str) -> int:
        """Start a throwaway mariadbd on the prepared datadir and CHECK every table."""
        # Runs as mysql (ADR 0014), without networking, socket inside the copy. The copy goes to
        # mysql; Tera's work directories between backup_dir and the copy only get traverse (0711).
        base = os.path.dirname(datadir)
        sockdir = os.path.join(base, "run")
        os.makedirs(sockdir, exist_ok=True)
        subprocess.run(["chown", "-R", "mysql:mysql", base], check=True)
        parent = os.path.dirname(base)
        root = os.path.realpath(self.cfg["backup_dir"])
        while os.path.realpath(parent).startswith(root + os.sep):
            os.chmod(parent, os.stat(parent).st_mode | 0o011)
            parent = os.path.dirname(parent)
        relabel(os.path.dirname(datadir))
        sock = os.path.join(sockdir, "verify.sock")
        log = os.path.join(sockdir, "verify.err")
        server = subprocess.Popen(
            [
                "mariadbd",
                "--no-defaults",
                "--user=mysql",
                f"--datadir={datadir}",
                f"--socket={sock}",
                "--skip-networking",
                f"--pid-file={sockdir}/verify.pid",
                f"--log-error={log}",
                "--innodb-buffer-pool-size=128M",
            ]  # fmt: skip
        )
        try:
            for _ in range(120):
                if os.path.exists(sock) or server.poll() is not None:
                    break
                time.sleep(1)
            if not os.path.exists(sock):
                tail = ""
                if os.path.exists(log):
                    with open(log, encoding="utf-8", errors="replace") as fh:
                        tail = " | ".join(fh.read().strip().splitlines()[-3:])
                raise BackupError(f"mariadbd sementara tidak menyala: {tail}")

            def query(sql):
                return subprocess.run(
                    ["mariadb", "-S", sock, "-N", "-B", "-e", sql],
                    capture_output=True, text=True, check=True,
                ).stdout  # fmt: skip

            tables = query(
                "SELECT CONCAT('`', table_schema, '`.`', table_name, '`')"
                " FROM information_schema.tables"
                " WHERE table_type = 'BASE TABLE' AND table_schema NOT IN"
                " ('information_schema', 'performance_schema', 'sys')"
                " AND engine IN ('InnoDB', 'Aria', 'MyISAM')"
            ).split()
            bad = []
            for start in range(0, len(tables), 50):
                bad += check_tables_output(
                    query("CHECK TABLE " + ", ".join(tables[start : start + 50]))
                )
            if bad:
                raise BackupError(f"CHECK TABLE gagal: {bad[:5]}")
            return len(tables)
        finally:
            if server.poll() is None:
                subprocess.run(["mariadb-admin", "-S", sock, "shutdown"], capture_output=True)
                try:
                    server.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


# --- Commands ---------------------------------------------------------------------------------


def now() -> str:
    return iso(datetime.datetime.now(datetime.timezone.utc))


def cmd_run(node: Node, args) -> int:
    started = now()
    _lock = None
    try:
        node.preflight()
        _lock = node.lock()
        node.preflight()  # a restore may have started while we waited for nothing
        node.clean_partials()
        chains = scan(node.root)
        needs_full = os.path.exists(node.cfg["needs_full_path"])
        plan = plan_next(chains, args.type, needs_full)
        datadir_size = node.disk_check(plan, chains)
        backup = node.take(plan, datadir_size)
    except (BackupError, OSError, subprocess.CalledProcessError) as exc:
        node.record("last", args.type, {"result": "failed", "started_at": started,
                                         "finished_at": now(), "message": str(exc)})  # fmt: skip
        print(f"tera-backup: {exc}", file=sys.stderr)
        return 1
    entry = {
        "result": "ok", "started_at": started, "finished_at": now(),
        "backup": f"{backup['meta']['chain_id']}/{backup['seq']}", "name": backup["name"],
        "type": backup["type"], "size_bytes": backup["meta"]["size_bytes"],
    }  # fmt: skip
    node.record("last", args.type, entry)
    if backup["type"] != args.type:
        node.record("last", backup["type"], entry)
    print(
        f"tera-backup: {backup['type']} {entry['backup']} ({backup['meta']['size_bytes']} byte) OK"
    )
    if backup["type"] == "full":
        if os.path.exists(node.cfg["needs_full_path"]):
            os.remove(node.cfg["needs_full_path"])
        removed = node.prune()
        if removed:
            print(f"tera-backup: retensi menghapus rantai {', '.join(removed)}")
    failed = {k: v for k, v in node.push_all().items() if v}
    if backup["type"] == "full" and node.cfg["verify_after_full"]:
        subprocess.run(["systemctl", "start", "--no-block", node.cfg["verify_unit"]], check=False)
    if failed:
        for name, error in failed.items():
            print(f"tera-backup: backup lokal OK, push ke {name} gagal: {error}", file=sys.stderr)
        return 2
    return 0


def cmd_push(node: Node, args) -> int:
    _lock = node.lock()
    failed = {k: v for k, v in node.push_all().items() if v}
    for name, error in failed.items():
        print(f"tera-backup: push ke {name} gagal: {error}", file=sys.stderr)
    return 2 if failed else 0


def cmd_verify(node: Node, args) -> int:
    chains = scan(node.root)
    try:
        if args.backup:
            chain, prefix = find_backup(chains, args.backup)
        else:
            chain, prefix = find_backup(chains, "latest")
    except BackupError as exc:
        node.record("verify", "last", {"result": "failed", "at": now(), "message": str(exc)})
        print(f"tera-backup: {exc}", file=sys.stderr)
        return 1
    backup_id = f"{chain['chain_id']}/{prefix[-1]['seq']}"
    if any(b["meta"].get("encrypted") for b in prefix) and not args.gpg_homedir:
        message = "backup terenkripsi; verifikasi otomatis butuh private key (tera backup-verify)"
        node.record("verify", "last", {"result": "skipped", "at": now(), "backup": backup_id,
                                       "message": message})  # fmt: skip
        print(f"tera-backup: {message}")
        return 0 if args.auto else 1
    need = int(prefix[0]["meta"].get("datadir_size_bytes", 0) * 1.2) + sum(
        b["meta"]["size_bytes"] for b in prefix
    )
    work_root = os.path.join(node.cfg["backup_dir"], ".verify")
    os.makedirs(work_root, mode=0o700, exist_ok=True)
    free = shutil.disk_usage(work_root).free
    if free < need:
        message = (
            f"ruang sementara tidak cukup ({free // 1024**2} MiB bebas, "
            f"butuh {need // 1024**2} MiB); "
            "verifikasi dilewati"
        )
        node.record("verify", "last", {"result": "warning", "at": now(), "backup": backup_id,
                                       "message": message})  # fmt: skip
        print(f"tera-backup: {message}")
        return 0
    workdir = tempfile.mkdtemp(prefix="verify-", dir=work_root)
    try:
        prepared = node.restore_chain(prefix, os.path.join(workdir, "data"), args.gpg_homedir)
        tables = node.check_with_server(prepared)
    except (BackupError, OSError, subprocess.CalledProcessError) as exc:
        node.record("verify", "last", {"result": "failed", "at": now(), "backup": backup_id,
                                       "message": str(exc)})  # fmt: skip
        print(f"tera-backup: verifikasi {backup_id} gagal: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    node.record("verify", "last", {"result": "ok", "at": now(), "backup": backup_id,
                                   "tables": tables})  # fmt: skip
    print(f"tera-backup: verifikasi {backup_id} OK ({tables} tabel)")
    return 0


def cmd_prepare(node: Node, args) -> int:
    """Restore helper: unpack and prepare a chain from a staging tree, then check it."""
    try:
        chain, prefix = find_backup(scan(args.root), args.backup)
        for backup in prefix:
            check_sums(backup["path"])
        os.makedirs(args.out, mode=0o700, exist_ok=True)
        prepared = node.restore_chain(prefix, os.path.join(args.out, "data"), args.gpg_homedir)
        tables = node.check_with_server(prepared)
    except (BackupError, OSError, subprocess.CalledProcessError) as exc:
        print(f"tera-backup: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps({"prepared": prepared, "tables": tables, "chain": [b["meta"] for b in prefix]})
    )
    return 0


def cmd_list(node: Node, args) -> int:
    root = args.root or node.root
    chains = scan(root)
    out = []
    for chain in chains:
        prefix = {b["name"] for b in valid_prefix(chain)}
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


def selection(chains: list, wanted: str) -> dict:
    """The chain prefix needed to restore `wanted`, as JSON-able data (used by tera restore)."""
    chain, prefix = find_backup(chains, wanted)
    return {
        "chain_id": chain["chain_id"],
        "id": f"{chain['chain_id']}/{prefix[-1]['seq']}",
        "backups": [{"name": b["name"], "path": b["path"], "meta": b["meta"]} for b in prefix],
    }


def cmd_select(node: Node, args) -> int:
    try:
        out = selection(scan(args.root or node.root), args.backup)
    except BackupError as exc:
        print(f"tera-backup: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def cmd_status(node: Node, args) -> int:
    print(json.dumps(node.status(), indent=2, sort_keys=True))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tera-backup")
    parser.add_argument("--config", default=CONFIG_PATH)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("type", choices=["full", "incremental"])
    sub.add_parser("push")
    verify = sub.add_parser("verify")
    verify.add_argument("--backup")
    verify.add_argument("--gpg-homedir")
    verify.add_argument("--auto", action="store_true")
    prep = sub.add_parser("prepare")
    prep.add_argument("--root", required=True)
    prep.add_argument("--backup", required=True)
    prep.add_argument("--out", required=True)
    prep.add_argument("--gpg-homedir")
    lst = sub.add_parser("list")
    lst.add_argument("--root")
    sel = sub.add_parser("select")
    sel.add_argument("--root")
    sel.add_argument("--backup", required=True)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    with open(args.config, encoding="utf-8") as fh:
        node = Node(json.load(fh))
    os.umask(0o077)
    handlers = {
        "run": cmd_run, "push": cmd_push, "verify": cmd_verify, "prepare": cmd_prepare,
        "list": cmd_list,
        "select": cmd_select, "status": cmd_status,
    }  # fmt: skip
    return handlers[args.command](node, args)


if __name__ == "__main__":
    sys.exit(main())
