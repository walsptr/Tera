# Spike: mariabackup 11.4 di Galera (2026-10-16)

Tujuan: memastikan, dengan data, perilaku `mariabackup` di node Galera sebelum menulis ADR 0012/0013:
apakah node desync otomatis, dampak flow control ke cluster, dan perilaku clustercheck/HAProxy selama backup.

## Lingkungan

- Topologi Molecule `loadbalancer` (3 node colocated, galera + HAProxy `single_writer` + Keepalived),
  Ubuntu 24.04, MariaDB `11.4.13`, `mariabackup 11.4.13`, VM 2 vCPU / 1,5 GB RAM.
- Data: tabel InnoDB `spike.bulk` 1,5 juta baris (805 MB di datadir).
- Beban: INSERT lewat VIP setiap ~50 ms dari db02 (masuk ke writer db01), dengan latensi per commit.
- Monitor setiap 0,2 detik: `wsrep_local_state_comment`, `wsrep_desync`, `wsrep_local_recv_queue`,
  `wsrep_flow_control_sent/recv/paused_ns`, kode HTTP `tera-clustercheck`, dan status server di stats HAProxy.
- Hanya Ubuntu 24.04. Perilakunya ada di server MariaDB (versi upstream yang sama di Rocky 9); skenario
  Molecule `backup-galera` nanti mengujinya di kedua OS.

## Eksperimen

| # | Node | Backup | Durasi |
|---|---|---|---|
| E1 | db03 (backup HAProxy) | full, tanpa throttle | 2,3 s (872 MB) |
| E2 | db03 | incremental | 2,4 s (24 MB) |
| E4 | db01 (writer) | full, tanpa throttle | 4,7 s |
| E5 | db03 | full, `--throttle=10` (meniru database besar) | 70 s |
| E6 | db01 (writer) | full, `--throttle=10` | 68 s |

## Temuan

### 1. Node desync sendiri, tetapi hanya selama `BACKUP STAGE BLOCK_DDL`

Log MariaDB db03 (E5):

```
21:58:54 WSREP: Member 2.0 (db03) desyncs itself from group
21:58:54 WSREP: Shifting SYNCED -> DONOR/DESYNCED (TO: 1924)
21:58:54 WSREP: Provider paused at 7c141750-...:1924 (1955)
21:58:54 WSREP: Server desynched from group during BACKUP STAGE BLOCK_DDL.
21:59:20 WSREP: Resuming and resyncing the provider
21:59:20 WSREP: Shifting DONOR/DESYNCED -> JOINED -> SYNCED
```

- `wsrep_desync` (variabel) tetap `OFF`. Desync dilakukan server saat `BACKUP STAGE BLOCK_DDL`, bukan lewat
  variabel, dan provider di-**pause** (applier berhenti) sampai `BLOCK_COMMIT`/`END`.
- Tahap mariabackup di E5: `START` 21:58:10–21:58:29, `FLUSH` –21:58:54 (node tetap Synced), `BLOCK_DDL`
  21:58:54–21:59:18 (Donor/Desynced), `BLOCK_COMMIT` –21:59:20, selesai 21:59:20.
- File InnoDB besar (`spike/bulk.ibd`) disalin di tahap `START`, saat node **masih Synced**. Tahap
  `BLOCK_DDL` menyalin file non-InnoDB (`.frm`, Aria/MyISAM, ~150 file di sini) dan ekor redo log.
- Akibatnya lama desync sebanding dengan **jumlah dan ukuran data non-InnoDB**, bukan ukuran InnoDB. Tanpa
  throttle (E1) desync < 2 detik; dengan throttle (E5) 25 detik karena setiap file kecil ikut diperlambat.

### 2. Tidak ada dampak flow control ke cluster

| | E5 (db03) | Baseline |
|---|---|---|
| `wsrep_local_recv_queue` maks di db03 | 267 (applier di-pause, lalu menyusul seketika saat resync) | 0 |
| `wsrep_flow_control_sent` db03 (delta) | 1 | 0 |
| `wsrep_flow_control_paused_ns` db01 (delta) | 1,3 ms | 0 |
| Write lewat VIP | 926 write, 0 error, p50 39 ms, p99 73 ms, maks 78 ms | p50 39 ms, p99 90 ms |

Node yang desync tidak mengirim flow control, sehingga cluster tidak melambat walau applier db03 berhenti.

### 3. Clustercheck dan HAProxy mengikuti status desync

Timeline E5 (detik sejak backup dimulai):

| t | db03 | clustercheck db03 | HAProxy |
|---|---|---|---|
| +45,1 | Donor/Desynced | 503 | db03 UP 2/3 (+45,8) → 1/3 (+46,2) → **DOWN** (+46,8) |
| +70,8 | Synced | 200 | db03 DOWN 1/2 (+71,3) → **UP** (+72,0) |

- Node backup keluar dari pool sekitar 1,7 detik setelah desync dan kembali sekitar 1,2 detik setelah resync
  (`fall 3`/`rise 2`). Selama sebagian besar backup (salinan InnoDB) node tetap di pool.
- Dengan `mariadb_clustercheck_available_when_donor: false` (default) node yang applier-nya di-pause tidak
  melayani klien. Jika `true`, node itu bisa melayani data basi.
- Dengan 3 node, selama jendela desync hanya satu kandidat failover yang tersisa.

### 4. Backup di writer menyebabkan failover

E6 (db01 = writer `single_writer`): HAProxy menandai db01 **DOWN** (+140,3 s), koneksi pindah ke db02,
1 write gagal (1110 ms), dan saat db01 kembali (+165,2 s) sesi di backup diputus
(`on-marked-up shutdown-backup-sessions`). Bahkan tanpa throttle (E4) db01 gagal 1–2 dari 3 health check dan
latensi write maksimum naik ke 1418 ms. Ini mendukung keputusan menolak backup di writer.

### 5. Format dan alur di 11.4

- File metadata bernama `mariadb_backup_*` (bukan `xtrabackup_*`): `mariadb_backup_checkpoints`
  (`backup_type`, `from_lsn`, `to_lsn`), `mariadb_backup_info` (`server_version`, waktu, perintah),
  `mariadb_backup_galera_info` (`uuid:seqno`, dengan `--galera-info`).
- Incremental harus diterapkan ke full yang **sudah di-prepare**. `--prepare --incremental-dir` pada full yang
  belum di-prepare gagal: `error: applying incremental backup needs a prepared target`. Urutan yang terbukti:
  `--prepare` full → `--prepare --incremental-dir=inc1` → `--prepare --incremental-dir=inc2`.
- Verifikasi tanpa menyentuh service: `mariadbd --no-defaults --skip-networking --socket=<tmp>
  --datadir=<prepared>` (tanpa Galera) membaca semua baris inc1/inc2, 1,5 juta baris `bulk`, dan
  `CHECK TABLE` = OK. Buffer pool 64 MB cukup.
- `--stream=mbstream | zstd` dan `zstd -dc | mbstream -x` bekerja (data uji sangat mudah dikompresi, jadi rasio
  kompresi di sini tidak representatif).
- Prepare full 805 MB: 0,4 s, 54 MB RSS.

## Implikasi untuk ADR

- Default node backup = node terakhir (backup HAProxy); writer ditolak kecuali di-override (temuan 4).
- Node backup keluar dari pool hanya selama jendela desync, bukan selama seluruh backup (temuan 1 dan 3).
  Database dengan banyak tabel non-InnoDB memperpanjang jendela itu.
- Tidak perlu `SET GLOBAL wsrep_desync` manual: server sudah desync di tahap yang tepat (temuan 1).
- `mariadb_clustercheck_available_when_donor` tetap `false` (temuan 3).
- Restore: prepare full lalu incremental berurutan, dan verifikasi dengan `mariadbd` sementara (temuan 5).
