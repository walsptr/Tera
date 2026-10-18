# Galera Lifecycle

> **Wajib dibaca** sebelum mengubah task Galera (`status.yml`, `galera.yml`, `restart.yml`,
> `recover.yml`, `wait_synced.yml`). Jika implementasi berbeda dari dokumen ini, **dokumen ini yang benar**.
> Perubahan perilaku hanya lewat ADR baru di `docs/decisions/`.

## Istilah

| Istilah | Arti |
|---|---|
| Primary | `wsrep_cluster_status = Primary` — node berada di komponen yang punya quorum |
| Synced | `wsrep_local_state_comment = Synced` (`wsrep_local_state = 4`) |
| Marker | file `/etc/tera/mariadb-galera.bootstrapped`; tanda cluster pernah di-bootstrap oleh Tera |
| Restart pending marker | file `/etc/tera/mariadb-restart-pending` (`mariadb_restart_marker`); ada = config baru belum aktif (ADR 0009) |
| Removed marker | file `/etc/tera/mariadb-removed` (`mariadb_removed_marker`); ada = host dikeluarkan lewat `tera scale-in` (ADR 0017) dan ditolak semua action |
| Restore marker | file `/etc/tera/mariadb-restore.active` (`mariadb_restore_marker`); ada = `tera restore` berjalan atau terputus, backup menolak berjalan (ADR 0013) |
| Bootstrap host | `mariadb_bootstrap_host` (default `groups['mariadb'][0]`) |
| grastate | `grastate.dat` di datadir: `uuid`, `seqno`, `safe_to_bootstrap` |

## Status (`status.yml`)

Read-only, semua query memakai `check_mode: false`. Fact per host (semua boolean, di-set dengan `| bool`):

| Fact | Sumber |
|---|---|
| `_mariadb_running` | `service_facts` |
| `_mariadb_wsrep_primary` | running AND `wsrep_cluster_status = Primary` |
| `_mariadb_bootstrapped_marker` | `stat` marker |

Agregat dihitung **di setiap host** dari `ansible_play_hosts` (bukan `run_once` + `set_fact`):

- `_galera_cluster_alive` — ada minimal satu host dengan `_mariadb_wsrep_primary`.
- `_galera_ever_bootstrapped` — ada minimal satu host dengan `_mariadb_bootstrapped_marker`.

## Prasyarat deploy

- Jumlah node >= `mariadb_galera_min_nodes` (jumlah genap → warning, karena rawan split brain).
- Tanpa `--limit` (`ansible_play_hosts_all` == `groups['mariadb']`).
- Password SST dan clustercheck terisi.
- Custom config tidak berisi `wsrep_sst_auth` (kredensial SST hanya di `98-tera-sst.cnf`).
- **Tidak ada SST yang menimpa data user.** Node yang akan menerima SST tanpa marker tidak boleh punya
  database user di datadir (`mariadb_datadir`):
  - saat fresh bootstrap: semua node **kecuali** bootstrap host (datanya menjadi sumber cluster, sehingga
    migrasi standalone → galera bisa dilakukan dengan menjadikan node lama bootstrap host);
  - saat cluster alive: node yang tidak Primary dan tidak punya marker (node baru, scale out).

  Deteksi di level filesystem (direktori di datadir selain `mysql`, `performance_schema`, `sys`), sehingga
  tetap jalan walau MariaDB mati. Pesan error menyebut node dan database yang ditemukan, dan menyarankan
  `mariadb_bootstrap_host` jika data ada di node non-bootstrap saat fresh bootstrap. Override eksplisit:
  `mariadb_galera_allow_sst_overwrite: true` (default `false`).
- **Datadir tidak hilang diam-diam.** Jika marker datadir (`mariadb_datadir_marker`) ada tetapi datadir kosong
  (tidak ada `mysql/`, mis. disk data gagal di-mount atau SST sebelumnya gagal), deploy gagal sebelum MariaDB
  disentuh. Tanpa aturan ini, node Galera dengan datadir kosong akan diisi ulang lewat SST ke disk root.
  Jika datadir memang sengaja dikosongkan, operator menghapus marker setelah memastikan mount benar.
  Node yang menerima SST secara normal tidak terpengaruh: marker ditulis saat deploy pertama (datadir sudah
  diinisialisasi paket) dan `mysql/` tetap ada setelah SST.

## Tabel keputusan

Dievaluasi setelah config ditulis, sebelum start/restart.

| Cluster alive | Marker ada | Aksi |
|---|---|---|
| tidak | tidak | Fresh bootstrap |
| tidak | ya | **FAIL** → arahkan ke `tera recover` |
| ya | apa saja | Join node yang tidak Primary |

## Fresh bootstrap

1. Stop mariadb di semua node.
2. `galera_new_cluster` di bootstrap host.
3. Tunggu Synced di bootstrap host.
4. Jalankan `users.yml` di bootstrap host, terutama user SST.
5. Node lain `start` dengan `throttle: 1`.
6. Semua node tunggu Synced.
7. Enable service; tulis marker dengan `force: false`.
8. Hapus restart pending marker (service baru menyala dengan config terbaru) dan set `mariadb_restart_required: false`.

## Join

1. Node yang tidak Primary di-restart dengan `throttle: 1`.
2. Tunggu Synced.
3. Tulis marker.
4. Hapus restart pending marker dan set `mariadb_restart_required: false`.
5. Setelah itu `users.yml` dijalankan di bootstrap host.

## Restart pending marker (ADR 0009)

- `config.yml` mendeteksi perubahan `99-tera.cnf` dengan `copy` `check_mode: true`. Jika akan berubah,
  restart pending marker ditulis **sebelum** file config ditulis. Pada run `--check` marker tidak ditulis.
- `config.yml` lalu membaca marker: `mariadb_restart_required` = flag lama OR file berubah OR marker ada.
  Dengan begitu run yang terputus setelah config ditulis tetap me-restart pada run `deploy`/`reconfigure`
  berikutnya. Action `prechecks` tidak pernah me-restart.
- Durabilitas: marker di-`sync` ke disk **sebelum** config ditulis, dan config (`99-tera.cnf`,
  `98-tera-sst.cnf`) di-`sync` sebelum MariaDB bisa di-start atau di-restart. Mati listrik tepat setelah Tera
  menulis tidak bisa menyisakan config baru tanpa marker. Marker bootstrap juga di-`sync` setelah ditulis.
- Pengecualian (ADR 0017): config yang hanya kehilangan alamat di `wsrep_cluster_address` setelah `tera scale-in`
  ditulis tanpa marker dan tanpa restart (lihat "Scale out dan scale in").
- Marker dihapus hanya oleh: rolling restart yang sukses (port terbuka, dan Synced untuk galera), start
  pertama standalone, bootstrap/join galera, serta `tera recover` setelah semua node Synced (service menyala
  dengan config terbaru).

## Rolling restart

- Hanya node dengan `mariadb_restart_required` (termasuk node yang punya restart pending marker).
- Urutan per node: restart → `wait_for` port di `tera_listen_address` → (mode galera) tunggu Synced →
  hapus restart pending marker → reset flag.
- Restart dijalankan di bawah lock backup (`flock -w mariadb_backup_lock_timeout`, ADR 0012): menunggu backup
  yang sedang berjalan di node itu, dan backup tidak bisa mulai selama restart. Jika batas waktu habis, run
  gagal dengan pesan; restart pending marker tetap ada, jadi run berikutnya melanjutkan.
- Jika satu node gagal, run berhenti; node lain tidak disentuh (`serial: 1`, `max_fail_percentage: 0`).
- Tidak memakai handler.

## Upgrade minor (ADR 0015)

`tera upgrade -i … -e mariadb_upgrade_to=<X.Y.Z|latest>` meng-upgrade patch dalam seri `mariadb_version`.

1. Prechecks di semua node: sisa run terputus dibersihkan (dengan peringatan), versi target MariaDB dan galera-4
   ditentukan **sekali** dari repo `mariadb_repo_*_url` (probe sementara, repo node belum diubah) dan harus sama
   di semua node; seri lain, downgrade, versi yang tidak ada di repo, cluster tidak Primary/Synced/lengkap, ruang
   `/var` kurang, `--limit`, restore yang aktif, dan backup terverifikasi yang lebih tua dari
   `mariadb_upgrade_max_backup_age` ditolak. Run yang ditolak dan `--check` tidak mengubah repo node.
   Setelah semua prechecks lulus, repo node ditulis dan dicek menyediakan versi target.
2. Satu node per kali (`serial: 1`, `max_fail_percentage: 0`), node non-writer dulu dalam urutan inventory,
   writer (`mariadb[0]`) paling akhir. Node yang sudah di versi target dilewati (tidak di-restart).
3. Per node, di bawah lock backup: drain (`tera-clustercheck.socket` dihentikan, tunggu DOWN di HAProxy) → stop →
   upgrade paket (Ubuntu: `policy-rc.d` Tera yang hanya menolak `mariadb`) → MariaDB yang dinyalakan paket
   dihentikan lagi dengan peringatan → start → tunggu Synced (biasanya IST) → Ubuntu: tunggu `mariadb-upgrade`
   dari `debian-start` selesai → `mariadb-upgrade --force` (lokal, tidak tereplikasi; wajib di setiap node) →
   undrain → tunggu UP di HAProxy.
4. Socket clustercheck dan lock dipulihkan di blok `always`. Jika controller terputus, `deploy`, `reconfigure`,
   atau `upgrade` berikutnya menyalakan socket, melepas lock, dan menghapus `policy-rc.d` Tera, dengan peringatan.

Upgrade paket gagal setelah retry: node itu dibiarkan **mati** (paket mungkin setengah terpasang) dan run
berhenti; node lain tidak disentuh. Perbaiki penyebabnya (log di `/var/log/tera/`), lalu ulangi `tera upgrade`.

## Reconfigure

1. Prechecks.
2. Tulis config di semua node **tanpa** restart.
3. Users + clustercheck.
4. Rolling restart.

`--limit` diperbolehkan untuk reconfigure.

## Scale out dan scale in

**Scale out:** tambah host ke inventory → `tera deploy` tanpa `--limit` → node baru join via SST,
node lama di-rolling restart karena `wsrep_cluster_address` berubah, HAProxy di-reload.

**Scale in** (ADR 0017), dua langkah:

1. `tera scale-in -i … -e tera_scale_in_host=<host> --yes-i-really-mean-it`. Prechecks di semua node: mode
   galera, tanpa `--limit`, cluster Primary dan semua Synced dengan size = jumlah node inventory, jumlah node
   sesudahnya ≥ `mariadb_galera_min_nodes`, bukan writer `single_writer` (kecuali `mariadb_scale_in_allow_writer`),
   bukan `mariadb_backup_host` saat backup aktif (kecuali `mariadb_scale_in_allow_backup_host`), ada node load
   balancer lain jika host itu juga load balancer, tidak ada restore, tidak ada host bermarker "removed". Di host
   itu, di bawah lock backup: drain (socket clustercheck dihentikan dan di-disable, tunggu DOWN di HAProxy) → timer
   backup dihentikan dan di-disable → jika host itu load balancer: Keepalived dihentikan (VIP pindah; tunggu VIP
   menjawab dan tepat satu node lain memegangnya), lalu HAProxy; keduanya di-disable → MariaDB dihentikan dan
   di-disable → marker `/etc/tera/mariadb-removed` ditulis dan di-`sync`. Node tersisa: tunggu Synced dan size
   berkurang satu. Datadir, paket, dan config tetap.
2. Operator menghapus host dari inventory (group `mariadb`, dan `loadbalancer` jika ada), lalu `tera reconfigure`:
   `wsrep_cluster_address`, backend HAProxy, peer Keepalived, rule firewall, dan kunci host backup diperbarui.

**Tanpa restart di langkah 2** (pengecualian sempit dari ADR 0009): jika satu-satunya perbedaan `99-tera.cnf` di
node adalah alamat yang hilang dari `wsrep_cluster_address` (urutan sisanya sama) dan node itu Primary dengan
`wsrep_cluster_size` = jumlah node `mariadb` di inventory, config ditulis tanpa restart pending marker dan tanpa
restart (pesan "ditulis tanpa restart (scale in, ADR 0017)", juga di `--check --diff`). Perbedaan lain apa pun, atau
node yang dihapus dari inventory masih ada di cluster (peringatan: keluarkan dulu lewat `tera scale-in`), mengikuti
ADR 0009: marker + rolling restart. Tera tidak pernah menjalankan `SET GLOBAL wsrep_cluster_address`.

**Marker "removed":** `deploy`, `reconfigure`, `prechecks`, `upgrade`, `recover`, `restore`, dan `scale-in` gagal di
prechecks jika host di inventory punya marker itu. Host itu tidak pernah dikecualikan otomatis: operator
menghapusnya dari inventory (langkah 2), lalu mengulang perintahnya. Hanya `deploy -e
mariadb_scale_in_allow_readd=true` yang menambahkannya kembali sebagai node baru: pengaman SST berlaku untuk node
itu walaupun marker galera-nya ada (datadir berisi database → butuh juga `mariadb_galera_allow_sst_overwrite`,
karena datanya salinan lama). Marker dihapus setelah node itu Synced.

## Recover

Prasyarat: mode galera dan **tidak ada** node Primary. Jika ada node Primary → FAIL, arahkan ke `tera deploy`.

Langkah:

1. Stop mariadb di semua node.
2. Baca `grastate.dat` di setiap node.
3. Jika `seqno == -1`: jalankan `mariadbd --user=mysql --wsrep-recover --log-error=<tmp>`,
   ambil seqno dari baris `WSREP: Recovered position: <uuid>:<seqno>`, lalu hapus log sementara.
4. Jika `uuid` berbeda antar node → FAIL, kecuali `mariadb_recover_from` diset.
5. Pilih node bootstrap dengan prioritas:
   1. `mariadb_recover_from`
   2. node pertama dengan `safe_to_bootstrap: 1`
   3. seqno tertinggi (seri: urutan inventory)
6. Tampilkan ringkasan (per node: uuid, seqno, safe_to_bootstrap, node terpilih).
7. Di node terpilih: set `safe_to_bootstrap: 1`, `galera_new_cluster`, tunggu Synced.
8. Node lain start dengan `throttle: 1`, tunggu Synced.
9. Pastikan marker ada di semua node.
10. Setelah semua node Synced: hapus restart pending marker di semua node (ADR 0009, revisi 2026-10-14).
    Recover menyalakan setiap node dengan config yang ada di disk, sehingga config terbaru sudah aktif.

Jika uuid berbeda antar node atau tidak ada node dengan posisi yang diketahui (seqno tertinggi `-1`), recover
gagal dan meminta `mariadb_recover_from` diset secara eksplisit. Memaksa node dengan data lebih lama
menghilangkan transaksi yang lebih baru.

### Pemulihan otomatis di produksi

Unit systemd MariaDB upstream memakai `Restart=on-abnormal` (MariaDB 11.4, unit upstream; dicek di Ubuntu 24.04 dan Rocky 9; kill -9 dan crash termasuk), dan Galera menyimpan komponen Primary terakhir di
`gvwstate.dat` (`pc.recovery`, aktif secara default). Setelah crash atau mati listrik, node bisa menyala
lagi sendiri (service di-enable) dan, jika semua anggota komponen Primary terakhir kembali, membentuk
Primary tanpa campur tangan. Dalam kondisi itu `tera deploy` melihat cluster **alive** dan hanya me-join
node yang tertinggal; `tera recover` menolak berjalan karena ada node Primary. Jika pemulihan otomatis tidak
terjadi (tidak ada Primary), `tera deploy` gagal dan mengarahkan ke `tera recover`.

## Restore (ADR 0013)

`tera restore` adalah perintah eksplisit, seperti recover; tabel keputusan deploy tidak berubah.

1. Tahap 1, MariaDB tetap berjalan: pilih rantai, cek cluster, seri MariaDB, dan mode (override
   `mariadb_restore_allow_mode_change` untuk standalone ↔ galera), cek ruang disk di node restore dan node
   yang akan menerima SST, tulis restore marker dan hentikan timer backup di semua node, tunggu lock backup,
   kirim rantai ke node restore (kunci sementara dari sumber, tulis-saja ke staging), prepare dan cek dengan
   `mariadbd` sementara. Gagal di sini = marker dihapus, timer dipulihkan, tidak ada yang diubah.
2. Tahap 2: stop MariaDB di **semua** node; di node restore datadir lama dipindah ke
   `<datadir>.pre-restore-<id>` dan hasil prepare dipindah masuk; `galera_new_cluster` di node restore (tanpa
   `grastate.dat` → UUID cluster baru); `users.yml` di node restore (user SST sebelum joiner mana pun); joiner
   start dengan `throttle: 1` dan menerima SST penuh; tunggu semua Synced.
3. Selesai: marker bootstrap ada di semua node; restart pending marker dihapus di semua node; `needs-full`
   ditulis (backup berikutnya full); restore marker dihapus; timer backup dipulihkan.

Jika tahap 2 gagal, restore marker sengaja dibiarkan dan pesan error berisi langkah kembali ke datadir lama
(lalu `tera recover`) atau, jika hanya joiner yang gagal, `tera deploy`.

## Timeout

| Variabel | Default |
|---|---|
| `mariadb_wait_retries` | `120` |
| `mariadb_wait_delay` | `5` |
| `mariadb_port_timeout` | `300` |

SST untuk data besar bisa butuh nilai yang lebih tinggi; naikkan di `group_vars` cluster.

## Yang tidak boleh terjadi

- Auto bootstrap cluster lama.
- Lebih dari satu node restart bersamaan.
- Node berikutnya restart sebelum node sebelumnya Synced.
- Joiner start sebelum user SST ada.
- Marker hilang karena SST.
- Restart pada run tanpa perubahan config (dan tanpa restart pending marker).
- Config baru yang sudah ditulis tidak pernah aktif karena run sebelumnya terputus.
- Restart MariaDB saat backup sedang berjalan di node itu.
- Paket MariaDB menyalakan MariaDB sendiri di tengah `tera upgrade`, atau dua `mariadb-upgrade` berjalan bersamaan.
- Lebih dari satu node di-upgrade bersamaan, atau writer di-upgrade sebelum node lain.
- Backup dibuat saat restore berjalan atau terputus.
- Node yang dikeluarkan lewat `tera scale-in` dinyalakan atau di-join lagi oleh action apa pun, kecuali `deploy`
  dengan `mariadb_scale_in_allow_readd` (dan pengaman SST).
- Restart karena `wsrep_cluster_address` hanya kehilangan node yang sudah keluar dari cluster.
