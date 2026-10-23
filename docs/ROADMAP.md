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

- [x] Spike: perilaku mariabackup 11.4 di Galera (desync, flow control, clustercheck/HAProxy) — `docs/spikes/2026-10-16-mariabackup-galera.md`
- [x] ADR 0012 (backup) dan ADR 0013 (restore), disetujui sebelum implementasi
- [x] Backup full + incremental, metadata, retensi per rantai, verifikasi, systemd timer
- [x] Target penyimpanan: lokal + rsync/ssh ke host backup tulis-saja (role `backup_target`, retensi dan checksum di host backup), gpg untuk salinan remote
- [x] Restore standalone dan galera (prechecks ruang disk sebelum service dihentikan, pengiriman dari host backup, standalone → galera dengan override)
- [x] Molecule `backup` dan `backup-galera`, plus backup/restore di `standalone-podman` (CI)

Status: **selesai** (tag `v0.4.0`, 2026-10-16). Diverifikasi dari VM baru: `backup` di Ubuntu 22.04/24.04 dan
Rocky 9; `backup-galera` di Ubuntu 24.04 dan Rocky 9; regresi `standalone` (Ubuntu 22.04/24.04, Rocky 9) dan
`galera`, `reconfigure`, `recover`, `loadbalancer`, `destroy` (Ubuntu 24.04, Rocky 9) lulus; failover
`loadbalancer` ≤ 4,9 detik, split brain 0. `standalone-podman` dengan backup/restore lulus di GitHub Actions
(Ubuntu 22.04/24.04, Rocky 9, AlmaLinux 9). Tetap terbuka: `galera_position` di metadata bernilai `null`
(mariabackup 11.4 tidak menuliskannya ke `--extra-lsndir`; restore tidak membutuhkannya), dan target S3/MinIO
serta restore lintas cluster menunggu ADR.

## Fase 4b — Operasional

Ditutup dengan tag `v0.5.0`.

- [x] Penerima restore khusus `tera-restore` dan kunci sementara ber-TTL (ADR 0014; Molecule `backup` Ubuntu 22.04/24.04 dan Rocky 9, `backup-galera` Ubuntu 24.04 dan Rocky 9)
- [x] Kecil: `mariadbd` sementara untuk verifikasi/restore berjalan sebagai user `mysql`, bukan root (perbaiki izin direktori kerja)
- [x] Kecil: field `galera_position` dihapus dari metadata backup (`format_version` tetap 1)
- [x] Upgrade minor rolling (patch dalam satu seri; perpindahan seri ditolak; ADR 0015; Molecule `upgrade` Ubuntu 24.04 dan Rocky 9, `upgrade-podman` 4 image; `standalone` dan `galera` ulang dari VM baru di Ubuntu 24.04 dan Rocky 9)
- [x] Exporter monitoring (`mysqld_exporter`, `node_exporter` opsional; ADR 0016; Molecule `monitoring` Ubuntu 24.04 dan Rocky 9, `monitoring-podman` 4 image)
- [x] Scale in (ADR 0017; `tera scale-in` + langkah 2 tanpa restart, marker "removed" ditolak semua action; Molecule `scale` Ubuntu 24.04 dan Rocky 9)
- [x] `SET GLOBAL` tanpa restart (ADR 0018; whitelist + alias + deny list, rollback semua key di node pertama, marker di node lain; Molecule `reconfigure` Ubuntu 24.04 dan Rocky 9, kasus dinamis di `standalone-podman` 4 image)

Status: **selesai** (tag `v0.5.0`, 2026-10-23). Diverifikasi dari VM baru (2026-10-23, `main` `63cab68`; `reconfigure`
di `e532ccd` dengan kode yang sama): `standalone` dan `backup` di Ubuntu 22.04/24.04 dan Rocky 9; `galera`,
`reconfigure`, `recover`, `loadbalancer`, `destroy`, `backup-galera`, `upgrade`, `monitoring`, `scale` di Ubuntu 24.04
dan Rocky 9 lulus; failover `loadbalancer` ≤ 4,9 detik. Dua run diulang karena sebab di luar Tera: `upgrade` Ubuntu
24.04 (laptop suspend 108 menit di tengah run) dan `scale` Rocky 9 (unduhan dari `mirror.mariadb.org` gagal).
GitHub Actions tidak menjalankan job sejak 2026-10-23 (kuota/billing akun). Keputusan pemilik 2026-10-23: fase ditutup
dan di-tag tanpa menunggu CI, dengan pengganti lokal: `yamllint .`, `ansible-lint`, `ruff check plugins/ roles/`,
`shellcheck`, syntax-check semua playbook, dan `pytest plugins/` (124) lulus; `standalone-podman`, `upgrade-podman`,
`monitoring-podman` di Ubuntu 24.04 dan Rocky 9 lulus, kecuali satu kegagalan `standalone-podman` Ubuntu 24.04 (lihat
di bawah; sesudahnya side effect diulang sekali dan 3 run penuh, semuanya lulus). Run GitHub Actions terakhir pada kode yang sama kecuali test `reconfigure` (`6f9e6c0`, run
39141085405) lulus di keempat image.

Tetap terbuka:

- `tera restore` tahap 2 di Ubuntu gagal sekali (2026-10-23, `standalone-podman` Ubuntu 24.04) di task "Create admin
  user" dengan `'NoneType' object is not subscriptable` dari `ansible.mysql.mysql_user`, pada akun admin kedua. Saat
  itu data hasil restore sudah aktif; datadir lama dan marker restore tetap ada, jadi pesan rescue ("kembali ke data
  lama") tidak berarti restore-nya gagal. Penyebab belum diketahui. Yang sudah dicek: setelah setiap restore di
  Ubuntu, `debian-start` menjalankan `mariadb-upgrade` penuh sekitar 5 detik (mariabackup tidak menyalin
  `mariadb_upgrade_info`) bersamaan dengan `users.yml`, tetapi query yang dipakai modul tidak pernah kosong selama
  jendela itu (30.000 sampel). Jalur ini tidak berubah sejak `v0.4.0`. Dicatat terbuka atas usulan Claude, dipilih
  pemilik 2026-10-23.
- Satu kegagalan `monitoring` di Ubuntu 24.04 (2026-10-18 17:18 WIB, 1 dari 3 run, assert "Assert Rocky refuses the
  host and Ubuntu does not"). Bukan insiden DNS hari itu: aturan MASQUERADE baru dipasang pukul 21:33 dan stub DNS host
  tidak menolak query apa pun sebelum 21:34; converge dan idempotence run itu (unduhan dari repo) lulus; probe memakai
  IP. Status yang diterima host tidak tercatat (`fail_msg` test rusak, diperbaiki hari itu). Petunjuk: saat itu
  `monitoring-podman` berjalan paralel di host yang sama dan timeout probe masih 5 detik (sekarang 10). Tidak muncul
  lagi sesudahnya, termasuk di regresi 2026-10-23.

Kandidat ADR di luar Fase 4: replikasi async, upgrade major, PITR dari binlog, restore lintas cluster,
target backup S3/MinIO.

## Fase 5 — PostgreSQL

- [ ] ADR Patroni + etcd dan format config
- [ ] Role `etcd`, `postgresql`, `patroni`
- [ ] Health check via REST API Patroni
