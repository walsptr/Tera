# 0012. Backup MariaDB dengan mariabackup

- **Status:** Accepted
- **Tanggal:** 2026-10-16

## Konteks

Tera belum punya backup. Operator butuh backup full dan incremental yang terjadwal, punya retensi, bisa
diverifikasi, disalin ke luar node, dan aman dipakai di cluster Galera tanpa mengganggu klien.

Spike `docs/spikes/2026-10-16-mariabackup-galera.md` (MariaDB 11.4.13) menunjukkan:

- node desync sendiri hanya selama `BACKUP STAGE BLOCK_DDL` (salinan file non-InnoDB dan ekor redo log).
  Salinan InnoDB, yaitu sebagian besar waktu backup, berjalan saat node masih Synced;
- tidak ada dampak flow control ke cluster (write lewat VIP 0 error, latensi tidak berubah);
- selama desync clustercheck menjawab 503 dan HAProxy mengeluarkan node dari pool (sekitar 1,7 s setelah
  desync, kembali sekitar 1,2 s setelah resync);
- `--throttle` memperpanjang jendela desync (< 2 s menjadi 25 s di data uji), karena file kecil di
  `BLOCK_DDL` ikut diperlambat;
- backup di writer `single_writer` menyebabkan failover, write gagal, dan sesi diputus saat writer kembali.

Keputusan pemilik proyek (2026-10-16): penyimpanan lokal + rsync/ssh sebagai lapisan target terpisah; gpg;
salinan remote wajib terenkripsi; node backup default node terakhir dan writer ditolak; full mingguan +
incremental harian via systemd timer; retensi per jumlah rantai; kredensial root via unix_socket; metadata
lengkap di setiap backup; backup opt-in; node hanya bisa menulis ke host backup; verifikasi level 2 otomatis
setelah full dengan prioritas rendah.

## Keputusan

### Alat, format, dan lokasi

- `mariabackup` dijalankan sebagai root lewat unix_socket (ADR 0008), dengan `--galera-info` di mode galera.
  Tidak ada user atau password backup.
- Tanpa `--throttle` secara default. Opsi `mariadb_backup_throttle` (kosong = tidak dipakai) tersedia, dengan
  efek samping yang dicatat di README: jendela desync di Galera ikut memanjang.
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
      │   ├── SHA256SUMS
      │   └── tera-backup.json         # metadata, ditulis paling akhir
      └── 01-incremental-20261019T010000Z/ ...
  ```

- Backup yang belum selesai ditulis ke nama `*.partial` dan baru di-rename setelah semua langkah sukses.
  Backup tanpa `tera-backup.json` dianggap tidak ada.

### Metadata (`tera-backup.json`)

Wajib di setiap backup, agar restore lintas cluster bisa ditambahkan nanti tanpa mengubah format:
`format_version` (1), `cluster` (`tera_cluster_name`), `mode` (`standalone`/`galera`), `host`, `type`
(`full`/`incremental`), `chain_id`, `sequence`, `parent` (backup sebelumnya di rantai), `started_at` dan
`finished_at` (UTC), `mariadb_version` (dari `mariadb_backup_info`), `from_lsn`/`to_lsn`, `compression` (`zstd`), `encrypted` + `gpg_fingerprint`, `size_bytes`,
`sha256`, `datadir_size_bytes` (ukuran datadir saat backup; dasar prechecks ruang disk restore).

- Variabel global baru `tera_cluster_name` (default nama folder inventory), dan
  `mariadb_galera_cluster_name` mengikutinya secara default (nilainya sama dengan sekarang).

### Aktivasi

- `mariadb_backup_enabled: false` (default). Backup opt-in agar disk tidak terisi tanpa disadari.
- Selama `false`, setiap `deploy` dan `reconfigure` menampilkan peringatan jelas bahwa backup belum aktif dan
  cara mengaktifkannya. Quickstart README memuat langkah aktivasi.
- Mengubah ke `false` setelah aktif: timer dan unit dimatikan; backup yang sudah ada tidak dihapus.

### Node yang menjalankan backup

- Standalone: satu-satunya node.
- Galera: `mariadb_backup_host` (default node **terakhir** di group `mariadb`, yaitu backup di HAProxy).
- Prechecks menolak node writer (node pertama, mode `single_writer`) kecuali `mariadb_backup_allow_writer: true`.
- Node backup keluar dari pool HAProxy **hanya selama `BACKUP STAGE BLOCK_DDL`**, bukan selama seluruh backup.
  Lamanya bergantung pada jumlah dan ukuran data non-InnoDB (`.frm`, Aria/MyISAM), bukan ukuran InnoDB.
  Prechecks dan README mencatat bahwa dengan 3 node hanya tersisa satu kandidat failover selama jendela itu.
- Tidak ada `SET GLOBAL wsrep_desync` manual: server sudah desync di tahap yang tepat.
- `mariadb_clustercheck_available_when_donor` tetap `false`, agar node dengan applier yang di-pause tidak
  melayani data basi.
- Script backup menolak berjalan jika node tidak Synced (`wsrep_local_state = 4`) atau cluster tidak Primary,
  misalnya saat node sedang menjadi donor SST atau sedang di-restart.

### Penjadwalan dan eksekusi

- Script `tera-backup` (dirender Tera) dan systemd unit di node backup:
  - `tera-backup-full.timer`: `OnCalendar={{ mariadb_backup_full_schedule }}`
    (default `Sun *-*-* 01:00:00`);
  - `tera-backup-incremental.timer`: `OnCalendar={{ mariadb_backup_incremental_schedule }}`
    (default `Mon..Sat *-*-* 01:00:00`);
  - `RandomizedDelaySec={{ mariadb_backup_randomized_delay }}` (default `15min`), `Persistent=true`.
- Incremental tanpa rantai yang valid (belum ada full, full terakhir gagal, atau ada restore sejak full
  terakhir) otomatis menjadi full.
- Satu backup per node dalam satu waktu: `flock` pada `/run/lock/tera-mariadb-backup.lock` (`mariadb_backup_lock`).
- `tera backup -i <cluster> [-e mariadb_backup_type=full|incremental]` menjalankan unit yang sama dan
  menunggu hasilnya. `tera backup-status -i <cluster>` menampilkan status.
- Status terakhir ditulis ke `/etc/tera/mariadb-backup.status` (JSON): per tipe waktu, hasil, id backup,
  ukuran; hasil push per target; hasil verifikasi level 2. File ini kontrak untuk exporter di Fase 4b.
  Kegagalan juga terlihat sebagai unit systemd `failed`.

### Target penyimpanan (lapisan terpisah)

- Backup selalu ditulis dulu ke target **lokal** (`mariadb_backup_dir`).
- Salinan ke luar node lewat daftar `mariadb_backup_targets`. Setiap entri punya `name` dan `type`; setiap tipe
  adalah script target terpisah di node dengan antarmuka yang sama (`push <backup_dir>`). Fase 4a hanya tipe
  `rsync`. S3/MinIO nanti = script tipe baru, tanpa mengubah format atau script backup.
- Push dilakukan setelah backup lokal sukses dan lolos verifikasi level 1. Kegagalan push dicatat di status
  (backup lokal tetap sah) dan dicoba lagi pada backup berikutnya untuk backup yang belum terkirim.

### Host backup (tipe `rsync`): node hanya bisa menulis

- Host backup ada di group inventory `mariadb_backup_target` dan dikelola role kecil `backup_target`:
  user `tera-backup`, direktori `mariadb_backup_target_dir` (default `/srv/tera-backup`), paket `rsync` dan
  `rrsync` (Ubuntu: paket `rsync`; EL9: `rsync-rrsync`).
- Kunci SSH khusus dibuat di node backup (`/etc/tera/backup/id_ed25519`, `0600 root`). Public key-nya dipasang
  di host backup dengan
  `command="rrsync -wo -no-del <dir>/<cluster>/<host>",restrict,from="<alamat node>"`. Host key host backup
  dipasang di `known_hosts` node oleh Tera (tanpa `StrictHostKeyChecking=no`).
- Dengan kredensial permanennya, node **tidak bisa membaca, mendaftar, atau menghapus** backup remote.
  Keterbatasan yang dicatat: `-wo` tidak mencegah menimpa file dengan nama yang sama; immutability penuh
  (mis. object lock) menunggu target S3.
- Node mengirim `tera-backup.json` paling akhir. Host backup menganggap backup lengkap jika metadata ada dan
  checksum cocok.
- Di host backup, timer `tera-backup-target.timer` (role `backup_target`) menjalankan script yang:
  - verifikasi level 1: `sha256sum -c SHA256SUMS` setiap backup baru, hasilnya `.verified` atau `.failed`
    di samping backup;
  - retensi: per `<cluster>/<host>`, simpan `mariadb_backup_keep_full` rantai terbaru yang full-nya lengkap
    dan terverifikasi; hapus rantai yang lebih lama. Rantai yang belum lengkap tidak menghitung dan tidak
    menyebabkan penghapusan.

### Enkripsi

- gpg dengan **public key** (`mariadb_backup_gpg_public_key`, path file armored, mis.
  `inventory/<cluster>/config/backup/backup.pub.asc`). Node hanya menyimpan public key di keyring khusus
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

- Berdasarkan **jumlah rantai**: `mariadb_backup_keep_full` (default `2`), di node dan di host backup.
- Di node, rantai lama dihapus hanya setelah full baru selesai **dan** lolos verifikasi level 1. Di host
  backup, aturan yang sama dijalankan host backup sendiri.
- Bukan berbasis umur, karena backup yang gagal diam-diam bisa membuat semua backup lama melewati batas umur
  dan terhapus, sehingga tidak ada backup tersisa. Dengan jumlah rantai, backup lama hanya terhapus jika ada
  pengganti yang terbukti baik.

### Verifikasi

- **Level 1, setiap backup:** mariabackup exit 0 dan `completed OK!`; `from_lsn` incremental sama dengan
  `to_lsn` parent; sha256 payload dicatat lalu dibaca ulang; metadata lengkap. Di host backup: checksum
  diperiksa ulang oleh host backup.
- **Level 2, otomatis setelah setiap full** (`mariadb_backup_verify_after_full: true`, bisa dimatikan) dan
  on-demand lewat `tera backup-verify`:
  - unit `tera-backup-verify.service` dengan `Nice=19`, `IOSchedulingClass=idle`, dan
    `MemoryMax={{ mariadb_backup_verify_memory_max }}` (default `1G`);
  - bongkar stream ke `<mariadb_backup_dir>/.verify/`, prepare full lalu incremental berurutan, nyalakan
    `mariadbd --no-defaults --skip-networking --user=mysql --socket=<tmp>`, cek bahwa setiap tabel bisa dibuka dan
    `CHECK TABLE` lulus, lalu hapus direktori sementara;
  - jika ruang sementara tidak cukup, verifikasi dilewati dengan status `warning` (backup tidak dibatalkan);
  - backup lokal terenkripsi (`mariadb_backup_encrypt_local: true`) tidak bisa diverifikasi otomatis karena
    private key tidak ada di node; status `skipped`, dan `tera backup-verify` dengan private key tetap bisa;
  - hasilnya ditulis ke file status.

### Ruang disk

- Sebelum mengambil lock backup: ruang bebas di `mariadb_backup_dir` harus ≥ ukuran datadir untuk full (atau
  ukuran incremental terakhir × 2, minimal 1 GB, untuk incremental), ditambah ukuran file sementara enkripsi
  jika ada. Jika kurang, backup gagal sebelum menyentuh server.

### Interaksi dengan operasi lain

- **Rolling restart menunggu backup:** restart sebuah node dijalankan di bawah lock backup
  (`flock -w {{ mariadb_backup_lock_timeout }}`, default 2 jam). Jika batas waktu habis, run gagal dengan pesan
  yang menyebut node, backup yang sedang berjalan, dan cara melanjutkan. Backup yang mulai saat node belum
  Synced kembali akan menolak sendiri.
- **Restore menghentikan backup** (ADR 0013): timer backup di semua node dihentikan sementara, marker
  `/etc/tera/mariadb-restore.active` ditulis (script backup menolak berjalan selama marker ada), dan lock
  diambil setelah backup yang sedang berjalan selesai. Setelah restore, timer dipulihkan dan marker dihapus.
- `tera destroy` menghentikan dan menghapus timer, unit, script, dan `/etc/tera/backup`, tetapi **tidak pernah
  menghapus isi `mariadb_backup_dir`** (juga tanpa `--keep-data`). Ringkasan destroy menyebut lokasinya.
- Tidak ada port baru (hanya ssh keluar ke host backup).

## Alternatif yang ditolak

- **Backup dalam bentuk direktori (`--target-dir`), bukan stream:** tidak terkompresi, butuh ruang 1:1, dan
  sulit dienkripsi atau disalin sebagai satu file.
- **`SET GLOBAL wsrep_desync=ON` selama seluruh backup:** node keluar dari pool selama seluruh backup, padahal
  server hanya perlu desync di `BLOCK_DDL` (spike).
- **Backup di writer secara default:** menyebabkan failover dan pemutusan sesi (spike E4/E6).
- **`--throttle` secara default:** memperpanjang jendela desync (spike E5).
- **Cron di controller:** backup berhenti jika controller mati atau laptop operator tidak menyala.
- **Retensi berbasis umur:** lihat bagian Retensi.
- **Node dengan akses baca-tulis ke host backup:** node yang dibobol bisa membaca atau menghapus semua backup
  remote.
- **Enkripsi simetris (passphrase di node):** node yang dibobol bisa membaca backup remote.
- **User MariaDB khusus backup:** butuh password di disk; root via unix_socket sudah cukup (ADR 0008).
- **Backup aktif secara default:** bisa mengisi disk tanpa disadari.

## Konsekuensi

- Jendela desync membuat node backup keluar dari pool beberapa detik per backup. Database dengan banyak tabel
  non-InnoDB, atau `mariadb_backup_throttle`, memperpanjang jendela itu.
- Operator wajib menyimpan private key gpg di luar node. Tanpa private key, salinan remote tidak bisa dipakai.
- Backup lokal di disk yang sama dengan datadir tidak melindungi dari kegagalan disk; README menyarankan disk
  terpisah dan host backup.
- Host backup menjadi bagian inventory (role `backup_target`), dan retensinya berjalan di sana.
- Format `tera-backup.json` versi 1 menjadi kontrak untuk restore, termasuk restore lintas cluster nanti.

## Revisi

- 2026-10-16: diterima setelah review pemilik proyek. Perubahan dari draft: backup opt-in dengan peringatan,
  host backup tulis-saja (`rrsync -wo -no-del`) dengan retensi dan verifikasi checksum di host backup,
  verifikasi level 2 otomatis setelah full dengan prioritas rendah, tanpa `--throttle` secara default, jendela
  desync hanya di `BLOCK_DDL`, dan penghentian backup selama restore.
- 2026-10-16: erratum saat implementasi (keputusan tidak berubah): path lock menjadi
  `/run/lock/tera-mariadb-backup.lock`; metadata menambah `datadir_size_bytes`; `mariadbd` sementara untuk
  verifikasi berjalan sebagai root (`--user=root`) di salinan root-only tanpa jaringan, sehingga pohon backup
  tidak perlu dibuka untuk user `mysql`; `galera_position` bernilai `null`, karena mariabackup
  11.4 tidak menulis `mariadb_backup_galera_info` ke `--extra-lsndir` (file itu tetap ada di dalam stream; restore
  tidak membutuhkannya karena membuat cluster dengan UUID baru).
- 2026-10-16: field `galera_position` dihapus dari metadata (selalu `null` dengan mariabackup 11.4; restore tidak
  memakainya). `format_version` tetap 1. `mariadbd` sementara verifikasi berjalan sebagai `mysql` (ADR 0014).
