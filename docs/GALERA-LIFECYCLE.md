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
- Marker dihapus hanya oleh: rolling restart yang sukses (port terbuka, dan Synced untuk galera), start
  pertama standalone, serta bootstrap/join galera (service menyala dengan config terbaru).

## Rolling restart

- Hanya node dengan `mariadb_restart_required` (termasuk node yang punya restart pending marker).
- Urutan per node: restart → `wait_for` port di `tera_listen_address` → (mode galera) tunggu Synced →
  hapus restart pending marker → reset flag.
- Jika satu node gagal, run berhenti; node lain tidak disentuh (`serial: 1`, `max_fail_percentage: 0`).
- Tidak memakai handler.

## Reconfigure

1. Prechecks.
2. Tulis config di semua node **tanpa** restart.
3. Users + clustercheck.
4. Rolling restart.

`--limit` diperbolehkan untuk reconfigure.

## Scale out dan scale in

**Scale out:** tambah host ke inventory → `tera deploy` tanpa `--limit` → node baru join via SST,
node lama di-rolling restart karena `wsrep_cluster_address` berubah, HAProxy di-reload.

**Scale in** (manual untuk sekarang): stop node, hapus dari inventory, lalu `tera reconfigure`.

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
