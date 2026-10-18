# Tera

Tera adalah tool berbasis Ansible untuk memasang dan mengoperasikan **MariaDB**: satu server (standalone)
atau cluster **Galera** 3 node ke atas dengan **VIP** (HAProxy + Keepalived) di depannya.

- **Satu cluster = satu folder** `inventory/<nama>/`: host, variabel, password, custom config.
- **Custom config tanpa fork role**: taruh file `.cnf` di `inventory/<nama>/config/`, lalu
  `tera reconfigure` me-merge, mengirim, dan me-restart **hanya node yang config-nya berubah**, satu per satu.
- **Keamanan data di atas otomatisasi**: Tera tidak pernah mem-bootstrap ulang cluster Galera yang mati
  total secara otomatis, tidak menimpa data lewat SST tanpa izin, dan tidak membuat database kosong baru
  di datadir yang hilang. Dalam kasus ragu, Tera berhenti dengan pesan yang menjelaskan langkah berikutnya.

OS node yang didukung: **Ubuntu 22.04/24.04, Rocky Linux 9, AlmaLinux 9**. MariaDB dari repo upstream
(default `11.4`).

## Prasyarat

**Mesin kontrol** (tempat Anda menjalankan `./tera`):

- Python 3 dan **ansible-core >= 2.16**
- Collections Ansible dari `requirements.yml`:

  ```bash
  python3 -m venv .venv
  .venv/bin/pip install 'ansible-core>=2.16'
  .venv/bin/ansible-galaxy collection install -r requirements.yml -p ./collections
  ```

  `./tera` memakai `ansible-playbook` dari `PATH`, atau dari `.venv/` di folder repo.

**Node**:

- SSH dari mesin kontrol dan `sudo` (Tera memakai `become`).
- systemd. Akses ke repo MariaDB upstream (atau set `mariadb_repo_manage: false` jika memakai mirror sendiri).
- Galera: node saling terjangkau di 4567/tcp+udp, 4568/tcp, 4444/tcp. Jika **firewalld** berjalan, Tera
  membukanya sendiri (lihat [Firewall](#firewall)).
- VIP: semua node load balancer di satu subnet L2, dan VIP adalah alamat bebas di subnet itu.

## Quickstart: standalone

```bash
./tera new-cluster prod-a                 # membuat inventory/prod-a dari inventory/sample
$EDITOR inventory/prod-a/hosts.yml        # satu host di group mariadb
./tera genpwd -i inventory/prod-a         # mengisi password kosong di group_vars/all/passwords.yml
ansible-vault encrypt inventory/prod-a/group_vars/all/passwords.yml   # disarankan
./tera prechecks -i inventory/prod-a      # validasi tanpa mengubah apa pun
./tera deploy    -i inventory/prod-a
```

Backup **belum aktif** secara default: setiap `deploy` dan `reconfigure` menampilkan peringatan sampai Anda
mengaktifkannya. Langkah minimal (lihat [Backup dan restore](#backup-dan-restore)):

```bash
echo 'mariadb_backup_enabled: true' >> inventory/prod-a/group_vars/all/tera.yml
./tera reconfigure -i inventory/prod-a    # memasang timer: full Minggu 01:00, incremental hari lain
./tera backup      -i inventory/prod-a    # backup full pertama sekarang
```

Setelah `passwords.yml` dienkripsi, tambahkan `--ask-vault-pass` (atau set `ANSIBLE_VAULT_PASSWORD_FILE`) ke
setiap perintah; argumen tambahan diteruskan apa adanya ke `ansible-playbook`. `genpwd` hanya bisa dijalankan
sebelum file dienkripsi.

Akses remote memakai user `tera_admin` (password `mariadb_admin_password`) dari host di
`mariadb_admin_hosts`. Root MariaDB hanya bisa login lewat unix socket di node itu sendiri.

## Quickstart: Galera + VIP

`inventory/prod-b/hosts.yml`:

```yaml
all:
  children:
    mariadb:
      hosts:
        db01: { ansible_host: 192.0.2.11, ip: 10.0.0.11 }
        db02: { ansible_host: 192.0.2.12, ip: 10.0.0.12 }
        db03: { ansible_host: 192.0.2.13, ip: 10.0.0.13 }
    loadbalancer:            # boleh host yang sama (colocated)
      hosts:
        db01:
        db02:
        db03:
```

`inventory/prod-b/group_vars/all/tera.yml`:

```yaml
mariadb_cluster_mode: galera
tera_vip_address: 10.0.0.100          # alamat bebas di subnet node load balancer
keepalived_virtual_router_id: 51      # unik per jaringan L2
mariadb_admin_hosts:
  - localhost
  - "10.0.0.%"
mariadb_client_sources:               # siapa yang boleh ke 3306/VIP (default semua)
  - 10.0.0.0/24
```

```bash
./tera genpwd    -i inventory/prod-b
./tera prechecks -i inventory/prod-b
./tera deploy    -i inventory/prod-b      # tanpa --limit: bootstrap/join butuh status semua node
```

Aplikasi terhubung ke `10.0.0.100:3306`. Halaman stats HAProxy ada di `http://<node>:8404/`
(user `tera`, password `haproxy_stats_password`, dari sumber di `haproxy_stats_sources`).

`ip` adalah alamat yang dipakai MariaDB untuk listen dan antar node. Tanpa `ip`, Tera memakai IPv4 dari
`tera_network_interface`, lalu alamat default route.

## Custom config dan reconfigure

```
inventory/<cluster>/config/
├── mariadb/*.cnf              # semua node
├── mariadb/<host>/*.cnf       # node tertentu (menang atas yang global)
├── haproxy/haproxy.cfg        # pengganti penuh config HAProxy (opsional)
├── haproxy/conf.d/*.cfg       # ditambahkan ke config HAProxy (opsional)
└── keepalived/keepalived.conf # pengganti penuh config Keepalived (opsional)
```

Contoh `config/mariadb/tuning.cnf`:

```ini
[mysqld]
max_connections = 1000
innodb_buffer_pool_size = {{ (ansible_facts['memtotal_mb'] * 0.6) | int }}M
```

```bash
./tera reconfigure -i inventory/prod-b --check --diff   # lihat perubahan dulu
./tera reconfigure -i inventory/prod-b
```

- Semua file dirender sebagai Jinja2 dan digabung ke satu file `99-tera.cnf` per node (aturan lengkap:
  `docs/CUSTOM-CONFIG.md`). Value `__remove__` menghapus key bawaan.
- Hanya node yang `99-tera.cnf`-nya berubah yang di-restart, **satu per satu**, dan node berikutnya baru
  di-restart setelah node sebelumnya Synced kembali. Run tanpa perubahan tidak me-restart apa pun.
- Jika run terputus setelah config ditulis tetapi sebelum restart, run berikutnya tetap me-restart.
- Jangan menaruh password di custom config; `wsrep_sst_auth` di custom config ditolak.

## Recover: semua node Galera mati

Jika semua node mati (listrik padam, crash), dua hal bisa terjadi:

- MariaDB menyala lagi sendiri dan cluster pulih otomatis: `./tera deploy` melihat cluster hidup dan
  hanya menyusulkan node yang tertinggal.
- Cluster tidak pulih: `./tera deploy` **gagal dengan sengaja** dan meminta Anda menjalankan:

  ```bash
  ./tera recover -i inventory/prod-b
  ```

  Tera membaca posisi transaksi terakhir di setiap node (`grastate.dat`, atau `mariadbd --wsrep-recover`),
  memilih node yang datanya paling baru, mem-bootstrap dari node itu, lalu menyalakan node lain satu per
  satu. Ringkasan per node ditampilkan sebelum bootstrap.

  Untuk memaksa node tertentu: `./tera recover -i inventory/prod-b -e mariadb_recover_from=db02`.
  **Hati-hati**: memaksa node dengan data lebih lama menghilangkan transaksi yang lebih baru.

## Backup dan restore

Backup memakai `mariabackup` (full + incremental, dikompresi zstd), dijalankan systemd timer di node backup,
tanpa user atau password tambahan (root lewat unix socket).

```yaml
# inventory/prod-b/group_vars/all/tera.yml
mariadb_backup_enabled: true
# mariadb_backup_host: db03                    # default: node terakhir (galera: bukan writer HAProxy)
# mariadb_backup_dir: /var/backups/tera/mariadb  # disarankan disk terpisah dari datadir
mariadb_backup_keep_full: 2                    # jumlah rantai (full + incremental-nya) yang disimpan
mariadb_backup_targets:                        # salinan di luar node, selalu terenkripsi gpg
  - name: bk
    type: rsync
    host: backup01                             # host di group mariadb_backup_target (hosts.yml)
mariadb_backup_gpg_public_key: "{{ inventory_dir }}/config/backup/backup.pub.asc"
```

```bash
gpg --armor --export backup@example.com > inventory/prod-b/config/backup/backup.pub.asc   # public key saja
./tera reconfigure    -i inventory/prod-b                  # timer, kunci, host backup
./tera backup         -i inventory/prod-b [--incremental]  # backup sekarang
./tera backup-status  -i inventory/prod-b                  # status terakhir setiap node
./tera backup-verify  -i inventory/prod-b                  # bongkar, prepare, CHECK TABLE (salinan sementara)
```

- **Jadwal:** full Minggu, incremental Senin–Sabtu, pukul 01:00 waktu node ditambah jeda acak hingga 15
  menit (`mariadb_backup_full_schedule`, `mariadb_backup_incremental_schedule`,
  `mariadb_backup_randomized_delay`). Incremental tanpa full yang sah otomatis menjadi full.
- **Verifikasi:** setiap backup diperiksa checksum-nya; setelah setiap full, backup dibongkar dan diuji dengan
  `mariadbd` sementara (`CHECK TABLE`) dengan prioritas rendah. Jika ruang sementara tidak cukup, verifikasi
  dilewati dengan status `warning`. Matikan dengan `mariadb_backup_verify_after_full: false`.
- **Retensi:** berdasarkan jumlah rantai, bukan umur: rantai lama baru dihapus setelah full baru terbukti baik,
  sehingga backup yang gagal diam-diam tidak pernah membuat semua backup terhapus.
- **Host backup:** node backup hanya bisa **menulis** ke sana; ia tidak bisa membaca, mendaftar, atau menghapus
  backup remote. Retensi dan pemeriksaan checksum remote dijalankan host backup sendiri.
- **Enkripsi:** salinan remote selalu dienkripsi dengan public key gpg; private key **tidak pernah** ada di node.
  Simpan private key di tempat aman: tanpa private key, salinan remote tidak bisa dipakai. Salinan lokal
  default tidak terenkripsi (root di node sudah bisa membaca datadir; restore darurat tidak bergantung pada
  private key); set `mariadb_backup_encrypt_local: true` jika perlu.
- `tera destroy` **tidak pernah** menghapus backup, baik di node maupun di host backup.

### Restore

```bash
./tera restore -i inventory/prod-b --yes-i-really-really-mean-it -e mariadb_restore_backup=latest
# backup tertentu dari host backup:
./tera restore -i inventory/prod-b --yes-i-really-really-mean-it \
    -e mariadb_restore_backup=20261018T010000Z/2 -e mariadb_restore_source=bk \
    -e mariadb_restore_gpg_private_key=~/secure/backup.key.asc
```

- Id backup terlihat di `./tera backup-status` (`<chain_id>/<sequence>`).
- Semua pemeriksaan (cluster, seri MariaDB, mode, checksum, ruang disk) dan prepare dilakukan **sebelum**
  MariaDB dihentikan. Jika gagal di tahap ini, tidak ada yang diubah.
- Galera: **seluruh cluster down** sampai node restore Synced; node lain lalu menerima SST penuh.
- Data setelah backup itu hilang. Backup berikutnya otomatis full.
- Restore standalone → galera (atau sebaliknya) adalah jalur migrasi; butuh
  `-e mariadb_restore_allow_mode_change=true`.
- Datadir lama di node restore dipindahkan ke `/var/lib/mysql.pre-restore-<id>` dan **tidak** dihapus otomatis.
  Setelah aplikasi diverifikasi: `sudo rm -rf /var/lib/mysql.pre-restore-<id>`.
- Restore dari host backup (atau dari node backup lain) mengirim data langsung ke node restore dengan kunci
  sementara milik user `tera-restore`: hanya boleh menulis ke direktori staging restore itu, dari alamat sumber,
  dan kedaluwarsa setelah 2 jam (`mariadb_restore_key_ttl`). Login root lewat SSH tidak dibutuhkan, tetapi sshd
  node harus mengizinkan user `tera-restore` (periksa `AllowUsers`/`AllowGroups`). Jika tidak, restore gagal
  sebelum MariaDB dihentikan dengan pesan yang menjelaskan penyebabnya.

## Upgrade minor (patch dalam satu seri)

```bash
./tera backup  -i inventory/prod-b                                    # jika backup aktif: butuh backup terverifikasi <= 24 jam
./tera upgrade -i inventory/prod-b -e mariadb_upgrade_to=latest --check   # lihat rencana: versi target per node
./tera upgrade -i inventory/prod-b -e mariadb_upgrade_to=latest           # atau versi eksplisit, mis. 11.4.13
```

- Hanya patch dalam seri `mariadb_version` (mis. 11.4.11 → 11.4.13). Perpindahan seri dan downgrade ditolak.
  `latest` diterjemahkan sekali ke satu versi untuk semua node, dan galera-4 ikut ke versi terbaru di repo.
- Galera: satu node per kali, writer paling akhir; setiap node dikeluarkan dulu dari HAProxy. Upgrade writer
  memberi **dua gangguan** seperti rolling restart (failover, lalu sesi di node cadangan diputus saat writer
  kembali). Koneksi baru yang kebetulan sedang tersambung saat itu juga bisa gagal. **Aplikasi wajib me-retry
  koneksi dan transaksi.** Standalone: MariaDB mati selama upgrade paket.
- Backup aktif: upgrade butuh backup sukses yang lolos verifikasi, maksimal `mariadb_upgrade_max_backup_age`
  (default 24 jam). Backup tidak aktif: ditolak kecuali `-e mariadb_upgrade_allow_without_backup=true`.
- Repo seri upstream biasanya hanya menyimpan patch terbaru; versi tertentu yang lebih lama ada di
  `archive.mariadb.org` (atur `mariadb_repo_deb_url`/`mariadb_repo_rpm_url`).
- Log setiap operasi paket dan `mariadb-upgrade` ada di `/var/log/tera/` di setiap node.
- Tera memasang paket MariaDB **tanpa** paket yang dianjurkan (Recommends/weak dependencies), saat deploy dan
  upgrade. Paket yang sudah terpasang tidak dihapus.

## Monitoring (Prometheus)

Tera memasang exporter; Prometheus dan Grafana tidak. Default mati.

```yaml
# inventory/prod-b/group_vars/all/tera.yml
tera_monitoring_enabled: true        # mysqld_exporter di setiap node mariadb (port 9104)
node_exporter_enabled: true          # opsional: metrik host + metrik backup (port 9100)
tera_monitoring_sources:             # alamat Prometheus; kosong = exporter hanya di 127.0.0.1
  - 10.10.20.5
haproxy_prometheus_enabled: true     # /metrics di port stats HAProxy (8404)
```

- `mysqld_exporter` berjalan sebagai user OS `tera-exporter` dan login ke MariaDB lewat `unix_socket` sebagai
  user `tera-exporter` (tanpa password; hak `PROCESS`, `REPLICA MONITOR`, `SELECT` pada `performance_schema`).
  `node_exporter` berjalan sebagai user lain, `tera-node-exporter`, yang tidak bisa login ke MariaDB.
- Binary diunduh dari GitHub releases dengan versi dan SHA256 yang di-pin; checksum yang salah menggagalkan run
  sebelum binary dipasang. **Tanpa internet:** arahkan `mysqld_exporter_url` dan `node_exporter_url` ke mirror
  internal (nama file rilis yang sama); versi lain butuh `*_sha256` yang sesuai.
- `/metrics` HAProxy memakai **user dan password stats** (`haproxy_stats_user`, `haproxy_stats_password`):
  Prometheus harus memakai basic auth. Port stats terbuka untuk `haproxy_stats_sources` ditambah
  `tera_monitoring_sources`.
- Mematikan monitoring (`tera_monitoring_enabled: false` lalu `tera reconfigure`) menghapus exporter, user OS,
  user MariaDB `tera-exporter`, file metrik, dan rule firewall-nya.

Metrik backup (`tera_backup.prom`, dibaca textfile collector `node_exporter` dari
`/var/lib/tera/node_exporter`) ditulis ulang setiap kali status backup berubah. Node backup selalu punya
metrik ini sejak deploy pertama, bernilai `0` sampai ada backup; node lain hanya `tera_backup_scheduled 0`.

| Metrik | Arti |
|---|---|
| `tera_backup_scheduled` | 1 di node yang menjalankan backup terjadwal |
| `tera_backup_last_success_timestamp_seconds{type}` | akhir backup sukses terakhir (`full`/`incremental`) |
| `tera_backup_last_attempt_timestamp_seconds{type}` | akhir percobaan terakhir, sukses atau gagal |
| `tera_backup_last_attempt_success{type}` | 1 jika percobaan terakhir sukses |
| `tera_backup_last_success_size_bytes{type}` | ukuran backup sukses terakhir |
| `tera_backup_target_last_push_timestamp_seconds{target}`, `..._success` | push terakhir ke target backup |
| `tera_backup_verify_last_timestamp_seconds`, `tera_backup_verify_last_result{result}` | verifikasi level 2 terakhir (`ok`, `failed`, `skipped`, `warning`) |

Umur dihitung di Prometheus dari timestamp. Contoh rule alert (jadwal default: backup setiap hari):

```yaml
groups:
  - name: tera-backup
    rules:
      - alert: TeraBackupTooOld
        expr: time() - max by (instance, cluster) (tera_backup_last_success_timestamp_seconds) > 26 * 3600
        labels: {severity: critical}
        annotations:
          summary: "Tidak ada backup sukses dalam 26 jam di {{ $labels.instance }}"
      - alert: TeraBackupLastAttemptFailed
        expr: tera_backup_last_attempt_success == 0 and tera_backup_last_attempt_timestamp_seconds > 0
        labels: {severity: warning}
      - alert: TeraBackupVerifyFailed
        expr: tera_backup_verify_last_result{result="failed"} == 1
        labels: {severity: critical}
      - alert: TeraBackupPushFailed
        expr: tera_backup_target_last_push_success == 0 and tera_backup_target_last_push_timestamp_seconds > 0
        labels: {severity: warning}
      - alert: TeraBackupMetricsMissing     # node_exporter mati atau file metrik hilang
        expr: absent(tera_backup_scheduled == 1)
        for: 1h
        labels: {severity: warning}
```

Node yang belum pernah berhasil backup punya timestamp `0`, sehingga `TeraBackupTooOld` langsung menyala.

## Destroy

```bash
./tera destroy -i inventory/prod-b --yes-i-really-really-mean-it              # hapus semua, termasuk data
./tera destroy -i inventory/prod-b --yes-i-really-really-mean-it --keep-data  # pertahankan datadir
```

Setiap node menampilkan dulu apa yang akan dihapus dan database yang ditemukan di datadir. Paket dan repo
tidak dihapus. Dengan `--keep-data` di cluster Galera, deploy berikutnya akan meminta `tera recover`
(data lama dipakai lagi dengan aman).

## Perilaku yang perlu diketahui operator

- **Aplikasi harus siap reconnect.** Saat writer mati, koneksi ke node itu putus dan koneksi baru lewat
  VIP pindah ke node berikutnya dalam beberapa detik (pengujian: sekitar 2 s; sekitar 5 s jika node yang
  mati juga memegang VIP).
- **Sesi diputus saat writer kembali.** Mode default `single_writer` mengirim semua koneksi ke node pertama
  group `mariadb`. Saat node itu kembali sehat, **semua sesi yang sedang berjalan di node cadangan diputus**
  agar semua klien kembali ke satu writer (menghindari konflik tulis di Galera). Transaksi yang sedang
  berjalan di sesi itu gagal dan harus diulang aplikasi.
- **VIP tidak pindah balik.** Setelah failover, VIP tetap di node barunya walaupun node lama kembali, agar
  tidak ada gangguan kedua.
- **Firewall dikelola Tera** (jika firewalld berjalan). Lihat bagian berikut.
- **Datadir kosong menghentikan deploy.** Jika datadir yang pernah terisi tiba-tiba kosong (mis. disk data
  gagal di-mount), deploy gagal dan meminta Anda memeriksa mount, bukan membuat database baru di disk root.
- **Tidak ada bootstrap otomatis untuk cluster lama** dan **tidak ada SST yang menimpa data user tanpa izin**
  (`mariadb_galera_allow_sst_overwrite: true` untuk sengaja membuang data di node itu).
- `--limit` ditolak untuk `deploy` mode Galera; untuk sebagian host gunakan `reconfigure --limit`.
- **Node backup keluar sebentar dari pool saat backup (Galera).** Selama tahap `BACKUP STAGE BLOCK_DDL`
  (salinan tabel non-InnoDB), node backup desync dan HAProxy mengeluarkannya; biasanya beberapa detik, lebih
  lama jika ada banyak tabel non-InnoDB. Salinan InnoDB berjalan saat node tetap melayani. Dengan 3 node, selama
  jendela itu hanya satu kandidat failover yang tersisa. `mariadb_backup_throttle` memperpanjang jendela ini.
- **Rolling restart menunggu backup** yang sedang berjalan di node itu (maks `mariadb_backup_lock_timeout`,
  default 2 jam), lalu gagal dengan pesan jika backup belum selesai. `tera upgrade` juga.
- **Sisa `tera upgrade` yang terputus dibersihkan otomatis.** `deploy`/`reconfigure`/`upgrade` berikutnya
  menyalakan lagi socket clustercheck (node kembali ke pool), melepas lock backup, dan menghapus
  `/usr/sbin/policy-rc.d` milik Tera, masing-masing dengan peringatan. `policy-rc.d` lain tidak disentuh.

## Firewall

Jika **firewalld berjalan**, Tera mengelola zona default (Tera tidak pernah menyalakan firewalld dan tidak
mengelola ufw):

| Port | Dibuka untuk |
|---|---|
| 3306/tcp (dan VIP) | `mariadb_client_sources` (default semua) |
| 4567/tcp+udp, 4568/tcp, 4444/tcp | node cluster saja |
| 9200/tcp (health check) | node load balancer saja |
| 8404/tcp (stats HAProxy) | `haproxy_stats_sources` (default hanya node load balancer); dengan `haproxy_prometheus_enabled` juga `tera_monitoring_sources` |
| 9104/tcp, 9100/tcp (exporter) | `tera_monitoring_sources` (default kosong: exporter hanya di 127.0.0.1) |
| VRRP (protokol 112) | node load balancer lain saja |

Tera **memiliki** rule untuk port-port itu: rule buatan tangan untuk port yang sama akan dihapus, dan
daftar rule yang akan dihapus ditampilkan saat run (juga di `--check --diff`). Atur akses lewat variabel di
atas, atau set `tera_manage_firewall: false` agar Tera sama sekali tidak menyentuh firewalld.

### Keamanan: `*_sources` hanya ditegakkan lewat firewalld

`mariadb_client_sources`, `haproxy_stats_sources`, dan `tera_monitoring_sources` **hanya** ditegakkan oleh rule
firewalld milik Tera. Di host tanpa firewalld yang berjalan (Ubuntu default), atau jika `tera_manage_firewall`
atau `*_firewall_manage` bernilai `false`, **tidak ada satu pun yang ditegakkan**: port terbuka untuk siapa saja
yang bisa menjangkau alamat itu. Prechecks memberi peringatan per host ("sources tidak ditegakkan") jika
sumbernya dibatasi di host seperti itu. Batasi sendiri lewat firewall jaringan atau ufw. Pengecualian:
`tera_monitoring_sources` kosong membuat exporter hanya mendengarkan `127.0.0.1`, tanpa bergantung firewall.

## Dokumentasi lanjutan

- `docs/ARCHITECTURE.md`: struktur, variabel, topologi HA, artefak di node, destroy
- `docs/CUSTOM-CONFIG.md`: aturan merge custom config
- `docs/GALERA-LIFECYCLE.md`: bootstrap, join, rolling restart, recover
- `docs/TESTING.md`: cara Tera diuji (Molecule) dan checklist lab
- `docs/decisions/`: keputusan desain (ADR); backup dan restore di ADR 0012 dan 0013
