# Arsitektur Tera

## Prinsip

1. **Satu cluster = satu folder.** Semua yang mendefinisikan sebuah cluster (host, variabel, password, custom config, fact cache) ada di `inventory/<cluster>/`.
2. **Config bisa di-override tanpa menyentuh role.** User menaruh file di `inventory/<cluster>/config/`; role tidak perlu di-fork.
3. **Keamanan data di atas otomatisasi penuh.** Jika Tera ragu (mis. cluster Galera mati semua), Tera berhenti dan memberi instruksi, bukan menebak.
4. **Idempotent dan deterministik.** Run ulang tanpa perubahan input = tidak ada file berubah = tidak ada restart.

## Struktur repo

```
tera                                  # CLI bash
ansible.cfg  requirements.yml  requirements-dev.txt  site.yml  .gitignore
.ansible-lint  .yamllint  pyproject.toml  .github/workflows/ci.yml
playbooks/{facts,common,mariadb,loadbalancer,mariadb-recover,destroy}.yml
plugins/filter/{merge_ini,tera_ip}.py   plugins/tests/test_{merge_ini,tera_ip}.py   # tests outside filter/: Ansible loads filter subdirs as plugins
roles/tera_defaults/defaults/main.yml
roles/common/tasks/{prechecks,deploy,reconfigure}.yml
roles/mariadb/{defaults,vars/{Debian,RedHat}.yml,templates,tasks}
  tasks entry point: prechecks deploy reconfigure restart recover destroy
  tasks internal:    vars install firewall config status standalone galera users clustercheck selinux wait_synced
  templates:         tera.cnf.j2 tera-clustercheck.j2 tera-clustercheck.socket.j2 tera-clustercheck@.service.j2
roles/loadbalancer/{defaults,handlers,templates/{haproxy.cfg.j2,keepalived.conf.j2},tasks/{prechecks,deploy,reconfigure,destroy,install,config}.yml}
inventory/sample/{hosts.yml,group_vars/all/{tera.yml,passwords.yml},config/{mariadb,haproxy/conf.d,keepalived}}
docs/
molecule/{shared,standalone,standalone-podman,galera,reconfigure,recover,recover-poweroff}/   # shared = playbook dan task bersama
```

## Inventory cluster

```
inventory/<cluster>/
├── hosts.yml
├── group_vars/all/tera.yml        # variabel cluster
├── group_vars/all/passwords.yml   # diisi `tera genpwd`, lalu disarankan `ansible-vault encrypt`
├── config/                        # custom config (lihat CUSTOM-CONFIG.md)
└── .facts_cache/                  # fact cache per cluster (gitignore)
```

Group:

- `mariadb` — mode standalone: tepat 1 host; mode galera: >= `mariadb_galera_min_nodes` (default 3).
- `loadbalancer` — opsional, boleh berisi host yang sama dengan node `mariadb` (colocated).

Host var opsional: `ip` (alamat yang dipakai Tera untuk listen dan komunikasi antar node).

Nilai yang wajib unik per cluster dan divalidasi di prechecks:

- `mariadb_galera_cluster_name` (default: nama folder cluster)
- `tera_vip_address`
- `keepalived_virtual_router_id`

## CLI

| Perintah | Playbook | `tera_action` |
|---|---|---|
| `new-cluster <nama>` | copy `inventory/sample` | – |
| `genpwd -i` | isi key kosong di `passwords.yml` | – |
| `prechecks -i` | `site.yml` | `prechecks` |
| `deploy -i` | `site.yml` | `deploy` |
| `reconfigure -i` | `site.yml` | `reconfigure` |
| `recover -i [-e mariadb_recover_from=<node>]` | `playbooks/mariadb-recover.yml` | – |
| `destroy -i … --yes-i-really-really-mean-it [--keep-data]` | `playbooks/destroy.yml` (`-e tera_destroy_confirm=true`, `--keep-data` → `-e tera_destroy_keep_data=true`) | – |

Perilaku CLI:

- `-i` menerima folder cluster atau path `hosts.yml`.
- Export `ANSIBLE_CONFIG=<repo>/ansible.cfg` dan `ANSIBLE_CACHE_PLUGIN_CONNECTION=<cluster>/.facts_cache` (hostname bisa sama antar cluster, sehingga cache tidak boleh dibagi).
- Argumen lain diteruskan apa adanya ke `ansible-playbook`.
- Aman untuk array kosong di bash `set -u`.
- `genpwd` hanya mengisi key yang kosong, tidak menimpa yang sudah ada, dan tidak bergantung pada PyYAML.
  Password berupa 32 karakter alfanumerik (`A-Za-z0-9`) agar aman dipakai di file `.cnf`, auth HAProxy stats,
  dan YAML. Key top-level dianggap kosong jika nilainya kosong, `""`, `''`, `~`, atau `null` dan baris
  berikutnya tidak menjorok (bukan parent mapping/list). File yang terenkripsi vault ditolak.
- `new-cluster <nama>` membuat `inventory/<nama>` (nama: huruf, angka, `.`, `_`, `-`) dan menolak jika sudah ada.
- `destroy` ditolak tanpa flag `--yes-i-really-really-mean-it`. `--keep-data` hanya diterima oleh `destroy`.

## Alur play `site.yml`

| # | Play | Hosts | Catatan |
|---|---|---|---|
| 1 | Validate | localhost | ansible-core >= 2.16, `tera_action` valid |
| 2 | Facts | `mariadb:loadbalancer` | `set_fact: tera_listen_address` |
| 3 | Common | `mariadb:loadbalancer` | paket dasar |
| 4 | MariaDB | `mariadb` | install, config, start/bootstrap/join, users |
| 5 | Rolling restart | `mariadb`, `serial: 1` | hanya node `mariadb_restart_required` |
| 6 | Load balancer | `loadbalancer` | hanya jika `tera_lb_enabled` |

Setiap play memuat role `tera_defaults` dan memakai `any_errors_fatal: true`.

## Matriks action

| Role | `prechecks` | `deploy` | `reconfigure` |
|---|---|---|---|
| common | OS | prechecks + paket | prechecks |
| mariadb | topologi, password, OS | prechecks, install, config, start/bootstrap/join, users, clustercheck | prechecks, config, users, clustercheck |
| loadbalancer | VIP, VRID, password | prechecks, install, config, start | prechecks, config + reload |

## Nilai lintas host

Role defaults tidak terlihat lewat `hostvars` host lain. Karena itu `tera_listen_address` di-`set_fact` di play facts dengan urutan:

1. host var `ip`
2. IPv4 dari interface `tera_network_interface`
3. `ansible_facts.default_ipv4.address`

Fact ini di-set dengan `cacheable: true` sehingga tersimpan di fact cache cluster; run dengan `--limit`
tetap bisa membaca alamat host lain dari cache. Play facts menggagalkan run jika alamat bukan IPv4
spesifik, berisi `0.0.0.0`, interface tidak ada, atau alamat yang sama dipakai lebih dari satu host.

## Variabel utama

| Variabel | Default |
|---|---|
| `tera_config_dir` | `{{ inventory_dir }}/config` |
| `tera_state_dir` | `/etc/tera` |
| `mariadb_restart_marker` | `{{ tera_state_dir }}/mariadb-restart-pending` |
| `mariadb_galera_marker` | `{{ tera_state_dir }}/mariadb-galera.bootstrapped` |
| `tera_network_interface` | `""` |
| `mariadb_cluster_mode` | `standalone` |
| `mariadb_version` | `"11.4"` |
| `mariadb_port` | `3306` |
| `mariadb_client_sources` | `["0.0.0.0/0"]` (IPv4/CIDR yang boleh ke `mariadb_port` saat Tera mengelola firewalld; juga untuk port VIP) |
| `mariadb_bootstrap_host` | `groups['mariadb'][0]` |
| `mariadb_galera_min_nodes` | `3` |
| `mariadb_clustercheck_port` | `9200` |
| `tera_enable_loadbalancer` | `true` |
| `tera_lb_enabled` | dihitung: galera AND enable AND group `loadbalancer` tidak kosong |
| `tera_vip_address` | `""` (wajib jika LB aktif) |
| `tera_vip_cidr_prefix` | `32` |
| `keepalived_virtual_router_id` | `51` |
| `mariadb_lb_mode` | `single_writer` (`single_writer` \| `multi_writer`) |
| `haproxy_stats_port` | `8404` |
| `haproxy_stats_sources` | `[]` (IPv4/CIDR yang boleh membuka halaman stats; kosong = hanya node load balancer) |
| `haproxy_stats_user` | `tera` (password: `haproxy_stats_password`) |
| `haproxy_check_inter` / `haproxy_check_fastinter` / `haproxy_check_fall` / `haproxy_check_rise` | `1s` / `500ms` / `3` / `2` |
| `haproxy_timeout_check` | `1s` (node yang mati mendadak hanya terdeteksi lewat timeout check) |
| `keepalived_interface` | `""` (kosong = interface yang memegang `tera_listen_address`) |
| `loadbalancer_firewall_manage` | `true` (firewalld di node load balancer, ADR 0011) |

Variabel role `mariadb` (`roles/mariadb/defaults/main.yml`):

| Variabel | Default |
|---|---|
| `mariadb_repo_manage` | `true` (set `false` jika node sudah punya repo/mirror sendiri) |
| `mariadb_repo_deb_url` | `https://mirror.mariadb.org/repo/{{ mariadb_version }}/<distribution>` |
| `mariadb_repo_rpm_url` | `https://rpm.mariadb.org/{{ mariadb_version }}/rhel/{{ distribution_major_version }}/$basearch` |
| `mariadb_packages_extra` | `[]` |
| `mariadb_admin_user` | `tera_admin` |
| `mariadb_admin_hosts` | `["localhost"]` (list host/subnet, mis. `"10.10.10.%"`; `"%"` memicu warning prechecks; host yang dihapus dari list tidak di-drop otomatis) |
| `mariadb_databases` / `mariadb_users` | `[]` |
| `mariadb_sst_user` | `tera_sst` (`@localhost`; password dari `mariadb_sst_password`) |
| `mariadb_galera_allow_sst_overwrite` | `false` (lihat prasyarat deploy di `GALERA-LIFECYCLE.md`) |
| `mariadb_clustercheck_user` | `tera_clustercheck` (`@localhost`, tanpa privilege; password dari `mariadb_clustercheck_password`) |
| `mariadb_recover_from` | `""` (`tera recover`: paksa node bootstrap; kosong = otomatis) |
| `mariadb_datadir` | `/var/lib/mysql` (dibaca pengaman SST dan `tera recover`; samakan jika custom config mengubah datadir) |
| `mariadb_firewall_manage` | `true` (kedua mode, hanya jika firewalld berjalan; ADR 0011) |
| `mariadb_selinux_permissive` | `false` (`true` = domain `mysqld_t` permissive; tidak disarankan) |


## Topologi HA

```
            klien
              │
              ▼
     VIP (Keepalived, VRRP unicast, track haproxy)
              │
   ┌──────────┼──────────┐
   ▼          ▼          ▼
 HAProxy    HAProxy    HAProxy        bind VIP:3306, net.ipv4.ip_nonlocal_bind=1
   │  health check HTTP ke tera-clustercheck :9200
   ▼
 db01 (writer)   db02 (backup)   db03 (backup)
```

- `mysqld` bind ke `tera_listen_address`, **tidak boleh** `0.0.0.0`.
- `auth_pass` VRRP hanya memakai 8 karakter pertama.
- HAProxy `single_writer` (ADR 0004): node pertama group `mariadb` menerima semua koneksi, node lain `backup`
  sesuai urutan inventory. Health check `option httpchk` ke `tera-clustercheck` (`inter 1s fastinter 500ms fall 3 rise 2`,
  `timeout check 1s`; variabel `haproxy_check_*` dan `haproxy_timeout_check`),
  `on-marked-down shutdown-sessions`. Saat writer kembali, `on-marked-up shutdown-backup-sessions` **memutus
  sesi yang sedang berjalan di backup** agar semua klien kembali ke writer: aplikasi harus siap reconnect.
  `multi_writer`: `balance leastconn`, tanpa backup.
- Keepalived: VRRP unicast (`unicast_src_ip` = `tera_listen_address`, peer = node load balancer lain), semua
  node `state BACKUP` + `nopreempt`, prioritas mengikuti urutan inventory (`150 - indeks`). VIP **tidak pindah
  balik** saat node yang mati kembali. `track_script` memindahkan VIP jika HAProxy mati. Interface VIP =
  interface yang memegang `tera_listen_address` (atau `keepalived_interface`).
- Prechecks load balancer: VIP IPv4 di subnet interface VIP dan bukan alamat node, prefix 1-32, VRID 1-255,
  password stats dan `auth_pass` terisi, `haproxy_stats_sources` valid, warning jika hanya satu node load
  balancer. VIP yang sedang dipegang node load balancer cluster ini dianggap normal; selain itu `arping -D`
  harus tidak mendapat jawaban (VIP dipakai host lain = gagal).
- RHEL dengan SELinux: boolean `haproxy_connect_any` di-set agar HAProxy boleh ke port 3306/9200 backend.

## Port

| Port | Fungsi |
|---|---|
| 3306/tcp | MariaDB |
| 4567/tcp+udp | replikasi Galera |
| 4568/tcp | IST |
| 4444/tcp | SST |
| 9200/tcp | tera-clustercheck |
| 8404/tcp | HAProxy stats (dari `haproxy_stats_sources`) |
| protokol 112 | VRRP (hanya dari node load balancer lain) |

SELinux (RHEL, mode galera, SELinux enabled): Tera memasang label `mysqld_port_t` untuk 4568/tcp (IST, tidak
berlabel) dan 4444/tcp (SST, default `kerberos_port_t`), dan memuat modul policy minimal `tera_galera`
(`roles/mariadb/files/tera_galera.te`, salinan di `/etc/tera/selinux/`). Setiap aturan di modul menyebut denial
yang diperbaikinya; semuanya terbatas pada domain `mysqld_t` sendiri (`setpgid` untuk `timeout` di script SST,
`connectto` socket server oleh mariabackup di donor, `sendto` datagram oleh socat di joiner). 4567/tcp sudah
`tram_port_t` dan boleh di-bind `mysqld_t`.

Firewall (ADR 0011, menggantikan ADR 0010): jika firewalld berjalan, di **kedua mode** Tera mengelola zona
default:

| Port | Sumber |
|---|---|
| `mariadb_port` (3306/tcp) | `mariadb_client_sources` (default `0.0.0.0/0` = port dibuka untuk zona; selain itu rich rule per sumber) |
| `mariadb_clustercheck_port` (9200/tcp, galera) | hanya alamat node group `loadbalancer` (group kosong = tertutup) |
| 4567/tcp+udp, 4568/tcp, 4444/tcp (galera) | hanya alamat node cluster |

Tera memiliki rich rule untuk port-port itu di zona default dan menyamakannya setiap deploy/reconfigure: rule
dengan sumber yang tidak lagi diharapkan dihapus, termasuk rule buatan tangan untuk port yang sama. Tera tidak
menyalakan firewalld dan tidak mengelola ufw (prechecks memberi peringatan jika ufw aktif). Matikan dengan
`mariadb_firewall_manage: false` jika firewall dikelola sendiri.

## Artefak di node

| Artefak | Lokasi / mode |
|---|---|
| Config MariaDB | `99-tera.cnf` di `/etc/mysql/mariadb.conf.d/` (Debian) atau `/etc/my.cnf.d/` (RHEL), `0640 root:mysql` |
| Kredensial SST (galera) | `98-tera-sst.cnf` di direktori yang sama, `0640 root:mysql`; satu-satunya file config yang berisi secret, ditulis dengan `no_log` tanpa diff |
| State Tera | `/etc/tera/` (`0750 root:mysql`) |
| Marker bootstrap | `/etc/tera/mariadb-galera.bootstrapped` |
| Restart pending marker | `/etc/tera/mariadb-restart-pending` (`0640 root:mysql`, ADR 0009) |
| Modul SELinux (RHEL, galera) | `/etc/tera/selinux/tera_galera.{te,mod,pp}`, dimuat dengan `semodule` |
| Kredensial clustercheck | `/etc/tera/clustercheck.cnf` (`0640 root:mysql`) |
| Script clustercheck | `/usr/local/bin/tera-clustercheck` |
| Unit systemd | `tera-clustercheck.socket`, `tera-clustercheck@.service` |
| HAProxy | `/etc/haproxy/haproxy.cfg` (`0640 root:haproxy`, berisi password stats) |
| Keepalived | `/etc/keepalived/keepalived.conf` (`0640 root:root`, berisi `auth_pass`) |
| Sysctl load balancer | `/etc/sysctl.d/90-tera-loadbalancer.conf` (`net.ipv4.ip_nonlocal_bind = 1`) |

Semua file yang dirender Tera diberi header "Managed by Tera".

File yang dibaca MariaDB saat boot atau menjadi dasar keputusan Tera (`98`/`99-tera.cnf`, restart pending
marker, marker bootstrap, file clustercheck) di-`sync` ke disk setelah berubah, sehingga mati listrik tidak
meninggalkan file kosong atau terpotong. Restart pending marker di-`sync` sebelum config ditulis (ADR 0009).

## Destroy

`tera destroy -i inventory/<cluster> --yes-i-really-really-mean-it [--keep-data]`:

1. Setiap host menampilkan ringkasan: file dan direktori yang akan dihapus, serta database non-sistem yang
   ditemukan di datadir (pemeriksaan yang sama dengan pengaman SST) dan apakah ikut dihapus.
2. Load balancer: HAProxy dan Keepalived dihentikan dan di-disable (VIP hilang); `haproxy.cfg`,
   `keepalived.conf`, file sysctl, dan aturan firewalld buatan Tera dihapus.
3. MariaDB: `tera-clustercheck` dan MariaDB dihentikan dan di-disable; `98`/`99-tera.cnf`, file dan unit
   clustercheck, aturan firewalld (ADR 0011), modul `tera_galera` dan label port SELinux buatan Tera dihapus.
4. Tanpa `--keep-data`: datadir dan `/etc/tera` ikut dihapus. Deploy berikutnya membangun cluster baru
   (datadir kosong diinisialisasi dengan `mariadb-install-db`).
5. Dengan `--keep-data`: datadir dipertahankan; di mode galera marker bootstrap juga dipertahankan, sehingga
   deploy berikutnya gagal dengan arahan ke `tera recover`, yang memilih node dari `grastate.dat` (ADR 0006).
   Di mode standalone deploy berikutnya langsung memakai datadir lama.

Paket, repo MariaDB, dan boolean SELinux `haproxy_connect_any` tidak disentuh.

## Menambah engine baru

1. Group inventory baru (mis. `postgresql`).
2. `roles/<engine>/` dengan file task per action.
3. `playbooks/<engine>.yml` yang di-import oleh `site.yml`.
4. Pola custom config `config/<engine>/` (global) lalu `config/<engine>/<host>/` (per host).
5. Role `loadbalancer` dipakai ulang.
