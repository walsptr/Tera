# 0005. Health check tera-clustercheck via systemd socket

- **Status:** Accepted
- **Tanggal:** 2026-10-14

## Konteks

HAProxy perlu tahu apakah sebuah node Galera benar-benar siap melayani (Synced), bukan sekadar menerima login.

## Keputusan

- Script `tera-clustercheck` dijalankan via systemd socket activation (`Accept=yes`) di port 9200 (`mariadb_clustercheck_port`), sebagai user `mysql`.
- Mengembalikan HTTP 200 hanya jika `wsrep_local_state = 4` (Synced).
- Node Donor boleh dianggap tersedia lewat `mariadb_clustercheck_available_when_donor` (default `false`).

## Alternatif yang ditolak

- **`option mysql-check`**: hanya mengecek login, bukan status Galera.
- **xinetd**: tidak tersedia/terpasang default di OS target modern.
- **Daemon terpisah**: menambah proses dan dependensi untuk dikelola.

## Konsekuensi

- Tidak ada proses yang selalu berjalan; systemd yang menangani koneksi.
- Kredensial clustercheck disimpan di `/etc/tera/clustercheck.cnf` (`0640 root:mysql`).
