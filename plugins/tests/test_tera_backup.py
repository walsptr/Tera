"""Tests for the pure helpers of roles/mariadb_backup/files/tera_backup.py (ADR 0012)."""

import pytest
import tera_backup as tb


def backup(seq, kind, from_lsn, to_lsn):
    name = f"{seq:02d}-{kind}-20261018T01000{seq}Z"
    return {
        "name": name,
        "seq": seq,
        "type": kind,
        "path": f"/b/{name}",
        "meta": {"type": kind, "from_lsn": from_lsn, "to_lsn": to_lsn, "size_bytes": 10},
    }


def chain(chain_id, *backups):
    return {"chain_id": chain_id, "path": f"/b/{chain_id}", "backups": list(backups)}


FULL = backup(0, "full", 0, 100)
INC1 = backup(1, "incremental", 100, 150)
INC2 = backup(2, "incremental", 150, 170)


def test_valid_prefix_full_and_incrementals():
    assert tb.valid_prefix(chain("20261018T010000Z", FULL, INC1, INC2)) == [FULL, INC1, INC2]


def test_valid_prefix_stops_at_lsn_gap():
    gap = backup(2, "incremental", 160, 170)
    assert tb.valid_prefix(chain("c", FULL, INC1, gap)) == [FULL, INC1]


def test_valid_prefix_stops_at_missing_sequence():
    assert tb.valid_prefix(chain("c", FULL, INC2)) == [FULL]


def test_chain_without_full_is_incomplete():
    assert tb.valid_prefix(chain("c", INC1)) == []
    assert not tb.is_complete(chain("c", INC1))


def test_plan_next_incremental_on_intact_chain():
    plan = tb.plan_next([chain("c1", FULL, INC1)], "incremental", needs_full=False)
    assert plan["type"] == "incremental"
    assert plan["chain_id"] == "c1"
    assert plan["seq"] == 2
    assert plan["parent"] is INC1


@pytest.mark.parametrize(
    "chains, needs_full",
    [
        ([], False),  # no chain yet
        ([chain("c1", INC1)], False),  # newest chain has no full
        ([chain("c1", FULL, backup(1, "incremental", 90, 150))], False),  # broken at the end
        ([chain("c1", FULL, INC1)], True),  # restore since the last full
    ],
)
def test_plan_next_falls_back_to_full(chains, needs_full):
    plan = tb.plan_next(chains, "incremental", needs_full)
    assert plan == {"type": "full", "chain_id": None, "seq": 0, "parent": None}


def test_plan_next_full_requested():
    assert tb.plan_next([chain("c1", FULL)], "full", False)["type"] == "full"


def test_plan_prune_keeps_newest_complete_chains():
    chains = [chain("c1", FULL), chain("c2", FULL, INC1), chain("c3", FULL)]
    assert [c["chain_id"] for c in tb.plan_prune(chains, 2)] == ["c1"]


def test_plan_prune_counts_only_complete_chains():
    # c3 has no valid full (failed): it does not count, so c1 must stay.
    chains = [chain("c1", FULL), chain("c2", FULL), chain("c3", INC1)]
    assert tb.plan_prune(chains, 2) == []


def test_plan_prune_never_deletes_without_replacement():
    assert tb.plan_prune([chain("c1", FULL)], 2) == []
    assert tb.plan_prune([chain("c1", FULL), chain("c2", FULL)], 2) == []


def test_plan_prune_removes_broken_chain_older_than_kept():
    chains = [chain("c1", INC1), chain("c2", FULL), chain("c3", FULL)]
    assert [c["chain_id"] for c in tb.plan_prune(chains, 2)] == ["c1"]


def test_find_backup_latest_and_by_id():
    chains = [chain("c1", FULL, INC1), chain("c2", FULL, INC1, INC2)]
    found, prefix = tb.find_backup(chains, "latest")
    assert found["chain_id"] == "c2"
    assert prefix == [FULL, INC1, INC2]
    found, prefix = tb.find_backup(chains, "c1/0")
    assert found["chain_id"] == "c1"
    assert prefix == [FULL]


@pytest.mark.parametrize("wanted", ["c1/5", "c9/0", "c1", "c1/x"])
def test_find_backup_rejects_unknown(wanted):
    with pytest.raises(tb.BackupError):
        tb.find_backup([chain("c1", FULL, INC1)], wanted)


def test_find_backup_without_complete_chain():
    with pytest.raises(tb.BackupError):
        tb.find_backup([chain("c1", INC1)], "latest")


def test_parse_kv():
    text = "backup_type = full-backuped\nfrom_lsn = 0\nto_lsn = 45552\n"
    assert tb.parse_kv(text) == {"backup_type": "full-backuped", "from_lsn": "0", "to_lsn": "45552"}


def test_check_tables_output():
    text = (
        "app.t\tcheck\tstatus\tOK\n"
        "app.u\tcheck\terror\tTable is marked as crashed\n"
        "app.u\tcheck\tstatus\tOperation failed\n"
        "app.v\tcheck\tnote\tThe storage engine for the table doesn't support check\n"
    )
    assert tb.check_tables_output(text) == [
        ("app.u", "error", "Table is marked as crashed"),
        ("app.u", "status", "Operation failed"),
    ]


def test_selection_lists_the_chain_prefix():
    out = tb.selection([chain("c1", FULL, INC1, INC2)], "c1/1")
    assert out["chain_id"] == "c1"
    assert out["id"] == "c1/1"
    assert [b["name"] for b in out["backups"]] == [FULL["name"], INC1["name"]]


# --- Metrics (ADR 0016) ---

CFG = {"cluster": "prod-a", "scheduled": True, "targets": [{"name": "bk"}]}


def sample(text, name, **labels):
    """Value of the sample `name` with exactly these labels (plus cluster)."""
    pairs = [("cluster", "prod-a")] + sorted(labels.items())
    wanted = name + "{" + ",".join(f'{k}="{v}"' for k, v in pairs) + "}"
    for line in text.splitlines():
        if not line.startswith("#") and sorted_labels(line.split(" ")[0]) == sorted_labels(wanted):
            return int(line.split(" ")[1])
    raise KeyError(wanted)


def sorted_labels(series):
    name, _, rest = series.partition("{")
    return name, sorted(rest.rstrip("}").split(","))


def test_epoch_parses_iso_and_defaults_to_zero():
    assert tb.epoch("1970-01-02T00:00:00Z") == 86400
    assert tb.epoch(None) == 0
    assert tb.epoch("kemarin") == 0


def test_metrics_exist_with_zero_before_the_first_backup():
    text = tb.render_metrics(CFG, {})
    assert sample(text, "tera_backup_scheduled") == 1
    for t in ("full", "incremental"):
        assert sample(text, "tera_backup_last_success_timestamp_seconds", type=t) == 0
        assert sample(text, "tera_backup_last_attempt_timestamp_seconds", type=t) == 0
        assert sample(text, "tera_backup_last_attempt_success", type=t) == 0
    assert sample(text, "tera_backup_target_last_push_timestamp_seconds", target="bk") == 0
    assert sample(text, "tera_backup_verify_last_timestamp_seconds") == 0
    for r in tb.VERIFY_RESULTS:
        assert sample(text, "tera_backup_verify_last_result", result=r) == 0


def test_metrics_keep_the_last_success_after_a_failed_attempt():
    status = {
        "last": {"full": {"result": "failed", "finished_at": "1970-01-03T00:00:00Z"}},
        "last_success": {
            "full": {"result": "ok", "finished_at": "1970-01-02T00:00:00Z", "size_bytes": 42}
        },
        "targets": {"bk": {"result": "ok", "at": "1970-01-02T00:01:00Z"}},
        "verify": {"last": {"result": "failed", "at": "1970-01-02T01:00:00Z"}},
    }
    text = tb.render_metrics(CFG, status)
    assert sample(text, "tera_backup_last_attempt_timestamp_seconds", type="full") == 2 * 86400
    assert sample(text, "tera_backup_last_attempt_success", type="full") == 0
    assert sample(text, "tera_backup_last_success_timestamp_seconds", type="full") == 86400
    assert sample(text, "tera_backup_last_success_size_bytes", type="full") == 42
    assert sample(text, "tera_backup_target_last_push_success", target="bk") == 1
    assert sample(text, "tera_backup_verify_last_result", result="failed") == 1
    assert sample(text, "tera_backup_verify_last_result", result="ok") == 0


def test_metrics_of_a_node_without_scheduled_backups():
    text = tb.render_metrics(dict(CFG, scheduled=False), {"last": {"full": {"result": "ok"}}})
    assert sample(text, "tera_backup_scheduled") == 0
    assert "tera_backup_last_success_timestamp_seconds" not in text


def test_metrics_label_values_are_escaped():
    text = tb.render_metrics({"cluster": 'a"b\\c', "scheduled": False}, {})
    assert 'cluster="a\\"b\\\\c"' in text


def test_write_metrics_is_atomic_stable_and_world_readable(tmp_path):
    path = tmp_path / "tera_backup.prom"
    cfg = dict(CFG, metrics_path=str(path))
    assert tb.write_metrics(cfg, {}) is True
    assert (path.stat().st_mode & 0o777) == 0o644
    assert tb.write_metrics(cfg, {}) is False
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tera_backup.prom"]
    assert tb.write_metrics(dict(cfg, metrics_path=None), {}) is False
