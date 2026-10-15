# 0013. Restore dari backup mariabackup

- **Status:** Proposed
- **Tanggal:** 2026-10-16

## Konteks

Backup (ADR 0012) baru berguna jika restore-nya terbukti. Restore adalah operasi paling berisiko di Tera:
mengganti data yang sedang hidup, dan di Galera mematikan seluruh cluster. Restore harus berinteraksi benar
dengan marker bootstrap (ADR 0006), marker datadir, restart pending marker (ADR 0009), user SST (aturan 4),
dan pengaman SST.

Temuan spike yang relevan (`docs/spikes/2026-10-16-mariabackup-galera.md`): di 11.4 incremental harus
diterapkan ke full yang sudah di-prepare, berurutan; hasil prepare bisa diverifikasi dengan `mariadbd`
sementara tanpa menyentuh service.

Keputusan pemilik proyek (2026-10-16): di Galera datadir lama dipindahkan ke samping hanya di node restore
(joiner ditimpa SST); prechecks ruang disk sebelum service apa pun dihentikan; cara membersihkan datadir lama
didokumentasikan; restore lintas cluster tidak di Fase 4a.

## Keputusan

### Perintah

```bash
./tera restore -i inventory/<cluster> --yes-i-really-really-mean-it \
    -e mariadb_restore_backup=<chain_id>/<sequence>|latest \
    [-e mariadb_restore_host=<node>] \
    [-e mariadb_restore_source=local|<nama target>] \
    [-e mariadb_restore_gpg_private_key=<file di controller>]
```

- Playbook terpisah `playbooks/mariadb-restore.yml`, seperti `tera recover`. Tabel keputusan `deploy` tidak
  berubah.
- Tanpa `--yes-i-really-really-mean-it` ditolak. `--limit` ditolak di mode galera.
- `mariadb_restore_host`: standalone = satu-satunya node; galera = default `mariadb_bootstrap_host`.
- `mariadb_restore_source`: default `local` (`mariadb_backup_dir` di node restore); nama target berarti backup
  diambil dulu lewat script target (`fetch`).
- Private key gpg (jika backup terenkripsi) disalin ke keyring sementara di node restore (`no_log`) dan dihapus
  di akhir, juga saat gagal.

### Tahap 1: validasi dan persiapan, tanpa menghentikan service

Semua langkah ini selesai sebelum service apa pun dihentikan. Kegagalan di tahap ini tidak menimbulkan downtime.

1. Baca `tera-backup.json` rantai sampai backup yang diminta. Tolak jika:
   - `cluster` ≠ `tera_cluster_name` (restore lintas cluster belum didukung);
   - `mode` ≠ `mariadb_cluster_mode`;
   - seri MariaDB (`major.minor`) backup ≠ seri yang terpasang (beda patch hanya peringatan);
   - rantai tidak lengkap, urutan LSN tidak bersambung, atau sha256 tidak cocok.
2. Prechecks ruang disk:
   - node restore: ruang bebas di `mariadb_backup_dir` ≥ ukuran backup yang dibongkar × 1,1 (staging);
     jika staging dan datadir di filesystem berbeda, ruang bebas di filesystem datadir juga ≥ hasil prepare;
   - joiner galera: ruang bebas + ukuran datadir sekarang ≥ hasil prepare × 1,1 (SST menimpa datadir).
3. Di node restore: dekripsi (jika perlu), bongkar ke `<mariadb_backup_dir>/.restore/<id>/`, prepare full lalu
   incremental berurutan.
4. Verifikasi hasil prepare dengan `mariadbd --no-defaults --skip-networking --socket=<tmp>` (sama dengan
   verifikasi level 2 ADR 0012).
5. Tampilkan ringkasan: backup yang dipakai (id, waktu, versi, posisi galera), node restore, node yang akan
   ditimpa SST, lokasi datadir lama, perkiraan downtime. Lalu tahap 2 dimulai.

### Tahap 2: standalone

1. Hentikan timer backup dan tunggu lock backup dilepas.
2. Stop MariaDB.
3. Pindahkan datadir ke `<mariadb_datadir>.pre-restore-<id>` (rename, tidak dihapus).
4. `mariabackup --move-back` (atau `--copy-back` jika staging di filesystem lain), `chown -R mysql:mysql`,
   `restorecon` di SELinux.
5. Marker datadir tetap ada; `mysql/` ada setelah langkah 4, sehingga pengaman datadir tidak terpicu.
6. Start MariaDB dengan config yang ada di disk, tunggu port.
7. Jalankan ulang `users.yml`: tabel `mysql.*` kembali ke waktu backup, sehingga password user Tera bisa
   berbeda dari `passwords.yml`.
8. Hapus restart pending marker (service menyala dengan config terbaru, ADR 0009).
9. Nyalakan lagi timer backup. Backup berikutnya wajib full (rantai lama mewakili data sebelum restore).
10. Tampilkan lokasi datadir lama dan perintah untuk menghapusnya setelah operator yakin.

### Tahap 2: galera

1. Hentikan timer backup di node backup dan tunggu lock dilepas.
2. Stop MariaDB di **semua** node. Cluster down dari sini sampai node restore Synced.
3. Di node restore: pindahkan datadir ke samping, `--move-back`/`--copy-back`, `chown`, `restorecon`. Tanpa
   `grastate.dat`, `galera_new_cluster` membuat cluster dengan UUID baru dari data hasil restore.
4. `galera_new_cluster` di node restore, tunggu Synced.
5. Jalankan `users.yml` di node restore, **termasuk user SST**, sebelum joiner mana pun di-start (aturan 4):
   user SST hasil restore bisa memakai password lama.
6. Joiner di-start dengan `throttle: 1`. UUID mereka berbeda dengan cluster baru, sehingga mereka menerima SST
   penuh dari node restore. Datadir joiner tidak dipindahkan ke samping (keputusan pemilik proyek). Pengaman
   SST deploy (node tanpa marker yang punya data user) tidak dipakai di sini, karena penimpaan adalah tujuan
   restore dan sudah dikonfirmasi dengan flag.
7. Tunggu semua node Synced.
8. Marker bootstrap ditulis (`force: false`) di semua node; marker datadir ada di semua node.
9. Hapus restart pending marker di semua node setelah semua Synced (seperti `tera recover`).
10. Nyalakan lagi timer backup; backup berikutnya wajib full.
11. Tampilkan lokasi datadir lama di node restore dan cara menghapusnya.

### Jika gagal di tahap 2

- Setiap langkah mencetak keadaan dan langkah pemulihan:
  - gagal sebelum node restore Synced: datadir lama masih utuh di `<datadir>.pre-restore-<id>`; pesan error
    berisi perintah untuk mengembalikannya, lalu `tera recover`;
  - joiner gagal SST: `tera restore` tidak diulang; cukup `tera deploy` (cluster sudah alive, joiner di-join).
    Jika datadir joiner tertinggal kosong, pengaman datadir menolak dan pesan menjelaskan langkahnya.
- Restore tidak pernah menghapus datadir lama secara otomatis.

### Hubungan dengan ADR lain

- **ADR 0006:** restore adalah perintah eksplisit operator, seperti `tera recover`. `deploy` tetap tidak pernah
  mem-bootstrap cluster lama secara otomatis.
- **ADR 0007:** restore tidak memakai handler; start/stop terjadi di playbook restore, satu node per langkah
  untuk joiner.
- **ADR 0009:** restart pending marker dihapus setelah service menyala dengan config di disk.
- **Pengaman datadir:** tidak terpicu selama restore berjalan benar; tetap melindungi joiner yang tertinggal
  kosong.

### Membersihkan datadir lama

README dan output restore menjelaskan:

```bash
# di node restore, setelah aplikasi diverifikasi
sudo rm -rf /var/lib/mysql.pre-restore-<id>
```

Tera tidak menghapusnya sendiri. Prechecks restore berikutnya memberi peringatan jika ada direktori
`*.pre-restore-*` lama yang memakan ruang.

## Alternatif yang ditolak

- **Restore lewat `tera deploy`:** operasi destruktif tersembunyi di perintah rutin (sama dengan alasan ADR 0006).
- **Stop service dulu, baru validasi dan prepare:** memperpanjang downtime dan bisa berakhir dengan cluster mati
  karena backup rusak.
- **Memakai `grastate.dat`/posisi galera dari backup untuk mempertahankan UUID cluster lama:** node lain dengan
  posisi lebih baru bisa mencoba IST dari state yang tidak cocok. UUID baru memaksa SST penuh yang bersih.
- **Memindahkan datadir joiner ke samping:** butuh ruang ×2 di setiap node; data joiner sama dengan data cluster
  yang sedang dipulihkan (keputusan pemilik proyek).
- **Restore ke semua node secara paralel tanpa SST:** butuh backup di setiap node dan rawan inkonsistensi.

## Konsekuensi

- Restore Galera = downtime seluruh cluster, dari stop semua node sampai node restore Synced. Joiner menyusul
  lewat SST setelah klien sudah bisa dilayani oleh node restore.
- Data setelah backup terakhir hilang (point-in-time recovery dari binlog adalah kandidat ADR terpisah).
- Node restore butuh ruang untuk staging + datadir lama sampai operator menghapusnya.
- Setelah restore, rantai backup lama tetap ada sesuai retensi, tetapi backup berikutnya selalu full.
