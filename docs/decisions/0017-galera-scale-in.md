# 0017. Scale in Galera dalam dua langkah

- **Status:** Accepted (penyimpangan sempit dari ADR 0009, lihat "Tanpa restart")
- **Tanggal:** 2026-10-16

## Konteks

Saat ini scale in manual (`docs/GALERA-LIFECYCLE.md`): stop node, hapus dari inventory, `tera reconfigure`.
Tidak ada pemeriksaan kuorum, drain dari HAProxy, atau perlindungan jika operator lupa menghapus host dari
inventory (deploy berikutnya akan me-join node itu kembali).

Keputusan sebelumnya: dua langkah; `deploy`/`reconfigure` menolak host yang punya marker "removed" kecuali ada
override eksplisit untuk menambahkannya kembali; uji kasus "lupa menghapus dari inventory".

## Keputusan

### Langkah 1: `tera scale-in`

`tera scale-in -i inventory/<cluster> -e tera_scale_in_host=<host> --yes-i-really-mean-it` (action `scale_in`,
mode galera saja).

Prechecks (seluruh cluster, sebelum apa pun diubah):

- Cluster Primary, semua node Synced.
- Jumlah node sesudahnya ≥ `mariadb_galera_min_nodes`.
- Host bukan writer `single_writer` (`groups['mariadb'][0]`) kecuali `mariadb_scale_in_allow_writer: true`;
  pesan menyebut bahwa writer akan pindah ke node berikutnya di inventory setelah langkah 2.
- Host bukan `mariadb_backup_host` kecuali `mariadb_scale_in_allow_backup_host: true`; pesan menyarankan
  memindahkan `mariadb_backup_host` dulu.
- Tidak ada restore yang berjalan (`mariadb_restore_marker`).

Di host yang dikeluarkan, di bawah lock backup:

1. Drain (hentikan `tera-clustercheck.socket`, tunggu DOWN di HAProxy), seperti upgrade (ADR 0015).
2. Hentikan dan disable timer backup Tera jika ada.
3. Stop MariaDB dengan rapi (node keluar dari view; node lain tetap Primary), lalu disable service.
4. Tulis marker `{{ tera_state_dir }}/mariadb-removed` (berisi nama cluster dan waktu).
5. Di node tersisa: pastikan cluster size berkurang satu dan semua Synced.

Datadir, paket, dan config tidak dihapus (dibersihkan dengan `tera destroy --limit <host>` setelah langkah 2,
atau dibiarkan sebagai cadangan).

### Langkah 2: hapus dari inventory, lalu `tera reconfigure`

`reconfigure` memperbarui `wsrep_cluster_address` di node tersisa, backend HAProxy (reload), rule firewall milik
Tera (ADR 0011 menghapus rule node lama), dan kunci node itu di host backup. Backup remote milik node itu tidak
dihapus.

### Tanpa restart: penyimpangan dari ADR 0009

ADR 0009 menulis restart pending marker untuk **setiap** perubahan `99-tera.cnf`. ADR ini membuat satu
pengecualian, usulan Claude yang disetujui pemilik pada review 2026-10-16:

- Pengecualian berlaku hanya jika **satu-satunya** perbedaan antara `99-tera.cnf` di node dan yang akan ditulis
  adalah penghapusan satu atau lebih alamat dari `wsrep_cluster_address`, dan node yang dihapus sudah keluar dari
  view: `wsrep_cluster_size` di setiap node tersisa sama dengan jumlah node `mariadb` di inventory dan semuanya
  Primary. Jika tidak (mis. node yang dihapus dari inventory masih berjalan), berlaku ADR 0009 dan prechecks
  memperingatkan bahwa node itu belum dikeluarkan lewat `tera scale-in`. Dalam kasus itu config ditulis **tanpa** marker
  dan tanpa restart: alamat itu hanya dibaca saat node start/join, sedangkan anggota yang berjalan sudah tidak
  memiliki node itu di view.
- Perbedaan lain apa pun (key lain, alamat baru, urutan alamat, scale out, atau penghapusan bersamaan dengan
  perubahan lain) mengikuti ADR 0009 apa adanya: marker + rolling restart.
- Tera **tidak pernah** menjalankan `SET GLOBAL wsrep_cluster_address` (mengubahnya saat berjalan membuat node
  memutus dan menyambung ulang ke cluster).
- `--check --diff` menyebut perubahan itu sebagai "tanpa restart (scale in)".

### Pengaman marker "removed"

- `deploy` dan `reconfigure` (dan `upgrade`) gagal di prechecks jika host di inventory punya marker
  `mariadb-removed`, dengan pesan: host sudah dikeluarkan lewat `tera scale-in`; hapus dari inventory, atau
  tambahkan kembali dengan `mariadb_scale_in_allow_readd: true`.
- Dengan override, host di-join sebagai node baru: datadir lama dianggap usang, jadi pengaman SST yang ada tetap
  berlaku (`mariadb_galera_allow_sst_overwrite` jika datadir berisi database). Marker dihapus setelah node Synced.

## Alternatif yang ditolak

- **Satu perintah yang juga mengubah node lain sebelum inventory diubah:** Tera harus menulis config yang tidak
  sesuai inventory; inventory tetap sumber kebenaran.
- **Menghapus datadir di langkah 1:** tidak bisa dibatalkan; operator memilih lewat `destroy`.
- **Rolling restart karena `wsrep_cluster_address` berkurang:** restart semua node untuk perubahan yang tidak
  berpengaruh pada cluster yang berjalan.
- **Tanpa marker:** lupa menghapus host dari inventory membuat `deploy` me-join node lama lagi, tanpa peringatan.

## Konsekuensi

- Selama antara langkah 1 dan 2, HAProxy masih mendaftar node yang sudah keluar (DOWN) dan node tersisa masih
  menyebutnya di `wsrep_cluster_address`; keduanya tidak berbahaya.
- Writer `single_writer` yang dikeluarkan dengan override membuat writer pindah permanen setelah langkah 2.
- Test (skenario `scale`, 4 node 1280 MiB, Ubuntu 24.04 dan Rocky 9): scale out db04, lalu scale in db02 dengan
  klien menulis lewat VIP (tanpa error setelah failover); cluster size 3, backend HAProxy 3, rule firewall db02
  hilang (Rocky), node tersisa tidak di-restart (start timestamp sama, tanpa marker); penghapusan alamat yang
  dibarengi perubahan custom config lain memicu rolling restart; "lupa menghapus dari inventory": `reconfigure`/`deploy` ditolak
  dengan pesan, cluster tidak berubah; `mariadb_scale_in_allow_readd: true` menambahkan db02 kembali dan marker
  hilang; penolakan di bawah minimum, writer dan node backup tanpa override, cluster tidak sehat.
