# Roadmap

Aturan:

- Kerjakan **satu item per kali**.
- Item selesai jika kriteria dan verifikasinya lulus (lihat `docs/TESTING.md`).
- Centang item dalam commit yang sama dengan implementasinya.
- Item yang sudah ditulis tetapi belum bisa diverifikasi ditandai `(belum diverifikasi)`, tidak dicentang.

## Fase 0 — Fondasi

- [x] Dokumen: `AGENTS.md`, `CLAUDE.md`, `docs/*`, ADR 0001–0008
- [x] Skeleton repo, `ansible.cfg`, `requirements.yml`, `.gitignore`
- [ ] CI: ansible-lint, syntax-check, pytest, shellcheck, ruff (belum diverifikasi: workflow belum pernah jalan di GitHub Actions; perintah setara lulus lokal)

## Fase 1 — Core + MariaDB standalone

- [x] Role `tera_defaults`
- [x] Filter `merge_ini` + test CC-01..CC-10
- [x] CLI `tera`: `new-cluster`, `genpwd`, `prechecks`, `deploy`, `reconfigure`, fact cache per cluster
- [x] `inventory/sample` dengan contoh config yang dikomentari
- [x] `playbooks/facts.yml` (`tera_listen_address`)
- [x] Role `common`
- [x] Role `mariadb`: vars per OS + repo upstream + install
- [x] `roles/mariadb/tasks/config.yml` (merge custom config → `99-tera.cnf`)
- [x] `standalone.yml` + `users.yml` (admin, hapus anonymous & database `test`, `mariadb_databases`, `mariadb_users`)
- [x] Play rolling restart + `restart.yml`
- [ ] Molecule `standalone` (belum diverifikasi: Vagrant belum terpasang; verify.yml sudah lulus terhadap container systemd Ubuntu 24.04 dan Rocky 9)

Kriteria fase: deploy berhasil di semua OS target, run kedua `changed=0`, reconfigure menerapkan config global dan per host.

## Fase 2 — Galera

- [ ] `status.yml`
- [ ] `galera.yml` (bootstrap / join sesuai `docs/GALERA-LIFECYCLE.md`)
- [ ] Template `[galera]`, paket galera/mariabackup/socat, user SST
- [ ] `wait_synced.yml`
- [ ] Prechecks galera
- [ ] SELinux (port Galera, `mysqld_t` permissive opsional)
- [ ] `tera recover`
- [ ] Clustercheck
- [ ] Molecule `galera`, `reconfigure`, `recover`

## Fase 3 — Load balancer

- [ ] Role `loadbalancer` (sysctl, SELinux `haproxy_connect_any`)
- [ ] HAProxy single/multi writer + stats + custom config
- [ ] Keepalived unicast + custom config
- [ ] Prechecks load balancer
- [ ] `tera destroy`
- [ ] Molecule failover

## Fase 4 — Operasional

- [ ] Upgrade MariaDB
- [ ] Backup/restore dengan mariabackup
- [ ] Scale in
- [ ] `SET GLOBAL` tanpa restart
- [ ] Exporter monitoring
- [ ] Replikasi async (perlu ADR)

## Fase 5 — PostgreSQL

- [ ] ADR Patroni + etcd dan format config
- [ ] Role `etcd`, `postgresql`, `patroni`
- [ ] Health check via REST API Patroni
