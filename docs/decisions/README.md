# Architecture Decision Records (ADR)

Keputusan desain Tera dicatat di sini.

## Aturan

- ADR berstatus `Accepted` **tidak diubah** isinya, kecuali lewat aturan erratum di bawah.
- **Erratum:** koreksi faktual yang tidak mengubah keputusan (typo, nama module/collection/path yang
  berganti, tautan) boleh langsung diedit. Tambahkan catatan di bagian `## Revisi` di akhir ADR:
  `- YYYY-MM-DD: <alasan singkat>`. Jika ragu apakah sebuah koreksi mengubah keputusan, anggap mengubah.
- Untuk mengubah keputusan, buat ADR baru yang menyebut `Supersedes NNNN`, lalu ubah status ADR lama menjadi `Superseded by MMMM`.
- Perubahan kode yang bertentangan dengan ADR `Accepted` harus didahului ADR baru dan diskusi.
- Nama file: `NNNN-judul-singkat.md`, nomor berurutan.

## Template

```markdown
# NNNN. Judul keputusan

- **Status:** Proposed | Accepted | Supersedes NNNN | Superseded by NNNN
- **Tanggal:** YYYY-MM-DD

## Konteks

## Keputusan

## Alternatif yang ditolak

## Konsekuensi

## Revisi
<!-- hanya untuk erratum: - YYYY-MM-DD: alasan singkat -->
```

## Daftar

| No | Keputusan | Status |
|---|---|---|
| [0001](0001-inventory-per-cluster.md) | Satu cluster satu folder inventory | Accepted |
| [0002](0002-custom-config-merge-ini.md) | Custom config via merge_ini ke satu file 99-tera.cnf | Accepted |
| [0003](0003-galera-first-ha.md) | Galera sebagai HA pertama | Accepted |
| [0004](0004-haproxy-single-writer.md) | HAProxy single_writer sebagai default | Accepted |
| [0005](0005-clustercheck-systemd-socket.md) | Health check tera-clustercheck via systemd socket | Accepted |
| [0006](0006-no-auto-bootstrap.md) | Tidak ada auto bootstrap cluster lama | Accepted |
| [0007](0007-rolling-restart-play.md) | Rolling restart lewat play serial: 1, bukan handler | Accepted |
| [0008](0008-root-unix-socket.md) | Root MariaDB via unix_socket, admin remote terpisah | Accepted |
| [0009](0009-restart-pending-marker.md) | Restart pending marker | Accepted |
| [0010](0010-firewalld-galera-ports.md) | Tera mengelola firewalld untuk port Galera | Superseded by 0011 |
| [0011](0011-firewalld-scope-and-sources.md) | Firewalld untuk semua mode, sumber klien, clustercheck hanya dari LB | Supersedes 0010 |
| [0012](0012-backup-mariabackup.md) | Backup MariaDB dengan mariabackup | Accepted |
| [0013](0013-restore-mariabackup.md) | Restore dari backup mariabackup | Accepted (pengiriman: lihat 0014) |
| [0014](0014-restore-receiver-user.md) | Penerima restore khusus dan kunci sementara ber-TTL | Accepted |
