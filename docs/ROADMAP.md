# Roadmap

Aturan:

- Kerjakan **satu item per kali**.
- Item selesai jika kriteria dan verifikasinya lulus (lihat `docs/TESTING.md`).
- Centang item dalam commit yang sama dengan implementasinya.
- Item yang sudah ditulis tetapi belum bisa diverifikasi ditandai `(belum diverifikasi)`, tidak dicentang.

## Fase 0 — Fondasi

- [x] Dokumen: `AGENTS.md`, `CLAUDE.md`, `docs/*`, ADR 0001–0008
- [x] Skeleton repo, `ansible.cfg`, `requirements.yml`, `.gitignore`
- [x] CI: ansible-lint, syntax-check, pytest, shellcheck, ruff (lulus di GitHub Actions 2026-10-15, run 38753663128)

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

- [x] Molecule `standalone-podman` (pelengkap cepat: Ubuntu 22.04/24.04, Rocky 9, AlmaLinux 9; job CI `molecule-podman` lulus di GitHub Actions 2026-10-15, run 38753663128)

Kriteria fase: deploy berhasil di semua OS target, run kedua `changed=0`, reconfigure menerapkan config global dan per host.

Status: **selesai** (tag `v0.1.0`, 2026-10-14). Kriteria diverifikasi dengan Molecule `standalone` di
Ubuntu 22.04/24.04 dan Rocky 9, plus uji manual `tera_action=reconfigure` di Ubuntu 22.04 (key global dan
override per host aktif, restart sekali, run berikutnya `changed=0`). Tetap terbuka: item CI (Fase 0) dan job
CI `molecule-podman` belum pernah jalan karena repo belum di-push ke GitHub.

## Fase 2 — Galera

- [x] `status.yml`
- [x] `galera.yml` (bootstrap / join sesuai `docs/GALERA-LIFECYCLE.md`) + Molecule `galera` (Ubuntu 22.04, Ubuntu 24.04, Rocky 9)
- [x] Template `[galera]`, paket galera/mariabackup/socat, user SST, `98-tera-sst.cnf`
- [x] `wait_synced.yml`
- [x] Cabang galera di `restart.yml` (rolling restart + `wait_synced`; diverifikasi di Molecule `reconfigure`)
- [x] Prechecks galera
- [x] Firewall: firewalld untuk port Galera (ADR 0010)
- [x] SELinux (port Galera, `mysqld_t` permissive opsional)
- [x] `tera recover`
- [x] Clustercheck
- [x] Molecule `galera`, `reconfigure`, `recover` (Ubuntu 22.04/24.04 dan Rocky 9 untuk `galera`; Ubuntu 24.04 dan Rocky 9 untuk `reconfigure` dan `recover`)

Status: **selesai** (tag `v0.2.0`, 2026-10-15). Diverifikasi dengan Molecule dari VM baru: `galera` di Ubuntu
22.04/24.04 dan Rocky 9 (SELinux enforcing, firewalld aktif); `reconfigure` dan `recover` di Ubuntu 24.04 dan
Rocky 9; `standalone` diulang di Ubuntu 24.04 dan Rocky 9 setelah perubahan `sync`; `recover-poweroff`
(opsional) di Ubuntu 24.04. Tetap terbuka: AlmaLinux 9 tidak dijalankan di VM (opsional), CI belum pernah
jalan karena repo belum di-push ke GitHub, dan pengelolaan firewall untuk mode standalone serta pembatasan
port 9200/3306 dibawa ke rencana Fase 3.

## Fase 3 — Load balancer

- [x] Filter IP `tera_ip` (validasi IPv4, CIDR, IP di dalam subnet) + pytest
- [x] Firewall v2 (ADR 0011): perilaku sama untuk standalone dan galera, `mariadb_client_sources`, 9200 hanya dari node LB, uji TCP dari luar VM
- [x] Role `loadbalancer` (sysctl, SELinux `haproxy_connect_any`, firewall VRRP/VIP/stats)
- [x] HAProxy single/multi writer + stats + custom config
- [x] Keepalived unicast + custom config
- [x] Prechecks load balancer
- [x] `tera destroy` (+ `--keep-data`; Molecule `destroy`: Ubuntu 24.04, Rocky 9)
- [x] Molecule failover (`loadbalancer`: Ubuntu 22.04, Ubuntu 24.04, Rocky 9)

Status: **selesai** (tag `v0.3.0`, 2026-10-15). Setelah pengaman datadir (`mariadb-datadir.initialized`) dan
`tera_manage_firewall`, semua skenario diulang dari VM baru dan lulus di Ubuntu 24.04 dan Rocky 9:
`standalone`, `galera`, `reconfigure`, `recover`, `loadbalancer`, `destroy`. `loadbalancer` juga lulus di
Ubuntu 22.04 sebelumnya. Downtime failover terukur ≤ 5,3 detik (batas 10 detik), split brain 0 sampel.
Tetap terbuka: AlmaLinux 9 tidak dijalankan di VM (opsional; di CI hanya lewat `standalone-podman`).
CI lulus di GitHub Actions setelah repo di-push (2026-10-15).
Tag `v0.3.1` (2026-10-15): test tambahan untuk pengaman datadir di node Galera dan `tera_manage_firewall`
serta tampilan rule di role `loadbalancer`, plus perbaikan CI. Lulus dari VM baru di Ubuntu 24.04 dan Rocky 9
(`standalone`, `galera`, `loadbalancer`, `destroy`) dan di GitHub Actions.

## Fase 4a — Backup & restore

Ditutup dengan tag `v0.4.0`.

- [ ] Spike: perilaku mariabackup 11.4 di Galera (desync, flow control, clustercheck/HAProxy)
- [ ] ADR 0012 (backup) dan ADR 0013 (restore), disetujui sebelum implementasi
- [ ] Backup full + incremental, metadata, retensi per rantai, verifikasi, systemd timer
- [ ] Target penyimpanan: lokal + rsync/ssh ke host backup (lapisan target terpisah), gpg untuk salinan remote
- [ ] Restore standalone dan galera (prechecks ruang disk sebelum service dihentikan)
- [ ] Molecule `backup` dan `backup-galera`, plus backup/restore di `standalone-podman` (CI)

## Fase 4b — Operasional

- [ ] Upgrade minor rolling (patch dalam satu seri; perpindahan seri ditolak)
- [ ] Exporter monitoring (`mysqld_exporter`, `node_exporter` opsional)
- [ ] Scale in
- [ ] `SET GLOBAL` tanpa restart (paling akhir)

Kandidat ADR di luar Fase 4: replikasi async, upgrade major, PITR dari binlog, restore lintas cluster,
target backup S3/MinIO.

## Fase 5 — PostgreSQL

- [ ] ADR Patroni + etcd dan format config
- [ ] Role `etcd`, `postgresql`, `patroni`
- [ ] Health check via REST API Patroni
