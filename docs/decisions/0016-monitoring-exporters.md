# 0016. Exporter monitoring

- **Status:** Accepted
- **Tanggal:** 2026-10-16

## Konteks

Fase 4b menyediakan metrik untuk Prometheus: status MariaDB/Galera, status backup (kontrak file
`/etc/tera/mariadb-backup.status`, ADR 0012), dan opsional metrik host dan HAProxy. Tera tidak memasang
Prometheus atau Grafana.

Keputusan sebelumnya: `mysqld_exporter` + `node_exporter` opsional (textfile status backup); binary dari URL yang
bisa diubah lewat variabel, versi di-pin, checksum SHA256, default GitHub releases; autentikasi lewat
`unix_socket`; `tera_monitoring_sources` default kosong; endpoint Prometheus HAProxy opsional jika tersedia di
paket EL9. Spike: HAProxy EL9 2.8.14, Ubuntu 22.04 2.4.30, Ubuntu 24.04 2.8.16 semuanya dibangun dengan
Prometheus exporter.

## Keputusan

### Binary

- `mysqld_exporter` (wajib saat monitoring aktif) dan `node_exporter` (opsional), masing-masing dengan variabel
  versi, URL tarball (default GitHub releases, dengan `{{ version }}` dan arsitektur), dan SHA256. Checksum yang
  salah menggagalkan run sebelum binary dipasang. Binary di `/usr/local/bin`, satu unit systemd per exporter.
- Aktivasi: `tera_monitoring_enabled` (default `false`), `node_exporter_enabled` (default `false`).

### mysqld_exporter

- Berjalan sebagai user sistem `tera-exporter` (tanpa shell, tanpa home). Login ke MariaDB lewat **unix_socket**
  sebagai user MariaDB `'tera-exporter'@'localhost'` `IDENTIFIED VIA unix_socket`, tanpa password (sejalan dengan
  ADR 0008). Hak: `PROCESS, REPLICA MONITOR, SELECT ON performance_schema.*`, `MAX_USER_CONNECTIONS 3`. User
  dibuat di node bootstrap (tereplikasi Galera) dan di standalone.
- File client exporter hanya berisi `user` dan `socket` (path socket per OS). Tidak ada secret.
- Port `mysqld_exporter_port` (default 9104).

### node_exporter dan status backup

- Port `node_exporter_port` (default 9100), collector bawaan + textfile collector di
  `/var/lib/tera/node_exporter`.
- Script kecil mengubah `/etc/tera/mariadb-backup.status` menjadi `tera_backup.prom` (waktu dan hasil backup
  terakhir per tipe, umur, hasil push per target, hasil verifikasi level 2). Dijalankan setelah setiap backup dan
  verifikasi (`ExecStartPost`/`ExecStopPost` unit backup), ditulis atomik (tulis file sementara lalu rename).
- Tanpa `node_exporter`, file `.prom` tetap ditulis bila monitoring aktif agar bisa dibaca exporter lain.

### HAProxy

- `haproxy_prometheus_enabled` (default `false`): `/metrics` di frontend stats yang sudah ada
  (`haproxy_stats_port`), dengan autentikasi dan sumber yang sama dengan halaman stats. Prechecks memastikan
  HAProxy dibangun dengan Prometheus exporter (`haproxy -vv`).

### Akses jaringan

- `tera_monitoring_sources` (list CIDR, default `[]`) untuk port exporter, divalidasi seperti
  `mariadb_client_sources`.
- **Daftar kosong:** exporter hanya mendengarkan `127.0.0.1`, sehingga tidak bisa diakses dari luar walaupun
  firewalld tidak dikelola (Ubuntu tanpa firewalld). Daftar berisi: exporter mendengarkan `tera_listen_address`,
  dan jika Tera mengelola firewalld, port dibuka hanya dari sumber itu (rich rule milik Tera, ADR 0011).
  (Usulan Claude, disetujui pemilik pada review 2026-10-16.)

### `*_sources` hanya ditegakkan lewat firewalld

Semua variabel sumber (`mariadb_client_sources`, `haproxy_stats_sources`, `tera_monitoring_sources`) hanya
ditegakkan oleh rich rule firewalld milik Tera. Di host yang tidak menjalankan firewalld (Ubuntu default), atau jika
`tera_manage_firewall`/`*_firewall_manage` `false`, **tidak ada satu pun yang ditegakkan**: port terbuka untuk
siapa saja yang bisa menjangkau alamat itu. Prechecks memberi peringatan per host jika sebuah `*_sources` dibatasi
(daftar `mariadb_client_sources` tanpa `0.0.0.0/0`; `haproxy_stats_sources` atau `tera_monitoring_sources` tidak
kosong) di host yang firewalld-nya tidak berjalan atau tidak dikelola. README menyatakannya di bagian keamanan.
(Keputusan pemilik pada review 2026-10-16.)

## Alternatif yang ditolak

- **User exporter dengan password:** secret tambahan di `passwords.yml` dan di node, padahal exporter selalu
  lokal.
- **Paket exporter distro:** versi berbeda per OS dan tidak tersedia di semua OS target (EL9 butuh EPEL).
- **Metrik backup lewat `mysqld_exporter`:** exporter itu tidak membaca file; textfile collector adalah pola
  standar.
- **Default `tera_monitoring_sources` = `mariadb_client_sources`:** default klien terbuka (`0.0.0.0/0`).
- **Endpoint Prometheus HAProxy di port terpisah:** port dan aturan firewall baru tanpa manfaat.

## Konsekuensi

- Ada user sistem dan user MariaDB `tera-exporter` di setiap node saat monitoring aktif. `destroy` menghapus user
  sistem, unit, binary, dan file `.prom`.
- Tera mengunduh binary dari internet (atau mirror lewat variabel URL); lingkungan tanpa internet mengisi URL
  mirror internal.
- Default monitoring mati; setelah diaktifkan, exporter hanya lokal sampai `tera_monitoring_sources` diisi.
- Operator Ubuntu tanpa firewalld harus menegakkan pembatasan sumber sendiri (firewall jaringan, ufw); Tera hanya
  memperingatkan.
- Test (skenario `monitoring`, 3 node, Ubuntu 24.04 dan Rocky 9; podman di CI): dari host `mysql_up 1`,
  `mysql_global_status_wsrep_cluster_size 3`, metrik `tera_backup_*`; checksum binary salah ditolak; sumber
  dibatasi di Rocky (host di luar daftar ditolak); daftar kosong = port hanya di `127.0.0.1`; peringatan prechecks
  "sources tidak ditegakkan" di Ubuntu tanpa firewalld saat sumber dibatasi, dan tidak muncul di Rocky; `/metrics` HAProxy
  dengan dan tanpa autentikasi; idempotence `changed=0`; tanpa denial SELinux.
