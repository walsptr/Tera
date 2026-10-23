# 0018. Perubahan config dinamis lewat SET GLOBAL

- **Status:** Accepted (memperhalus ADR 0009; ADR 0007 tetap berlaku untuk semua restart)
- **Tanggal:** 2026-10-16

## Konteks

Saat ini setiap perubahan `99-tera.cnf` menulis restart pending marker (ADR 0009) dan memicu rolling restart
(ADR 0007), juga untuk variabel yang bisa diubah saat berjalan (`max_connections`, `wait_timeout`, ...).
Di Galera, rolling restart berarti failover writer dan sesi yang terputus.

Keputusan sebelumnya: whitelist dikelola Tera, operator boleh menambah lewat variabel. `SET GLOBAL` diterapkan di
node pertama dulu; gagal di sana = run gagal tanpa menulis config ke node mana pun; berhasil di node pertama
tetapi gagal di node lain = restart pending marker untuk node itu dan selesai lewat rolling restart. Kedua jalur
diuji.

## Keputusan

### Kapan jalur dinamis dipakai

- Whitelist `_mariadb_dynamic_variables` (vars role, dikelola Tera) ditambah `mariadb_dynamic_variables_extra`
  (list, default `[]`, operator). Nama dinormalisasi (`-` → `_`, huruf kecil).
- Variabel `wsrep_*` dan variabel yang berdampak ke seluruh cluster tidak pernah dinamis, termasuk jika ditulis di
  `mariadb_dynamic_variables_extra` (prechecks menolak).
- Jalur dinamis dipakai di sebuah node hanya jika **semua** key yang berubah di `99-tera.cnf` node itu ada di
  whitelist, berada di section server (`[mysqld]`, `[mariadb]`, `[server]`, `[galera]`), dan tidak ada key yang
  dihapus (`__remove__` atau hilang dari config). Jika tidak, perilaku ADR 0009 apa adanya (marker + rolling
  restart).

### Urutan

1. Semua node menghitung perubahan (`copy` `check_mode`, seperti sekarang) dan memutuskan dinamis atau restart.
2. **Node pertama** (node pertama di `groups['mariadb']` yang jalur dinamis): `SET GLOBAL` setiap key, lalu
   membaca kembali nilainya. Jika salah satu gagal, atau nilai terbaca berbeda setelah normalisasi (mis. server
   memotong nilai di luar rentang), nilai yang sudah diubah di node itu dikembalikan ke nilai sebelumnya, dan
   **run gagal tanpa menulis config ke node mana pun**.
3. Node lain dengan jalur dinamis: `SET GLOBAL` + baca kembali. Jika gagal di node itu: restart pending marker
   ditulis untuk node itu (sebelum config ditulis, seperti ADR 0009), sehingga rolling restart menyelesaikannya.
4. Semua node menulis `99-tera.cnf`. Node yang sukses di jalur dinamis tidak mendapat marker dan tidak di-restart.

### Normalisasi dan tampilan

- Ukuran dengan sufiks (`K`, `M`, `G`, `T`) dikonversi ke byte; boolean (`ON/OFF`, `1/0`, `true/false`)
  disamakan; enum dibandingkan tanpa beda huruf besar/kecil. Nilai yang tidak bisa dinormalisasi dibandingkan
  sebagai teks.
- `--check --diff` menampilkan per node: key, nilai berjalan → nilai baru, dan apakah "tanpa restart" atau
  "restart". Pada run `--check`, tidak ada `SET GLOBAL`.
- `SET GLOBAL` lewat root unix_socket (ADR 0008). Nilai global hanya berlaku untuk sesi baru untuk variabel
  sesi seperti `wait_timeout`; README menyebutnya.

## Alternatif yang ditolak

- **`SET GLOBAL` di semua node paralel:** nilai yang tidak valid gagal di semua node sekaligus dan config sudah
  tertulis; rolling restart dengan nilai itu bisa membuat MariaDB gagal start.
- **Gagal di node mana pun = run gagal:** config node lain sudah konsisten dengan nilai yang terbukti valid di
  node pertama; menyelesaikan lewat restart lebih aman daripada meninggalkan node berbeda tanpa marker.
- **Whitelist hanya dari Tera:** operator butuh variabel yang belum dikenal Tera; `wsrep_*` tetap dikunci.
- **`SET PERSIST`:** tidak ada di MariaDB.

## Konsekuensi

- Perubahan variabel dinamis tidak lagi me-restart node; ADR 0009 tetap berlaku untuk semua perubahan lain.
- Nilai berjalan dan `99-tera.cnf` bisa berbeda sebentar di node yang menunggu rolling restart; marker
  mencatatnya.
- Test (skenario `reconfigure` diperluas, Ubuntu 24.04 dan Rocky 9; podman di CI): `max_connections` dan
  `wait_timeout` berubah tanpa restart (start timestamp sama, nilai aktif di 3 node, tanpa marker); `512M`
  dikonversi ke byte; variabel statis atau campuran memicu rolling restart; nilai tidak valid di node pertama:
  run gagal dan `99-tera.cnf` tidak berubah di semua node, nilai berjalan kembali; gagal di node lain saja
  (kegagalan `SET GLOBAL` disuntikkan di satu node lewat variabel khusus test `__tera_test_*`, lihat
  `docs/CONVENTIONS.md`, karena nilai yang sama sah di semua node; usulan Claude, disetujui pemilik pada review
  2026-10-16): marker ditulis dan rolling restart menyelesaikannya;
  `mariadb_dynamic_variables_extra` dengan `wsrep_*` ditolak; idempotence `changed=0`.

## Revisi

- 2026-10-18: keputusan pemilik proyek saat menyetujui rencana implementasi:
  - Whitelist awal konservatif (`roles/mariadb/vars/main.yml`): tanpa `innodb_buffer_pool_size` dan tanpa
    variabel berisi path file; operator bisa menambahkannya lewat `mariadb_dynamic_variables_extra` dengan risiko
    sendiri.
  - **Alias** dipetakan ke nama kanonik MariaDB 11.4 (`slow_query_log` → `log_slow_query`, `long_query_time` →
    `log_slow_query_time`, `min_examined_row_limit` → `log_slow_min_examined_row_limit`); `SET GLOBAL` dan
    pembacaan ulang memakai nama kanonik. Diuji.
  - **Nilai yang disesuaikan server** (mis. `max_allowed_packet` dibulatkan ke kelipatan 1024, `table_open_cache`
    dibatasi `open_files_limit`): pembacaan ulang yang berbeda = rollback lalu gagal, dengan pesan yang menyebut nilai
    yang diminta dan nilai efektif. Diuji dengan `max_allowed_packet = 1000000`.
  - **Pasangan yang saling membatasi** (`innodb_io_capacity` ≤ `innodb_io_capacity_max`): urutan `SET` mengikuti arah
    perubahan (batas atas dulu saat naik, terakhir saat turun). Diuji naik dan turun.
  - **Rollback** di node pertama mengembalikan **semua** key perubahan itu ke nilai berjalan sebelumnya (urutan
    terbalik), bukan hanya key yang gagal.
  - **Deny list** di luar `wsrep_*`: `binlog_*`, `log_bin*`, `gtid_*`, `auto_increment_*`, `server_id`, `read_only`,
    `innodb_flush_log_at_trx_commit`, `sync_binlog`; berlaku juga untuk `mariadb_dynamic_variables_extra` lewat
    prechecks.
  - README menjelaskan bahwa variabel per sesi hanya berlaku untuk koneksi baru. README dan `CUSTOM-CONFIG.md`
    menjelaskan bahwa Tera hanya membandingkan file config lama dan baru: `SET GLOBAL` manual di server tidak
    terdeteksi dan hilang saat restart berikutnya.
- 2026-10-18: detail implementasi, diusulkan Claude (bukan keputusan pemilik; sampaikan jika perlu diubah):
  - Perbandingan dan normalisasi ada di filter `plugins/filter/tera_cnf.py` (diuji pytest). Perubahan yang hanya
    menyentuh komentar (mis. baris `# Sources` karena file custom baru) dianggap jalur dinamis tanpa key, jadi tanpa
    restart.
  - Jalur dinamis butuh `99-tera.cnf` lama di node dan MariaDB yang berjalan; selain itu ADR 0009 (deploy pertama,
    node mati).
  - "Node pertama" adalah node pertama di jalur dinamis di antara host run ini (`ansible_play_hosts`, sehingga
    `reconfigure --limit` tetap berlaku). Pada `--check`, rencana ditampilkan tanpa `SET GLOBAL`.
  - Pengecualian scale in (ADR 0017) dievaluasi lebih dulu; perubahan yang menggabungkan penghapusan alamat dengan
    variabel dinamis tetap memakai restart (`wsrep_cluster_address` tidak pernah dinamis).
  - Test yang memang menguji jalur restart (ADR 0009 run terputus, lock backup, rolling restart `reconfigure`) kini
    menambahkan `max_prepared_stmt_count` (bukan variabel dinamis) agar tetap menguji restart.
