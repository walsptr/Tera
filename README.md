# Tera

Tera adalah tool berbasis Ansible untuk memasang dan mengoperasikan **MariaDB**: satu server (standalone)
atau cluster **Galera** 3 node ke atas dengan **VIP** (HAProxy + Keepalived) di depannya.

- **Satu cluster = satu folder** `inventory/<nama>/`: host, variabel, password, custom config.
- **Custom config tanpa fork role**: taruh file `.cnf` di `inventory/<nama>/config/`, lalu
  `tera reconfigure` me-merge, mengirim, dan me-restart **hanya node yang config-nya berubah**, satu per satu.
- **Keamanan data di atas otomatisasi**: Tera tidak pernah mem-bootstrap ulang cluster Galera yang mati
  total secara otomatis, tidak menimpa data lewat SST tanpa izin, dan tidak membuat database kosong baru
  di datadir yang hilang. Dalam kasus ragu, Tera berhenti dengan pesan yang menjelaskan langkah berikutnya.

OS node yang didukung: **Ubuntu 22.04/24.04, Rocky Linux 9, AlmaLinux 9**. MariaDB dari repo upstream
(default `11.4`).

## Prasyarat

**Mesin kontrol** (tempat Anda menjalankan `./tera`):

- Python 3 dan **ansible-core >= 2.16**
- Collections Ansible dari `requirements.yml`:

  ```bash
  python3 -m venv .venv
  .venv/bin/pip install 'ansible-core>=2.16'
  .venv/bin/ansible-galaxy collection install -r requirements.yml -p ./collections
  ```

  `./tera` memakai `ansible-playbook` dari `PATH`, atau dari `.venv/` di folder repo.

**Node**:

- SSH dari mesin kontrol dan `sudo` (Tera memakai `become`).
- systemd. Akses ke repo MariaDB upstream (atau set `mariadb_repo_manage: false` jika memakai mirror sendiri).
- Galera: node saling terjangkau di 4567/tcp+udp, 4568/tcp, 4444/tcp. Jika **firewalld** berjalan, Tera
  membukanya sendiri (lihat [Firewall](#firewall)).
- VIP: semua node load balancer di satu subnet L2, dan VIP adalah alamat bebas di subnet itu.

## Quickstart: standalone

```bash
./tera new-cluster prod-a                 # membuat inventory/prod-a dari inventory/sample
$EDITOR inventory/prod-a/hosts.yml        # satu host di group mariadb
./tera genpwd -i inventory/prod-a         # mengisi password kosong di group_vars/all/passwords.yml
ansible-vault encrypt inventory/prod-a/group_vars/all/passwords.yml   # disarankan
./tera prechecks -i inventory/prod-a      # validasi tanpa mengubah apa pun
./tera deploy    -i inventory/prod-a
```

Setelah `passwords.yml` dienkripsi, tambahkan `--ask-vault-pass` (atau set `ANSIBLE_VAULT_PASSWORD_FILE`) ke
setiap perintah; argumen tambahan diteruskan apa adanya ke `ansible-playbook`. `genpwd` hanya bisa dijalankan
sebelum file dienkripsi.

Akses remote memakai user `tera_admin` (password `mariadb_admin_password`) dari host di
`mariadb_admin_hosts`. Root MariaDB hanya bisa login lewat unix socket di node itu sendiri.

## Quickstart: Galera + VIP

`inventory/prod-b/hosts.yml`:

```yaml
all:
  children:
    mariadb:
      hosts:
        db01: { ansible_host: 192.0.2.11, ip: 10.0.0.11 }
        db02: { ansible_host: 192.0.2.12, ip: 10.0.0.12 }
        db03: { ansible_host: 192.0.2.13, ip: 10.0.0.13 }
    loadbalancer:            # boleh host yang sama (colocated)
      hosts:
        db01:
        db02:
        db03:
```

`inventory/prod-b/group_vars/all/tera.yml`:

```yaml
mariadb_cluster_mode: galera
tera_vip_address: 10.0.0.100          # alamat bebas di subnet node load balancer
keepalived_virtual_router_id: 51      # unik per jaringan L2
mariadb_admin_hosts:
  - localhost
  - "10.0.0.%"
mariadb_client_sources:               # siapa yang boleh ke 3306/VIP (default semua)
  - 10.0.0.0/24
```

```bash
./tera genpwd    -i inventory/prod-b
./tera prechecks -i inventory/prod-b
./tera deploy    -i inventory/prod-b      # tanpa --limit: bootstrap/join butuh status semua node
```

Aplikasi terhubung ke `10.0.0.100:3306`. Halaman stats HAProxy ada di `http://<node>:8404/`
(user `tera`, password `haproxy_stats_password`, dari sumber di `haproxy_stats_sources`).

`ip` adalah alamat yang dipakai MariaDB untuk listen dan antar node. Tanpa `ip`, Tera memakai IPv4 dari
`tera_network_interface`, lalu alamat default route.

## Custom config dan reconfigure

```
inventory/<cluster>/config/
├── mariadb/*.cnf              # semua node
├── mariadb/<host>/*.cnf       # node tertentu (menang atas yang global)
├── haproxy/haproxy.cfg        # pengganti penuh config HAProxy (opsional)
├── haproxy/conf.d/*.cfg       # ditambahkan ke config HAProxy (opsional)
└── keepalived/keepalived.conf # pengganti penuh config Keepalived (opsional)
```

Contoh `config/mariadb/tuning.cnf`:

```ini
[mysqld]
max_connections = 1000
innodb_buffer_pool_size = {{ (ansible_facts['memtotal_mb'] * 0.6) | int }}M
```

```bash
./tera reconfigure -i inventory/prod-b --check --diff   # lihat perubahan dulu
./tera reconfigure -i inventory/prod-b
```

- Semua file dirender sebagai Jinja2 dan digabung ke satu file `99-tera.cnf` per node (aturan lengkap:
  `docs/CUSTOM-CONFIG.md`). Value `__remove__` menghapus key bawaan.
- Hanya node yang `99-tera.cnf`-nya berubah yang di-restart, **satu per satu**, dan node berikutnya baru
  di-restart setelah node sebelumnya Synced kembali. Run tanpa perubahan tidak me-restart apa pun.
- Jika run terputus setelah config ditulis tetapi sebelum restart, run berikutnya tetap me-restart.
- Jangan menaruh password di custom config; `wsrep_sst_auth` di custom config ditolak.

## Recover: semua node Galera mati

Jika semua node mati (listrik padam, crash), dua hal bisa terjadi:

- MariaDB menyala lagi sendiri dan cluster pulih otomatis: `./tera deploy` melihat cluster hidup dan
  hanya menyusulkan node yang tertinggal.
- Cluster tidak pulih: `./tera deploy` **gagal dengan sengaja** dan meminta Anda menjalankan:

  ```bash
  ./tera recover -i inventory/prod-b
  ```

  Tera membaca posisi transaksi terakhir di setiap node (`grastate.dat`, atau `mariadbd --wsrep-recover`),
  memilih node yang datanya paling baru, mem-bootstrap dari node itu, lalu menyalakan node lain satu per
  satu. Ringkasan per node ditampilkan sebelum bootstrap.

  Untuk memaksa node tertentu: `./tera recover -i inventory/prod-b -e mariadb_recover_from=db02`.
  **Hati-hati**: memaksa node dengan data lebih lama menghilangkan transaksi yang lebih baru.

## Destroy

```bash
./tera destroy -i inventory/prod-b --yes-i-really-really-mean-it              # hapus semua, termasuk data
./tera destroy -i inventory/prod-b --yes-i-really-really-mean-it --keep-data  # pertahankan datadir
```

Setiap node menampilkan dulu apa yang akan dihapus dan database yang ditemukan di datadir. Paket dan repo
tidak dihapus. Dengan `--keep-data` di cluster Galera, deploy berikutnya akan meminta `tera recover`
(data lama dipakai lagi dengan aman).

## Perilaku yang perlu diketahui operator

- **Aplikasi harus siap reconnect.** Saat writer mati, koneksi ke node itu putus dan koneksi baru lewat
  VIP pindah ke node berikutnya dalam beberapa detik (pengujian: sekitar 2 s; sekitar 5 s jika node yang
  mati juga memegang VIP).
- **Sesi diputus saat writer kembali.** Mode default `single_writer` mengirim semua koneksi ke node pertama
  group `mariadb`. Saat node itu kembali sehat, **semua sesi yang sedang berjalan di node cadangan diputus**
  agar semua klien kembali ke satu writer (menghindari konflik tulis di Galera). Transaksi yang sedang
  berjalan di sesi itu gagal dan harus diulang aplikasi.
- **VIP tidak pindah balik.** Setelah failover, VIP tetap di node barunya walaupun node lama kembali, agar
  tidak ada gangguan kedua.
- **Firewall dikelola Tera** (jika firewalld berjalan). Lihat bagian berikut.
- **Datadir kosong menghentikan deploy.** Jika datadir yang pernah terisi tiba-tiba kosong (mis. disk data
  gagal di-mount), deploy gagal dan meminta Anda memeriksa mount, bukan membuat database baru di disk root.
- **Tidak ada bootstrap otomatis untuk cluster lama** dan **tidak ada SST yang menimpa data user tanpa izin**
  (`mariadb_galera_allow_sst_overwrite: true` untuk sengaja membuang data di node itu).
- `--limit` ditolak untuk `deploy` mode Galera; untuk sebagian host gunakan `reconfigure --limit`.

## Firewall

Jika **firewalld berjalan**, Tera mengelola zona default (Tera tidak pernah menyalakan firewalld dan tidak
mengelola ufw):

| Port | Dibuka untuk |
|---|---|
| 3306/tcp (dan VIP) | `mariadb_client_sources` (default semua) |
| 4567/tcp+udp, 4568/tcp, 4444/tcp | node cluster saja |
| 9200/tcp (health check) | node load balancer saja |
| 8404/tcp (stats HAProxy) | `haproxy_stats_sources` (default hanya node load balancer) |
| VRRP (protokol 112) | node load balancer lain saja |

Tera **memiliki** rule untuk port-port itu: rule buatan tangan untuk port yang sama akan dihapus, dan
daftar rule yang akan dihapus ditampilkan saat run (juga di `--check --diff`). Atur akses lewat variabel di
atas, atau set `tera_manage_firewall: false` agar Tera sama sekali tidak menyentuh firewalld.

## Dokumentasi lanjutan

- `docs/ARCHITECTURE.md`: struktur, variabel, topologi HA, artefak di node, destroy
- `docs/CUSTOM-CONFIG.md`: aturan merge custom config
- `docs/GALERA-LIFECYCLE.md`: bootstrap, join, rolling restart, recover
- `docs/TESTING.md`: cara Tera diuji (Molecule) dan checklist lab
- `docs/decisions/`: keputusan desain (ADR)
