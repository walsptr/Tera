# 0013. Restore dari backup mariabackup

- **Status:** Accepted
- **Tanggal:** 2026-10-16

## Konteks

Backup (ADR 0012) baru berguna jika restore-nya terbukti. Restore adalah operasi paling berisiko di Tera:
mengganti data yang sedang hidup, dan di Galera mematikan seluruh cluster. Restore harus berinteraksi benar
dengan marker bootstrap (ADR 0006), marker datadir, restart pending marker (ADR 0009), user SST (aturan 4),
pengaman SST, dan backup yang terjadwal.

Temuan spike yang relevan (`docs/spikes/2026-10-16-mariabackup-galera.md`): di 11.4 incremental harus
diterapkan ke full yang sudah di-prepare, berurutan; hasil prepare bisa diverifikasi dengan `mariadbd`
sementara tanpa menyentuh service.

Keputusan pemilik proyek (2026-10-16): di Galera datadir lama dipindahkan ke samping hanya di node restore
(joiner ditimpa SST); prechecks ruang disk sebelum service apa pun dihentikan; cara membersihkan datadir lama
didokumentasikan; restore lintas cluster tidak di Fase 4a; restore antar mode (standalone ↔ galera) adalah
jalur migrasi yang sah dengan override eksplisit; kredensial permanen node tidak boleh bisa membaca backup
remote, sehingga data dikirim dari host backup ke node, diorkestrasi controller.

## Keputusan

### Perintah

```bash
./tera restore -i inventory/<cluster> --yes-i-really-really-mean-it \
    -e mariadb_restore_backup=<chain_id>/<sequence>|latest \
    [-e mariadb_restore_host=<node>] \
    [-e mariadb_restore_source=local|<nama target>] \
    [-e mariadb_restore_gpg_private_key=<file di controller>] \
    [-e mariadb_restore_allow_mode_change=true]
```

- Playbook terpisah `playbooks/mariadb-restore.yml`, seperti `tera recover`. Tabel keputusan `deploy` tidak
  berubah.
- Tanpa `--yes-i-really-really-mean-it` ditolak. `--limit` ditolak di mode galera.
- `mariadb_restore_host`: standalone = satu-satunya node; galera = default `mariadb_bootstrap_host`.
- `mariadb_restore_source`: default `local` (`mariadb_backup_dir` di node yang membuat backup; jika bukan node
  restore, lihat "Pengiriman backup"); nama target berarti backup diambil dari host backup.
- Private key gpg (jika backup terenkripsi) disalin ke keyring sementara di node restore (`no_log`) dan dihapus
  di akhir, juga saat gagal.

### Pengiriman backup ke node restore

Kredensial permanen node hanya bisa menulis ke host backup (ADR 0012). Untuk restore, controller
mengorkestrasi pengiriman **dari** host backup **ke** node restore:

1. Controller membuat direktori staging di node restore: `<mariadb_backup_dir>/.incoming/<restore_id>/`.
2. Di host backup, controller membuat kunci SSH **sementara** (ed25519, di direktori sementara milik
   `tera-backup`, khusus restore ini).
3. Public key sementara itu dipasang di `authorized_keys` root node restore dengan
   `command="rrsync -wo <staging>",restrict,from="<alamat host backup>"` dan komentar `tera-restore-<id>`.
   Host key node dipasang di `known_hosts` sementara di host backup.
4. Host backup menjalankan `rsync` file rantai yang diperlukan (hanya yang terverifikasi `.verified`) ke staging.
5. Node memeriksa ulang `SHA256SUMS`.
6. Di blok `always`: entri `authorized_keys` `tera-restore-<id>` dihapus dari node dan kunci sementara dihapus
   dari host backup, juga saat restore gagal.

Hasilnya, node tidak pernah memegang kredensial untuk membaca host backup, dan kunci yang dipakai host backup
hanya bisa menulis ke staging di node selama restore berjalan. Pola yang sama (rsync antar node lewat kunci
sementara) dipakai jika `mariadb_restore_source: local` tetapi backup ada di node lain (mis. node backup galera
db03, sedangkan node restore db01).

### Backup terjadwal selama restore

- Sebelum tahap 2, di **semua** node MariaDB: timer backup dihentikan, marker `/etc/tera/mariadb-restore.active`
  ditulis (script backup menolak berjalan selama marker ada), dan Tera menunggu lock backup
  (`flock -w {{ mariadb_backup_lock_timeout }}`) agar backup yang sedang berjalan selesai dulu. Jika batas waktu
  habis, restore gagal sebelum menghentikan MariaDB.
- Setelah restore sukses: timer dipulihkan (hanya jika backup aktif) dan marker dihapus. Script backup
  mencatat bahwa ada restore sejak full terakhir, sehingga backup berikutnya wajib full.
- Jika restore gagal, marker sengaja dibiarkan: backup terjadwal tidak boleh membuat rantai dari data yang
  belum pasti. Pesan error menjelaskan cara melanjutkan (`tera restore` ulang, atau hapus marker setelah
  keadaan dipastikan).

### Tahap 1: validasi dan persiapan, tanpa menghentikan MariaDB

Semua langkah ini selesai sebelum MariaDB dihentikan. Kegagalan di tahap ini tidak menimbulkan downtime.

1. Baca `tera-backup.json` rantai sampai backup yang diminta. Tolak jika:
   - `cluster` ≠ `tera_cluster_name` (restore lintas cluster belum didukung);
   - seri MariaDB (`major.minor`) backup ≠ seri yang terpasang (beda patch hanya peringatan);
   - `mode` ≠ `mariadb_cluster_mode`, kecuali `mariadb_restore_allow_mode_change: true` (jalur migrasi
     standalone → galera dan sebaliknya);
   - rantai tidak lengkap, urutan LSN tidak bersambung, atau sha256 tidak cocok.
2. Prechecks ruang disk:
   - node restore: ruang bebas di `mariadb_backup_dir` ≥ ukuran backup yang dibongkar × 1,1 (staging);
     jika staging dan datadir di filesystem berbeda, ruang bebas di filesystem datadir juga ≥ hasil prepare;
   - joiner galera: ruang bebas + ukuran datadir sekarang ≥ hasil prepare × 1,1 (SST menimpa datadir).
3. Kirim backup ke node restore jika perlu (lihat di atas), dekripsi jika perlu, bongkar ke
   `<mariadb_backup_dir>/.restore/<id>/`, prepare full lalu incremental berurutan.
4. Verifikasi hasil prepare dengan `mariadbd --no-defaults --skip-networking --socket=<tmp>` (sama dengan
   verifikasi level 2 ADR 0012).
5. Tampilkan ringkasan: backup yang dipakai (id, waktu, versi, mode, posisi galera), node restore, node yang
   akan ditimpa SST, lokasi datadir lama. Lalu tahap 2 dimulai.

### Tahap 2: standalone

1. Hentikan backup terjadwal (lihat di atas).
2. Stop MariaDB.
3. Pindahkan datadir ke `<mariadb_datadir>.pre-restore-<id>` (rename, tidak dihapus).
4. `mariabackup --move-back` (atau `--copy-back` jika staging di filesystem lain), `chown -R mysql:mysql`,
   `restorecon` di SELinux.
5. Marker datadir tetap ada; `mysql/` ada setelah langkah 4, sehingga pengaman datadir tidak terpicu.
6. Start MariaDB dengan config yang ada di disk, tunggu port.
7. Jalankan ulang `users.yml`: tabel `mysql.*` kembali ke waktu backup, sehingga password user Tera bisa
   berbeda dari `passwords.yml`.
8. Hapus restart pending marker (service menyala dengan config terbaru, ADR 0009).
9. Pulihkan backup terjadwal; backup berikutnya wajib full.
10. Tampilkan lokasi datadir lama dan perintah untuk menghapusnya setelah operator yakin.

### Tahap 2: galera

1. Hentikan backup terjadwal di semua node.
2. Stop MariaDB di **semua** node. Cluster down dari sini sampai node restore Synced.
3. Di node restore: pindahkan datadir ke samping, `--move-back`/`--copy-back`, `chown`, `restorecon`. Tanpa
   `grastate.dat`, `galera_new_cluster` membuat cluster dengan UUID baru dari data hasil restore. Backup dari
   mode standalone (dengan override) masuk lewat jalur yang sama.
4. `galera_new_cluster` di node restore, tunggu Synced.
5. Jalankan `users.yml` di node restore, **termasuk user SST**, sebelum joiner mana pun di-start (aturan 4):
   user SST hasil restore bisa memakai password lama atau, untuk backup standalone, belum ada.
6. Joiner di-start dengan `throttle: 1`. UUID mereka berbeda dengan cluster baru, sehingga mereka menerima SST
   penuh dari node restore. Datadir joiner tidak dipindahkan ke samping. Pengaman SST deploy (node tanpa marker
   yang punya data user) tidak dipakai di sini, karena penimpaan adalah tujuan restore dan sudah dikonfirmasi
   dengan flag.
7. Tunggu semua node Synced.
8. Marker bootstrap ditulis (`force: false`) di semua node; marker datadir ada di semua node.
9. Hapus restart pending marker di semua node setelah semua Synced (seperti `tera recover`).
10. Pulihkan backup terjadwal; backup berikutnya wajib full.
11. Tampilkan lokasi datadir lama di node restore dan cara menghapusnya.

### Restore galera → standalone (dengan override)

Tahap 2 standalone dipakai. Tabel `mysql.wsrep_*` ikut ter-restore dan tidak dipakai di mode standalone.

### Jika gagal di tahap 2

- Setiap langkah mencetak keadaan dan langkah pemulihan:
  - gagal sebelum node restore Synced: datadir lama masih utuh di `<datadir>.pre-restore-<id>`; pesan error
    berisi perintah untuk mengembalikannya, lalu `tera recover` (galera) atau `systemctl start mariadb`
    (standalone);
  - joiner gagal SST: `tera restore` tidak diulang; cukup `tera deploy` (cluster sudah alive, joiner di-join).
    Jika datadir joiner tertinggal kosong, pengaman datadir menolak dan pesan menjelaskan langkahnya.
- Restore tidak pernah menghapus datadir lama secara otomatis.

### Hubungan dengan ADR lain

- **ADR 0006:** restore adalah perintah eksplisit operator, seperti `tera recover`. `deploy` tetap tidak pernah
  mem-bootstrap cluster lama secara otomatis.
- **ADR 0007:** restore tidak memakai handler; start/stop terjadi di playbook restore, satu node per langkah
  untuk joiner.
- **ADR 0009:** restart pending marker dihapus setelah service menyala dengan config di disk.
- **ADR 0012:** backup terjadwal dihentikan selama restore, dan backup berikutnya wajib full.
- **Pengaman datadir:** tidak terpicu selama restore berjalan benar; tetap melindungi joiner yang tertinggal
  kosong.

### Membersihkan datadir lama dan staging

README dan output restore menjelaskan:

```bash
# di node restore, setelah aplikasi diverifikasi
sudo rm -rf /var/lib/mysql.pre-restore-<id>
```

Direktori staging `.incoming/` dan `.restore/` dihapus otomatis setelah restore sukses. Tera tidak menghapus
datadir lama sendiri. Prechecks restore berikutnya memberi peringatan jika ada direktori `*.pre-restore-*` lama
yang memakan ruang.

## Alternatif yang ditolak

- **Restore lewat `tera deploy`:** operasi destruktif tersembunyi di perintah rutin (sama dengan alasan ADR 0006).
- **Stop service dulu, baru validasi dan prepare:** memperpanjang downtime dan bisa berakhir dengan cluster mati
  karena backup rusak.
- **Node menarik backup dari host backup dengan kredensial baca:** node yang dibobol bisa membaca semua backup
  remote (keputusan pemilik proyek).
- **Mengalirkan backup lewat controller (fetch lalu copy):** bandwidth dan ruang disk controller menjadi batas,
  dan laptop operator bisa terputus di tengah.
- **Memakai `grastate.dat`/posisi galera dari backup untuk mempertahankan UUID cluster lama:** node lain dengan
  posisi lebih baru bisa mencoba IST dari state yang tidak cocok. UUID baru memaksa SST penuh yang bersih.
- **Memindahkan datadir joiner ke samping:** butuh ruang ×2 di setiap node; data joiner sama dengan data cluster
  yang sedang dipulihkan (keputusan pemilik proyek).
- **Menolak perubahan mode tanpa pengecualian:** menutup jalur migrasi standalone → galera yang sah.

## Konsekuensi

- Restore Galera = downtime seluruh cluster, dari stop semua node sampai node restore Synced. Joiner menyusul
  lewat SST setelah klien sudah bisa dilayani oleh node restore.
- Data setelah backup terakhir hilang (point-in-time recovery dari binlog adalah kandidat ADR terpisah).
- Node restore butuh ruang untuk staging + datadir lama sampai operator menghapusnya.
- Controller membutuhkan akses SSH ke host backup (inventory group `mariadb_backup_target`) untuk restore dari
  remote.
- Setelah restore, rantai backup lama tetap ada sesuai retensi, tetapi backup berikutnya selalu full.

## Revisi

- 2026-10-16: diterima setelah review pemilik proyek. Perubahan dari draft: override
  `mariadb_restore_allow_mode_change`, pengiriman dari host backup ke node dengan kunci sementara, dan
  penghentian backup terjadwal di semua node selama restore.
