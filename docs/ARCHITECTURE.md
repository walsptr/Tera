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
| `destroy -i … --yes-i-really-really-mean-it` | `playbooks/destroy.yml` (`-e tera_destroy_confirm=true`) | – |

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
- `destroy` ditolak tanpa flag `--yes-i-really-really-mean-it`.

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
| `mariadb_firewall_manage` | `true` (mode galera, hanya jika firewalld berjalan; ADR 0010) |
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

## Port

| Port | Fungsi |
|---|---|
| 3306/tcp | MariaDB |
| 4567/tcp+udp | replikasi Galera |
| 4568/tcp | IST |
| 4444/tcp | SST |
| 9200/tcp | tera-clustercheck |
| 8404/tcp | HAProxy stats |
| protokol 112 | VRRP |

SELinux (RHEL, mode galera, SELinux enabled): Tera memasang label `mysqld_port_t` untuk 4568/tcp (IST, tidak
berlabel) dan 4444/tcp (SST, default `kerberos_port_t`), dan memuat modul policy minimal `tera_galera`
(`roles/mariadb/files/tera_galera.te`, salinan di `/etc/tera/selinux/`). Setiap aturan di modul menyebut denial
yang diperbaikinya; semuanya terbatas pada domain `mysqld_t` sendiri (`setpgid` untuk `timeout` di script SST,
`connectto` socket server oleh mariabackup di donor, `sendto` datagram oleh socat di joiner). 4567/tcp sudah
`tram_port_t` dan boleh di-bind `mysqld_t`.

Firewall (ADR 0010): di mode galera, jika firewalld berjalan, Tera membuka 4567/tcp, 4567/udp, 4568/tcp, dan
4444/tcp **hanya dari alamat node cluster** (rich rule), serta `mariadb_port` dan `mariadb_clustercheck_port`
di zona default. Tera tidak menyalakan firewalld dan tidak mengelola ufw (prechecks memberi peringatan jika
ufw aktif). Matikan dengan `mariadb_firewall_manage: false` jika firewall dikelola sendiri.

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
| HAProxy | `/etc/haproxy/haproxy.cfg` (`0640`) |
| Keepalived | `/etc/keepalived/keepalived.conf` (`0640`) |

Semua file yang dirender Tera diberi header "Managed by Tera".

File yang dibaca MariaDB saat boot atau menjadi dasar keputusan Tera (`98`/`99-tera.cnf`, restart pending
marker, marker bootstrap, file clustercheck) di-`sync` ke disk setelah berubah, sehingga mati listrik tidak
meninggalkan file kosong atau terpotong. Restart pending marker di-`sync` sebelum config ditulis (ADR 0009).

## Menambah engine baru

1. Group inventory baru (mis. `postgresql`).
2. `roles/<engine>/` dengan file task per action.
3. `playbooks/<engine>.yml` yang di-import oleh `site.yml`.
4. Pola custom config `config/<engine>/` (global) lalu `config/<engine>/<host>/` (per host).
5. Role `loadbalancer` dipakai ulang.
