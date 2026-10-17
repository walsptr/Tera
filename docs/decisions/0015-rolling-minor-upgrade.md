# 0015. Upgrade minor rolling

- **Status:** Accepted
- **Tanggal:** 2026-10-16

## Konteks

Fase 4b menambah upgrade MariaDB **dalam satu seri** (patch, mis. 11.4.11 → 11.4.13) tanpa mematikan cluster
Galera. Perpindahan seri (11.4 → 11.8) dan upgrade major di luar cakupan (kandidat ADR).

Spike `docs/spikes/2026-10-16-mariadb-upgrade.md` (Ubuntu 24.04 dan Rocky 9, topologi `loadbalancer`):

- Upgrade paket me-restart MariaDB yang berjalan di kedua OS (deb: postinst; rpm: `posttrans` `try-restart`).
- Jika MariaDB dihentikan dulu, paket deb menyalakannya lagi; paket rpm tidak. Dengan `policy-rc.d` (exit 101)
  service deb tetap mati. Image container Ubuntu bisa sudah membawa `policy-rc.d` sendiri.
- Node kembali lewat IST di kedua OS.
- Paket deb menjalankan `mariadb-upgrade --version-check` di background setiap service start
  (`ExecStartPost=!/etc/mysql/debian-start`). Akibatnya `mariadb_upgrade_info` ada di setiap node Ubuntu, sedangkan
  di Rocky hanya di node bootstrap (SST tidak membawanya). Tanpa `--force`, isi file info berbeda antar node.
  Perubahan `mariadb-upgrade` tidak tereplikasi Galera; perbedaan `CHECKSUM TABLE mysql.proc` antar node hanya
  karena kolom `modified`.
- Upgrade bisa menarik paket baru lewat Recommends (11.4.13 menambah `stunnel`). Upgrade dengan daftar paket
  tetap meninggalkan paket MariaDB lain (`-compat`) di versi lama.
- Upgrade writer dengan drain: Ubuntu 585 write 0 gagal, Rocky 569 write 1 gagal (koneksi baru yang sedang
  handshake ke backup diputus saat writer kembali). Satu `dnf upgrade` gagal sekali tanpa penyebab yang tercatat.

## Keputusan

### Perintah dan versi target

- `tera upgrade -i inventory/<cluster> -e mariadb_upgrade_to=<11.4.x|latest>` (action `upgrade`).
- Prechecks menentukan versi target **sekali, di awal run**, untuk `MariaDB-server`/`mariadb-server` dan
  `galera-4` (mode galera): versi eksplisit dipakai apa adanya; `latest` diterjemahkan ke versi tertinggi di repo
  yang dikonfigurasi. Versi itu ditampilkan dan dipakai untuk semua node. Prechecks gagal jika versi target tidak
  tersedia di repo salah satu node, atau jika node tidak sepakat tentang versi `latest`.
- Prechecks menolak: seri berbeda dari `mariadb_version` (major.minor), downgrade, cluster tidak Primary atau ada
  node tidak Synced, ruang disk kurang, `--limit` di mode galera (sama dengan deploy).
- **Backup:** jika `mariadb_backup_enabled`, prechecks mewajibkan backup sukses yang lolos verifikasi, dengan
  umur ≤ `mariadb_upgrade_max_backup_age` (detik, default `86400`), dibaca dari status backup
  (`/etc/tera/mariadb-backup.status` di node backup). Jika backup tidak aktif, upgrade ditolak kecuali
  `mariadb_upgrade_allow_without_backup: true`. Tidak ada backup otomatis; pesan error menyarankan
  `tera backup`.

### Paket

- Daftar paket yang di-upgrade diambil dari **paket yang terpasang di node** (package facts): semua paket
  MariaDB upstream (`mariadb-*`/`libmariadb*` di deb, `MariaDB-*` di rpm) dan `galera-4`, semuanya ke versi
  target. Paket yang tidak terpasang tidak ditambahkan.
- Paket yang dianjurkan **dimatikan** saat install dan upgrade: `install_recommends: false` (apt),
  `install_weak_deps: false` (dnf). Dependensi yang dibutuhkan Tera ditulis eksplisit di vars per OS. Paket yang
  sudah terpasang tidak dihapus. Ini juga mengubah jalur install pertama.
- Operasi paket diberi retry terbatas (`mariadb_upgrade_package_retries`, default 3, dengan jeda). Output setiap
  operasi paket selalu disimpan di node (`/var/log/tera/mariadb-upgrade-<versi>-<waktu>.log`) dan ditampilkan
  jika gagal. File log bukan output config, jadi aturan determinisme tidak berlaku.

### Mencegah restart oleh paket (Ubuntu)

- Sebelum operasi paket, MariaDB sudah dihentikan Tera. Di Ubuntu, Tera memasang `/usr/sbin/policy-rc.d` yang
  hanya menolak `mariadb` (exit 101 untuk nama service itu, exit 0 untuk yang lain), dengan baris penanda Tera,
  dan menghapusnya di blok `always`.
- Jika `/usr/sbin/policy-rc.d` sudah ada dan **bukan** milik Tera (tanpa penanda), Tera tidak mengubah atau
  menghapusnya dan tidak memasang miliknya; output menampilkan peringatan.
- Setiap awal `deploy` dan `upgrade`, `policy-rc.d` milik Tera yang tertinggal (run terputus) dihapus, dengan
  peringatan.
- Setelah operasi paket, di kedua OS, Tera memeriksa apakah MariaDB masih mati. Jika ternyata menyala (mis.
  `policy-rc.d` asing yang mengizinkan start, atau perilaku paket yang berubah), Tera menghentikannya lagi dengan
  peringatan, lalu melanjutkan alur normal (start oleh Tera, tunggu Synced).
- Rocky tidak memakai mekanisme ini: `try-restart` tidak menyalakan service yang mati (spike).

### Urutan per node

Play `serial: 1`, `max_fail_percentage: 0` (ADR 0007), di bawah lock backup (ADR 0012) seperti rolling restart.
Mode galera: node non-writer dulu (urutan inventory), writer (`groups['mariadb'][0]`) paling akhir. Di setiap node:

1. **Drain:** hentikan `tera-clustercheck.socket` (HAProxy menandai node DOWN); tunggu sampai stats HAProxy
   menandai node DOWN di semua node load balancer. Tanpa load balancer, langkah ini dilewati. Langkah 2–7 berada
   dalam `block` yang blok `always`-nya menyalakan socket kembali.
2. Stop MariaDB.
3. Upgrade paket (bagian di atas), lalu pastikan MariaDB masih mati.
4. Start MariaDB, tunggu Synced (`wait_synced.yml`; IST diharapkan, SST tetap sah).
5. Ubuntu: tunggu `mariadb-upgrade` background dari `debian-start` selesai (tidak ada proses `mariadb-upgrade`,
   dengan timeout `mariadb_upgrade_debian_start_timeout`), agar dua `mariadb-upgrade` tidak berjalan bersamaan.
   Timeout = node gagal (MariaDB tetap berjalan, socket dinyalakan lagi oleh blok `always`).
6. `mariadb-upgrade --force` di node ini. Perubahannya lokal (tidak tereplikasi), jadi wajib di setiap node.
   Sukses jika rc=0 dan `mariadb_upgrade_info` berisi versi target.
   Asal keputusan: pemilik proyek memutuskan `mariadb-upgrade` dijalankan di setiap node **tanpa `--force`**
   (rencana Fase 4b). Spike menunjukkan file info lalu berbeda antar node; `--force` adalah usulan Claude dari
   spike, disetujui pemilik pada review ADR ini (2026-10-16), dengan syarat langkah 5.
7. **Undrain:** nyalakan `tera-clustercheck.socket`; tunggu node UP di HAProxy sebelum node berikutnya.

Standalone: langkah 2–6 tanpa drain; ada downtime selama upgrade. README menyarankan backup full lebih dulu.

Socket clustercheck dinyalakan kembali di blok `always`. Jika controller terputus sebelum blok itu, node tetap
ter-drain; karena itu setiap `deploy`, `reconfigure`, dan `upgrade` memastikan `tera-clustercheck.socket` aktif di
setiap node galera dan menampilkan peringatan jika menemukannya mati. Node masuk pool lagi setelah Synced.

### Gangguan untuk klien

Upgrade writer (`single_writer`) menyebabkan dua gangguan, sama dengan rolling restart: failover saat drain, dan
sesi di backup diputus saat writer kembali (`on-marked-up shutdown-backup-sessions`). Koneksi baru yang sedang
handshake saat itu juga bisa gagal (spike Rocky: 1 dari 569). **Klien wajib me-retry koneksi dan transaksi**;
README dan ARCHITECTURE mencatatnya. Pemindahan writer sementara selama upgrade adalah kandidat ADR.

## Alternatif yang ditolak

- **Upgrade tanpa menghentikan MariaDB dulu:** restart dikendalikan paket, bukan Tera; tidak ada drain yang rapi
  dan tidak ada titik untuk memeriksa hasil paket sebelum start.
- **`mariadb-upgrade` tanpa `--force`** (keputusan awal pemilik, diganti pada review ini atas usulan Claude):
  file info berbeda antar node (Rocky: bootstrap versi lama, joiner versi baru), sehingga status upgrade tidak
  bisa diperiksa seragam.
- **Melewati `mariadb-upgrade` untuk patch** (usulan awal Claude di spike): ditolak pemilik proyek; dijalankan
  di setiap node.
- **`policy-rc.d` yang menolak semua service:** run yang terputus akan mencegah service lain start lewat paket.
- **Menimpa atau memindahkan `policy-rc.d` asing:** run yang terputus bisa menghilangkannya.
- **Daftar paket tetap:** paket MariaDB lain tertinggal di versi lama (spike, `-compat`).
- **Backup otomatis sebelum upgrade:** durasi dan ruang disk tidak terduga; operator menjalankan `tera backup`.
- **Drain lewat file maintenance yang dibaca `tera-clustercheck`:** butuh perubahan ADR 0005 dan izin baca
  `tera_state_dir` untuk user `mysql`; menghentikan socket sudah diukur di spike dan memberi hasil yang sama di
  HAProxy.

## Konsekuensi

- Jalur install pertama berubah (tanpa paket yang dianjurkan): `standalone` dan `galera` dijalankan ulang dari VM
  baru di Ubuntu dan Rocky.
- Selama upgrade, cluster berisi versi campuran dalam satu seri; ini didukung MariaDB untuk patch.
- `deploy` tidak pernah meng-upgrade (paket `state: present`). Node baru (scale out) memasang versi terbaru di
  repo; prechecks `deploy` memperingatkan jika versi node berbeda.
- Test (skenario `upgrade`, topologi `loadbalancer`, Ubuntu 24.04 dan Rocky 9; podman di CI): pasang 11.4 lama
  dari archive lalu upgrade; probe VIP; semua node di versi target untuk server dan galera-4; data utuh; definisi
  `mysql.proc` (tanpa `created`/`modified`) dan versi di `mariadb_upgrade_info` sama di semua node; `deploy`
  sesudahnya `changed=0`; prechecks menolak seri lain, downgrade, node tidak Synced, backup kedaluwarsa atau tidak
  aktif tanpa override. Ubuntu: run upgrade yang diputus setelah `policy-rc.d` terpasang tidak mencegah service
  lain start, dan `deploy` berikutnya menghapus `policy-rc.d` Tera dengan peringatan; `policy-rc.d` asing tidak
  disentuh, dan MariaDB yang menyala setelah operasi paket dihentikan lagi dengan peringatan (podman Ubuntu, yang
  membawa `policy-rc.d` asing); `mariadb-upgrade --force` tidak berjalan bersamaan dengan `mariadb-upgrade` dari
  `debian-start` (dibuktikan dengan journal/urutan proses); upgrade yang diputus setelah drain tidak meninggalkan
  node keluar dari pool HAProxy setelah `deploy` berikutnya (backend UP, peringatan socket mati tampil).

## Revisi

- 2026-10-17: tambahan saat implementasi; keputusan di atas tidak berubah. Diusulkan Claude setelah test VM
  `upgrade` pertama, disetujui pemilik proyek 2026-10-17. Prechecks membaca versi dari `mariadb_repo_*_url` lewat
  probe sementara tanpa mengubah repo node (apt: `sources.list`, lists, dan cache di direktori sementara; dnf:
  `--repofrompath` dengan `cachedir` sementara). Repo node ditulis di play terpisah setelah prechecks lulus di
  semua node, lalu dicek bahwa repo itu menyediakan versi target, sebelum node pertama di-upgrade. Run yang ditolak
  dan `--check` tidak mengubah repo node. Sebelumnya prechecks menulis repo lebih dulu, sehingga run yang ditolak
  meninggalkan repo baru di node (mis. seri lain, yang bisa terpasang lewat `apt upgrade` manual), dan `--check`
  menghitung rencana dari repo lama.
