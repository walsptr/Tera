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
- [x] Molecule `standalone` (Ubuntu 22.04, Ubuntu 24.04, Rocky 9 lulus 2026-10-14 dengan `vagrant`/`vagrant-libvirt` paket Fedora; AlmaLinux 9 opsional, belum dijalankan di VM)

- [x] Molecule `standalone-podman` (pelengkap cepat: Ubuntu 22.04/24.04, Rocky 9, AlmaLinux 9; job CI belum diverifikasi di GitHub)

Kriteria fase: deploy berhasil di semua OS target, run kedua `changed=0`, reconfigure menerapkan config global dan per host.

Status: **selesai** (tag `v0.1.0`, 2026-10-14). Kriteria diverifikasi dengan Molecule `standalone` di
Ubuntu 22.04/24.04 dan Rocky 9, plus uji manual `tera_action=reconfigure` di Ubuntu 22.04 (key global dan
override per host aktif, restart sekali, run berikutnya `changed=0`). Tetap terbuka: item CI (Fase 0) dan job
CI `molecule-podman` belum pernah jalan karena repo belum di-push ke GitHub.

## Fase 2 — Galera

- [ ] `status.yml`
- [ ] `galera.yml` (bootstrap / join sesuai `docs/GALERA-LIFECYCLE.md`)
- [ ] Template `[galera]`, paket galera/mariabackup/socat, user SST, `98-tera-sst.cnf` (belum diverifikasi: dicentang bersama `galera.yml`)
- [ ] `wait_synced.yml`
- [ ] Cabang galera di `restart.yml` (rolling restart + `wait_synced`; diverifikasi di Molecule `reconfigure`)
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
