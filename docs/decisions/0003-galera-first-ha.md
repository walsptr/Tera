# 0003. Galera sebagai HA pertama

- **Status:** Accepted
- **Tanggal:** 2026-10-14

## Konteks

Tera membutuhkan satu topologi HA MariaDB pertama yang aman terhadap kehilangan transaksi dan sederhana untuk failover.

## Keputusan

- MariaDB Galera Cluster, minimal 3 node (`mariadb_galera_min_nodes`), SST memakai `mariabackup`.

## Alternatif yang ditolak

- **Async replication + MaxScale**: failover lebih kompleks dan berisiko kehilangan transaksi. Bisa ditambahkan kemudian lewat ADR baru.

## Konsekuensi

- Butuh minimal 3 node dan jaringan latensi rendah.
- Lifecycle bootstrap/join/recover harus ketat (lihat `docs/GALERA-LIFECYCLE.md`).
