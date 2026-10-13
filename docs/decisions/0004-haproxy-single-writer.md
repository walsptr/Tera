# 0004. HAProxy single_writer sebagai default

- **Status:** Accepted
- **Tanggal:** 2026-10-14

## Konteks

Menulis ke beberapa node Galera sekaligus dapat menimbulkan konflik sertifikasi (deadlock error di aplikasi) pada beban tulis tinggi pada baris yang sama.

## Keputusan

- Default `mariadb_lb_mode: single_writer`: satu node aktif (db01), node lain `backup`.
- `multi_writer` tersedia sebagai opsi.

## Alternatif yang ditolak

- **Round robin sebagai default**: rawan konflik sertifikasi.

## Konsekuensi

- Kapasitas tulis = satu node; baca bisa diarahkan aplikasi sendiri jika perlu.
- Failover writer ditangani health check HAProxy.
