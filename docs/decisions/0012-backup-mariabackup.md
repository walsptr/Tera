# 0012. Backup MariaDB dengan mariabackup

- **Status:** Proposed
- **Tanggal:** 2026-10-16

## Konteks

Tera belum punya backup. Operator butuh backup full dan incremental yang terjadwal, punya retensi, bisa
diverifikasi, disalin ke luar node, dan aman dipakai di cluster Galera tanpa mengganggu klien.

Spike `docs/spikes/2026-10-16-mariabackup-galera.md` (MariaDB 11.4.13) menunjukkan:

- node desync sendiri hanya selama `BACKUP STAGE BLOCK_DDL` (salinan file non-InnoDB). Salinan InnoDB, yaitu
  sebagian besar waktu backup, berjalan saat node masih Synced;
- tidak ada dampak flow control ke cluster (write lewat VIP 0 error, latensi tidak berubah);
- selama desync clustercheck menjawab 503 dan HAProxy mengeluarkan node dari pool (sekitar 1,7 s setelah
  desync, kembali sekitar 1,2 s setelah resync);
- backup di writer `single_writer` menyebabkan failover, write gagal, dan sesi diputus saat writer kembali.

Keputusan pemilik proyek (2026-10-16): penyimpanan lokal + rsync/ssh sebagai lapisan target terpisah; gpg;
salinan remote wajib terenkripsi; node backup default node terakhir dan writer ditolak; full mingguan +
incremental harian via systemd timer; retensi per jumlah rantai; kredensial root via unix_socket; metadata
lengkap di setiap backup.

## Keputusan

### Alat, format, dan lokasi

- `mariabackup` dijalankan sebagai root lewat unix_socket (ADR 0008), dengan `--galera-info` di mode galera.
  Tidak ada user atau password backup.
- Setiap backup ditulis sebagai stream: `mariabackup --backup --stream=mbstream --extra-lsndir=<dir>` →
  `zstd` → (opsional `gpg`) → file. `--extra-lsndir` menyimpan `mariadb_backup_checkpoints` dan
  `mariadb_backup_info` di samping stream, sehingga incremental berikutnya memakai
  `--incremental-basedir=<lsndir backup sebelumnya>` tanpa membongkar stream.
- Satu **rantai** = satu full + incremental-nya. Tata letak di `mariadb_backup_dir`
  (default `/var/backups/tera/mariadb`, disarankan disk terpisah dari datadir):

  ```
  <mariadb_backup_dir>/<tera_cluster_name>/
  └── <chain_id>/                      # 20261018T010000Z (waktu UTC full)
      ├── 00-full-20261018T010000Z/
      │   ├── backup.mbstream.zst      # .gpg di akhir jika terenkripsi
      │   ├── lsn/                     # mariadb_backup_checkpoints, mariadb_backup_info
      │   ├── tera-backup.json         # metadata
      │   └── SHA256SUMS
      └── 01-incremental-20261019T010000Z/ ...
  ```

- Backup yang belum selesai ditulis ke nama `*.partial` dan baru di-rename setelah semua langkah sukses.
  Backup tanpa `tera-backup.json` dianggap tidak ada.

### Metadata (`tera-backup.json`)

Wajib di setiap backup, agar restore lintas cluster bisa ditambahkan nanti tanpa mengubah format:
`format_version` (1), `cluster` (`tera_cluster_name`), `mode` (`standalone`/`galera`), `host`, `type`
(`full`/`incremental`), `chain_id`, `sequence`, `parent` (backup sebelumnya di rantai), `started_at` dan
`finished_at` (UTC), `mariadb_version` (dari `mariadb_backup_info`), `from_lsn`/`to_lsn`, `galera_position`
(`uuid:seqno` atau `null`), `compression` (`zstd`), `encrypted` + `gpg_fingerprint`, `size_bytes`,
`sha256`.

- Variabel global baru `tera_cluster_name` (default nama folder inventory), dan
  `mariadb_galera_cluster_name` mengikutinya secara default (nilainya sama dengan sekarang).

### Node yang menjalankan backup

- Standalone: satu-satunya node.
- Galera: `mariadb_backup_host` (default node **terakhir** di group `mariadb`, yaitu backup di HAProxy).
- Prechecks menolak node writer (node pertama, mode `single_writer`) kecuali `mariadb_backup_allow_writer: true`.
- Prechecks dan README memberi peringatan: selama jendela desync node backup keluar dari pool, dan dengan 3
  node hanya tersisa satu kandidat failover. Jendela itu memanjang jika database punya banyak tabel non-InnoDB.
- Tidak ada `SET GLOBAL wsrep_desync` manual: server sudah desync di tahap yang tepat.
- `mariadb_clustercheck_available_when_donor` tetap `false`, agar node dengan applier yang di-pause tidak
  melayani data basi.
- Script backup menolak berjalan jika node tidak Synced (`wsrep_local_state = 4`) atau cluster tidak Primary,
  misalnya saat node sedang menjadi donor SST.

### Penjadwalan dan eksekusi

- Script `tera-backup` (dirender Tera) dan systemd unit di node backup:
  - `tera-backup-full.timer`: `OnCalendar={{ mariadb_backup_full_schedule }}`
    (default `Sun *-*-* 01:00:00`);
  - `tera-backup-incremental.timer`: `OnCalendar={{ mariadb_backup_incremental_schedule }}`
    (default `Mon..Sat *-*-* 01:00:00`);
  - `RandomizedDelaySec={{ mariadb_backup_randomized_delay }}` (default `15min`), `Persistent=true`.
- Incremental tanpa rantai yang valid (belum ada full, atau full terakhir gagal) otomatis menjadi full.
- Satu backup per node dalam satu waktu (`flock` di `/run/tera/backup.lock`).
- `tera backup -i <cluster> [-e mariadb_backup_type=full|incremental]` menjalankan unit yang sama dan
  menunggu hasilnya.
- Status terakhir (per tipe: waktu, hasil, id backup, ukuran, verifikasi) ditulis ke
  `/etc/tera/mariadb-backup.status` (JSON). File ini dibaca `tera backup-status` dan nanti oleh exporter
  (Fase 4b). Kegagalan juga terlihat sebagai unit systemd `failed`.
- Backup bersifat opt-in: `mariadb_backup_enabled` (lihat pertanyaan terbuka untuk nilai default).

### Target penyimpanan (lapisan terpisah)

- Backup selalu ditulis dulu ke target **lokal** (`mariadb_backup_dir`).
- Salinan ke luar node lewat daftar `mariadb_backup_targets`. Setiap entri punya `type`, dan setiap tipe adalah
  script target terpisah dengan antarmuka yang sama: `push <backup_dir>`, `list`, `fetch <id> <dir>`,
  `prune <chain_id>`. Fase 4a hanya tipe `rsync` (rsync lewat ssh ke host backup). S3/MinIO nanti = script
  tipe baru, tanpa mengubah format atau script backup.
- Push dilakukan setelah backup lokal sukses dan lolos verifikasi level 1. Rename `*.partial` di remote setelah
  checksum cocok.
- Kunci SSH khusus dibuat di node backup (`/etc/tera/backup/id_ed25519`, `0600 root`).

### Enkripsi

- gpg dengan **public key** (`mariadb_backup_gpg_public_key`, file armored di
  `inventory/<cluster>/config/backup/`). Node hanya menyimpan public key di keyring khusus
  `/etc/tera/backup/gnupg`. Private key tidak pernah ada di node; operator memberikannya saat restore.
- **Salinan remote wajib terenkripsi.** Prechecks menolak `mariadb_backup_targets` yang tidak kosong tanpa
  public key.
- Salinan lokal default **tidak** terenkripsi; opsi `mariadb_backup_encrypt_local` (default `false`).
  Alasannya:
  - root di node sudah bisa membaca datadir, jadi enkripsi lokal tidak melindungi dari pembaca yang sama;
  - restore darurat dari backup lokal tidak bergantung pada private key yang mungkin tidak tersedia saat itu,
    dan tidak membuang waktu untuk dekripsi.
- Jika salinan lokal tidak terenkripsi, push ke remote mengenkripsi dulu ke file sementara di
  `<mariadb_backup_dir>/.outgoing/` (lalu dihapus). Prechecks ruang disk memperhitungkannya.

### Retensi

- Berdasarkan **jumlah rantai**: `mariadb_backup_keep_full` (default `2`), lokal dan setiap target.
- Rantai lama dihapus hanya setelah full baru selesai **dan** lolos verifikasi level 1.
- Bukan berbasis umur, karena backup yang gagal diam-diam bisa membuat semua backup lama melewati batas umur
  dan terhapus, sehingga tidak ada backup tersisa. Dengan jumlah rantai, backup lama hanya terhapus jika ada
  pengganti yang terbukti baik.

### Verifikasi

- **Level 1, setiap backup:** mariabackup exit 0 dan `completed OK!`; `from_lsn` incremental sama dengan
  `to_lsn` parent; sha256 payload dicatat lalu dibaca ulang; metadata lengkap. Di remote: sha256 dicek setelah
  transfer.
- **Level 2, `tera backup-verify`** (on-demand): bongkar stream ke direktori sementara di
  `<mariadb_backup_dir>/.verify/`, prepare full lalu incremental berurutan, nyalakan
  `mariadbd --no-defaults --skip-networking --socket=<tmp>`, lalu cek bahwa setiap tabel bisa dibuka dan
  `CHECK TABLE` lulus. Untuk backup terenkripsi, private key diberikan saat itu dan dihapus setelahnya. Hasilnya
  dicatat di status.

### Ruang disk

- Sebelum mengambil lock backup: ruang bebas di `mariadb_backup_dir` harus ≥ ukuran datadir untuk full (atau
  ukuran incremental terakhir × 2, minimal 1 GB, untuk incremental), ditambah ukuran file sementara enkripsi
  jika ada. Jika kurang, backup gagal sebelum menyentuh server.

### Interaksi dengan operasi lain

- Rolling restart menunggu lock backup di node itu dilepas (dengan batas waktu) sebelum me-restart. Jika batas
  waktu habis, run gagal dengan pesan; backup tidak dibatalkan.
- `tera destroy` menghentikan dan menghapus timer, unit, script, dan `/etc/tera/backup`, tetapi **tidak pernah
  menghapus isi `mariadb_backup_dir`** (juga tanpa `--keep-data`). Ringkasan destroy menyebut lokasinya.
- Tidak ada port baru (hanya ssh keluar ke host backup).

## Alternatif yang ditolak

- **Backup dalam bentuk direktori (`--target-dir`), bukan stream:** tidak terkompresi, butuh ruang 1:1, dan
  sulit dienkripsi atau disalin sebagai satu file.
- **`SET GLOBAL wsrep_desync=ON` selama seluruh backup:** node keluar dari pool selama seluruh backup, padahal
  server hanya perlu desync di `BLOCK_DDL` (spike).
- **Backup di writer secara default:** menyebabkan failover dan pemutusan sesi (spike E4/E6).
- **Cron di controller:** backup berhenti jika controller mati atau laptop operator tidak menyala.
- **Retensi berbasis umur:** lihat bagian Retensi.
- **Enkripsi simetris (passphrase di node):** node yang dibobol bisa membaca backup remote.
- **User MariaDB khusus backup:** butuh password di disk; root via unix_socket sudah cukup (ADR 0008).

## Konsekuensi

- Jendela desync membuat node backup keluar dari pool beberapa detik per backup. Database dengan banyak tabel
  non-InnoDB memperpanjang jendela itu.
- Operator wajib menyimpan private key gpg di luar node. Tanpa private key, salinan remote tidak bisa dipakai.
- Backup lokal di disk yang sama dengan datadir tidak melindungi dari kegagalan disk; README menyarankan disk
  terpisah dan target remote.
- Format `tera-backup.json` versi 1 menjadi kontrak untuk restore, termasuk restore lintas cluster nanti.

## Pertanyaan terbuka (untuk review)

1. `mariadb_backup_enabled` default `false` (opt-in, tidak mengisi disk tanpa disadari) atau `true`?
2. Akses node ke host backup: (A) baca-tulis biasa, node yang melakukan prune remote; atau (B, disarankan)
   node hanya bisa menulis (`rrsync -wo -no-del` di `authorized_keys`), prune dan pembacaan untuk restore
   dilakukan dari host backup/controller. B mencegah node yang dibobol menghapus atau membaca backup remote,
   tetapi menambah role kecil untuk host backup (group inventory `mariadb_backup_target`).
3. Verifikasi level 2 hanya on-demand, atau otomatis setelah setiap full (butuh ruang sebesar backup yang
   dibongkar dan I/O tambahan di node backup)?
