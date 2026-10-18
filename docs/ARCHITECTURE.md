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
playbooks/{facts,common,mariadb,loadbalancer,backup,monitoring,mariadb-recover,mariadb-backup,mariadb-restore,mariadb-upgrade,destroy}.yml
playbooks/tasks/listen_address.yml     # tera_listen_address, dipakai facts.yml dan mariadb-restore.yml
plugins/filter/{merge_ini,tera_ip}.py   plugins/tests/test_{merge_ini,tera_ip,tera_backup}.py   # tests outside filter/: Ansible loads filter subdirs as plugins
roles/tera_defaults/defaults/main.yml
roles/common/tasks/{prechecks,deploy,reconfigure}.yml
roles/mariadb/{defaults,vars/{Debian,RedHat}.yml,templates,tasks}
  tasks entry point: prechecks deploy reconfigure restart recover destroy restore_{prepare,apply,finish}
  tasks internal:    vars install firewall config status standalone galera users clustercheck selinux wait_synced
                     restore_transfer restore_abort
  templates:         tera.cnf.j2 tera-clustercheck.j2 tera-clustercheck.socket.j2 tera-clustercheck@.service.j2
roles/loadbalancer/{defaults,handlers,templates/{haproxy.cfg.j2,keepalived.conf.j2},tasks/{prechecks,deploy,reconfigure,destroy,install,config}.yml}
roles/mariadb_backup/{defaults,vars,templates,files/{tera_backup.py,backup-target-rsync}}   # ADR 0012
  tasks entry point: prechecks deploy reconfigure destroy keys op_{run,verify,status}
roles/backup_target/{defaults,vars,templates,files/tera_backup_target.py,tasks/{prechecks,deploy,reconfigure,destroy}.yml}
roles/monitoring/{defaults,vars/{main,Debian,RedHat}.yml,templates}   # ADR 0016
  tasks entry point: prechecks deploy reconfigure destroy
  tasks internal:    vars mysqld_exporter node_exporter binary releases_remove remove firewall
inventory/sample/{hosts.yml,group_vars/all/{tera.yml,passwords.yml},config/{mariadb,haproxy/conf.d,keepalived}}
docs/
molecule/{shared,standalone,standalone-podman,galera,reconfigure,recover,recover-poweroff,loadbalancer,destroy,backup,backup-galera,upgrade,upgrade-podman,monitoring,monitoring-podman}/   # shared = playbook dan task bersama
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
- `mariadb_backup_target` — opsional, host backup untuk salinan remote (ADR 0012). Node backup hanya bisa
  menulis ke sana (`rrsync -wo -no-del`); retensi dan pemeriksaan checksum berjalan di host itu.

Host var opsional: `ip` (alamat yang dipakai Tera untuk listen dan komunikasi antar node).

Nilai yang wajib unik per cluster dan divalidasi di prechecks:

- `tera_cluster_name` (default: nama folder cluster; dipakai metadata dan path backup, dan default
  `mariadb_galera_cluster_name`)
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
| `upgrade -i -e mariadb_upgrade_to=<X.Y.Z\|latest> [--check]` | `playbooks/mariadb-upgrade.yml` (ADR 0015) | `upgrade` |
| `destroy -i … --yes-i-really-really-mean-it [--keep-data]` | `playbooks/destroy.yml` (`-e tera_destroy_confirm=true`, `--keep-data` → `-e tera_destroy_keep_data=true`) | – |
| `backup -i [--incremental]` | `playbooks/mariadb-backup.yml` (`-e tera_backup_op=run -e mariadb_backup_type=full\|incremental`) | – |
| `backup-verify -i` | `playbooks/mariadb-backup.yml` (`-e tera_backup_op=verify`) | – |
| `backup-status -i` | `playbooks/mariadb-backup.yml` (`-e tera_backup_op=status`) | – |
| `restore -i … --yes-i-really-really-mean-it -e mariadb_restore_backup=<id>` | `playbooks/mariadb-restore.yml` (`-e tera_restore_confirm=true`) | – |

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
- `destroy` dan `restore` ditolak tanpa flag `--yes-i-really-really-mean-it`. `--keep-data` hanya diterima oleh
  `destroy`, `--incremental` hanya oleh `backup`.

## Alur play `site.yml`

| # | Play | Hosts | Catatan |
|---|---|---|---|
| 1 | Validate | localhost | ansible-core >= 2.16, `tera_action` valid |
| 2 | Facts | `mariadb:loadbalancer:mariadb_backup_target` | `set_fact: tera_listen_address` |
| 3 | Common | `mariadb:loadbalancer:mariadb_backup_target` | paket dasar |
| 4 | MariaDB | `mariadb` | install, config, start/bootstrap/join, users |
| 5 | Rolling restart | `mariadb`, `serial: 1` | hanya node `mariadb_restart_required`; restart di bawah lock backup |
| 6 | Load balancer | `loadbalancer` | hanya jika `tera_lb_enabled` |
| 7 | Backup keys | `mariadb` | kunci SSH node backup (hanya jika ada target remote) |
| 8 | Backup target | `mariadb_backup_target` | user, direktori, `authorized_keys` tulis-saja, timer retensi; publikasi host key |
| 9 | MariaDB backup | `mariadb` | alat, script, config, `known_hosts`, timer di `mariadb_backup_host`; peringatan jika backup mati |
| 10 | Monitoring | `mariadb` | exporter, user OS, rule firewall, `tera_backup.prom`; jika monitoring mati: semua itu dihapus (ADR 0016) |

Setiap play memuat role `tera_defaults` dan memakai `any_errors_fatal: true`.

## Alur play `playbooks/mariadb-upgrade.yml` (ADR 0015)

| # | Play | Hosts | Catatan |
|---|---|---|---|
| 1 | Start | localhost | id run (nama file log di node) |
| 2 | Facts | `mariadb:loadbalancer` | `tera_listen_address` |
| 3 | Prechecks | `mariadb` | prechecks umum, sisa run terputus, versi target seragam (dibaca dari repo `mariadb_repo_*_url` lewat probe sementara, repo node belum diubah), seri/downgrade, cluster sehat, ruang `/var`, backup terverifikasi; menampilkan rencana |
| 4 | Repo | `mariadb` | tulis repo node setelah semua prechecks lulus; cek repo menyediakan versi target |
| 5 | Upgrade | `mariadb[1:]`, `serial: 1` | node non-writer, urutan inventory; hanya node yang belum di versi target |
| 6 | Upgrade | `mariadb[0]`, `serial: 1` | writer `single_writer` paling akhir |

Per node: lock backup (unit `tera-mariadb-upgrade-lock`), drain (`tera-clustercheck.socket` dihentikan, tunggu
DOWN di stats HAProxy), stop, upgrade paket (Ubuntu: `policy-rc.d` Tera; retry; log), pastikan MariaDB masih
mati, start, Synced, tunggu `mariadb-upgrade` dari `debian-start` (Ubuntu), `mariadb-upgrade --force`, cek
`mariadb_upgrade_info`, undrain (blok `always`), tunggu UP. `--check` hanya menjalankan prechecks dan menampilkan
perubahan repo tanpa menulisnya.

## Matriks action

| Role | `prechecks` | `deploy` | `reconfigure` |
|---|---|---|---|
| common | OS | prechecks + paket | prechecks |
| mariadb | topologi, password, OS | prechecks, install, config, start/bootstrap/join, users, clustercheck | prechecks, config, users, clustercheck |
| loadbalancer | VIP, VRID, password | prechecks, install, config, start | prechecks, config + reload |
| mariadb_backup | node backup, writer, target, public key | prechecks, alat, script, config, timer | sama dengan deploy |
| backup_target | OS, direktori | prechecks, paket, user, kunci node, timer | sama dengan deploy |
| monitoring | sumber, checksum per arsitektur, port | prechecks, exporter (unduh + checksum), unit, firewall, metrik backup; atau hapus semuanya | sama dengan deploy |

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
| `mariadb_datadir_marker` | `{{ tera_state_dir }}/mariadb-datadir.initialized` |
| `mariadb_restore_marker` | `{{ tera_state_dir }}/mariadb-restore.active` (ditulis `tera restore`; backup menolak berjalan selama ada) |
| `tera_cluster_name` | nama folder inventory |
| `mariadb_datadir` | `/var/lib/mysql` (dibaca pengaman SST, `tera recover`, backup, dan restore; samakan jika custom config mengubah datadir) |
| `mariadb_backup_enabled` | `false` (opt-in; deploy/reconfigure memberi peringatan selama `false`) |
| `mariadb_backup_host` | `groups['mariadb'][-1]` (galera: writer ditolak kecuali `mariadb_backup_allow_writer`) |
| `mariadb_backup_dir` | `/var/backups/tera/mariadb` (disarankan disk terpisah; tidak pernah dihapus `tera destroy`) |
| `mariadb_backup_keep_full` | `2` (retensi per jumlah rantai, di node dan host backup) |
| `mariadb_backup_targets` | `[]` (`[{name, type: rsync, host, port}]`; host di group `mariadb_backup_target`) |
| `mariadb_backup_lock` / `mariadb_backup_lock_timeout` | `/run/lock/tera-mariadb-backup.lock` / `7200` (rolling restart dan restore menunggu backup) |
| `mariadb_backup_target_dir` / `mariadb_backup_target_user` | `/srv/tera-backup` / `tera-backup` |
| `mariadb_restore_user` / `mariadb_restore_key_ttl` | `tera-restore` / `7200` (penerima restore dan umur kunci sementara, ADR 0014) |
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
| `mariadb_packages_extra` | `[]` (dipasang tanpa paket yang dianjurkan, seperti paket MariaDB: `install_recommends`/`install_weak_deps` mati, ADR 0015) |
| `mariadb_upgrade_to` | `""` (`tera upgrade`: patch dalam seri `mariadb_version`, mis. `"11.4.13"`, atau `latest`) |
| `mariadb_upgrade_galera_to` | `latest` (versi galera-4; `latest` = tertinggi di repo) |
| `mariadb_upgrade_max_backup_age` | `86400` (detik; umur maksimal backup terverifikasi saat backup aktif) |
| `mariadb_upgrade_allow_without_backup` | `false` (`true` = upgrade boleh saat backup tidak aktif) |
| `mariadb_upgrade_package_retries` / `mariadb_upgrade_package_delay` | `3` / `10` |
| `mariadb_upgrade_min_free_mb` | `1024` (ruang bebas minimal di `/var`) |
| `mariadb_upgrade_debian_start_timeout` | `600` (Ubuntu: tunggu `mariadb-upgrade` dari `debian-start`) |
| `mariadb_upgrade_lb_timeout` | `60` (tunggu HAProxy menandai node DOWN/UP) |
| `mariadb_admin_user` | `tera_admin` |
| `mariadb_admin_hosts` | `["localhost"]` (list host/subnet, mis. `"10.10.10.%"`; `"%"` memicu warning prechecks; host yang dihapus dari list tidak di-drop otomatis) |
| `mariadb_databases` / `mariadb_users` | `[]` |
| `mariadb_sst_user` | `tera_sst` (`@localhost`; password dari `mariadb_sst_password`) |
| `mariadb_galera_allow_sst_overwrite` | `false` (lihat prasyarat deploy di `GALERA-LIFECYCLE.md`) |
| `mariadb_clustercheck_user` | `tera_clustercheck` (`@localhost`, tanpa privilege; password dari `mariadb_clustercheck_password`) |
| `mariadb_recover_from` | `""` (`tera recover`: paksa node bootstrap; kosong = otomatis) |
| `tera_manage_firewall` | `true` (`false` = Tera tidak pernah menyentuh firewalld) |
| `mariadb_firewall_manage` | `true` (kedua mode, hanya jika firewalld berjalan; ADR 0011) |
| `mariadb_selinux_permissive` | `false` (`true` = domain `mysqld_t` permissive; tidak disarankan) |

Variabel role `mariadb_backup` (`roles/mariadb_backup/defaults/main.yml`, ADR 0012):

| Variabel | Default |
|---|---|
| `mariadb_backup_full_schedule` / `mariadb_backup_incremental_schedule` | `Sun *-*-* 01:00:00` / `Mon..Sat *-*-* 01:00:00` (systemd `OnCalendar`) |
| `mariadb_backup_randomized_delay` | `15min` |
| `mariadb_backup_throttle` | `""` (mati; jika diisi, jendela desync galera ikut memanjang) |
| `mariadb_backup_verify_after_full` / `mariadb_backup_verify_memory_max` | `true` / `1G` |
| `mariadb_backup_gpg_public_key` | `""` (wajib jika ada target remote atau `mariadb_backup_encrypt_local`) |
| `mariadb_backup_encrypt_local` | `false` |
| `mariadb_backup_allow_writer` | `false` |
| `mariadb_backup_source_address` | (opsional, host var) alamat node yang dilihat host backup untuk `from=`; default `tera_listen_address` |

Variabel monitoring (ADR 0016; `tera_monitoring_enabled`, `tera_monitoring_sources`, `mysqld_exporter_user`,
`tera_monitoring_textfile_dir` di `tera_defaults`, sisanya di `roles/monitoring/defaults/main.yml`,
`haproxy_prometheus_enabled` di role `loadbalancer`):

| Variabel | Default |
|---|---|
| `tera_monitoring_enabled` / `node_exporter_enabled` | `false` / `false` |
| `tera_monitoring_sources` | `[]` (exporter hanya di `127.0.0.1`; diisi = `tera_listen_address` + rich rule per sumber) |
| `mysqld_exporter_version` / `_url` / `_sha256` / `_port` | `0.20.0` / GitHub releases / per arsitektur (`amd64`, `arm64`) / `9104` |
| `node_exporter_version` / `_url` / `_sha256` / `_port` | `1.12.1` / GitHub releases / per arsitektur / `9100` |
| `mysqld_exporter_user` / `node_exporter_user` | `tera-exporter` / `tera-node-exporter` |
| `tera_monitoring_textfile_dir` | `/var/lib/tera/node_exporter` |
| `monitoring_download_dir` / `monitoring_firewall_manage` | `/var/cache/tera/exporters` / `true` |
| `haproxy_prometheus_enabled` | `false` (`/metrics` di port stats, user stats) |

Variabel `tera restore` (ADR 0013, lewat `-e`): `mariadb_restore_backup` (`latest` atau `<chain_id>/<sequence>`),
`mariadb_restore_host` (default: standalone = satu-satunya node, galera = `mariadb_bootstrap_host`),
`mariadb_restore_source` (`local` atau nama target), `mariadb_restore_source_host` (node yang backup-nya
dipulihkan; default `mariadb_backup_host`), `mariadb_restore_gpg_private_key` (file di controller),
`mariadb_restore_allow_mode_change` (`false`).


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
| 8404/tcp | HAProxy stats dan `/metrics` (dari `haproxy_stats_sources`, plus `tera_monitoring_sources` jika `haproxy_prometheus_enabled`) |
| 9104/tcp, 9100/tcp | `mysqld_exporter`, `node_exporter` (dari `tera_monitoring_sources`; kosong = hanya `127.0.0.1`) |
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
| `mysqld_exporter_port`, `node_exporter_port` (monitoring) | `tera_monitoring_sources` (role `monitoring`, `monitoring_firewall_manage`) |

Semua `*_sources` hanya ditegakkan lewat rich rule ini. Di host tanpa firewalld yang berjalan atau yang
firewalld-nya tidak dikelola, prechecks memberi peringatan per host jika sumbernya dibatasi (ADR 0016).

Tera memiliki rich rule untuk port-port itu di zona default dan menyamakannya setiap deploy/reconfigure: rule
dengan sumber yang tidak lagi diharapkan dihapus, termasuk rule buatan tangan untuk port yang sama. Sebelum
menghapus, Tera menampilkan rule dan port zona yang akan dihapus per host; tampilan ini juga muncul di
`--check --diff` (tanpa perubahan). Tera tidak menyalakan firewalld dan tidak mengelola ufw (prechecks memberi
peringatan jika ufw aktif).

`tera_manage_firewall: false` (global, default `true`) membuat Tera **sama sekali tidak menyentuh firewalld**
di deploy, reconfigure, dan destroy, untuk role `mariadb` maupun `loadbalancer`. `mariadb_firewall_manage` dan
`loadbalancer_firewall_manage` hanya mematikan per role dan diabaikan jika `tera_manage_firewall` false.

## Artefak di node

| Artefak | Lokasi / mode |
|---|---|
| Config MariaDB | `99-tera.cnf` di `/etc/mysql/mariadb.conf.d/` (Debian) atau `/etc/my.cnf.d/` (RHEL), `0640 root:mysql` |
| Kredensial SST (galera) | `98-tera-sst.cnf` di direktori yang sama, `0640 root:mysql`; satu-satunya file config yang berisi secret, ditulis dengan `no_log` tanpa diff |
| State Tera | `/etc/tera/` (`0750 root:mysql`) |
| Marker bootstrap | `/etc/tera/mariadb-galera.bootstrapped` |
| Marker datadir | `/etc/tera/mariadb-datadir.initialized` (`0640 root:mysql`): ditulis setelah datadir pertama kali terinisialisasi; jika marker ada tetapi datadir kosong (tidak ada `mysql/`), deploy gagal dan meminta operator mengecek mount/disk, bukan menginisialisasi database baru |
| Restart pending marker | `/etc/tera/mariadb-restart-pending` (`0640 root:mysql`, ADR 0009) |
| Log upgrade | `/var/log/tera/mariadb-upgrade-<versi>-<id run>-{packages,mariadb-upgrade}.log` (`0640 root`, ADR 0015) |
| Selama upgrade saja | `/usr/sbin/policy-rc.d` milik Tera (Ubuntu, hanya menolak `mariadb`), unit sementara `tera-mariadb-upgrade-lock.service` (memegang lock backup, file `/run/tera-mariadb-upgrade-lock.held`); sisa run terputus dibersihkan `deploy`/`reconfigure`/`upgrade` dengan peringatan |
| Modul SELinux (RHEL, galera) | `/etc/tera/selinux/tera_galera.{te,mod,pp}`, dimuat dengan `semodule` |
| Kredensial clustercheck | `/etc/tera/clustercheck.cnf` (`0640 root:mysql`) |
| Script clustercheck | `/usr/local/bin/tera-clustercheck` |
| Unit systemd | `tera-clustercheck.socket`, `tera-clustercheck@.service` |
| HAProxy | `/etc/haproxy/haproxy.cfg` (`0640 root:haproxy`, berisi password stats) |
| Keepalived | `/etc/keepalived/keepalived.conf` (`0640 root:root`, berisi `auth_pass`) |
| Sysctl load balancer | `/etc/sysctl.d/90-tera-loadbalancer.conf` (`net.ipv4.ip_nonlocal_bind = 1`) |
| Backup (semua node MariaDB) | `/usr/local/sbin/tera-backup`, `/usr/local/lib/tera/backup-targets/rsync`, `/etc/tera/backup/config.json` (`0600 root`); `mariadb_backup_dir`, `.incoming/`, `.restore/`, `.verify/` `0711 root` (bisa dilewati, tidak bisa didaftar; isi rantai `0700 root`; induk default `/var/backups/tera` `0711`); user `tera-restore` (password terkunci, home `/var/lib/tera-restore`, `authorized_keys` hanya berisi entri sementara selama restore) |
| Backup (node backup) | unit `tera-backup@.service`, `tera-backup-{full,incremental}.timer`, `tera-backup-verify.service`; kunci SSH `/etc/tera/backup/id_ed25519`, `known_hosts`, keyring public key `/etc/tera/backup/gnupg`, status `/etc/tera/mariadb-backup.status` (JSON, sumber metrik `tera_backup_*`, ADR 0016) |
| Monitoring (semua node MariaDB, ADR 0016) | `/usr/local/bin/{mysqld,node}_exporter`, unit `tera-mysqld-exporter.service` dan `tera-node-exporter.service`, user OS `tera-exporter` dan `tera-node-exporter` (sistem, tanpa shell, tanpa home), `/etc/tera-exporter/my.cnf` (`0640 root:tera-exporter`, hanya `user` dan `socket`), user MariaDB `'tera-exporter'@'localhost'` (`unix_socket`), `/var/lib/tera/node_exporter/tera_backup.prom` (`0644`, ditulis `tera-backup metrics` dan setiap perubahan status), unduhan di `/var/cache/tera/exporters` |
| Host backup | user `tera-backup`, `mariadb_backup_target_dir/<cluster>/<node>/`, state verifikasi `/var/lib/tera-backup-target/state/` (di luar jangkauan node), `/etc/tera/backup-target/<cluster>.json`, `tera-backup-target.{service,timer}` |

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
4. Tanpa `--keep-data`: datadir dan `/etc/tera` (termasuk marker datadir) ikut dihapus. Deploy berikutnya
   membangun cluster baru (datadir kosong diinisialisasi dengan `mariadb-install-db`).
5. Dengan `--keep-data`: datadir dan marker datadir dipertahankan; di mode galera marker bootstrap juga dipertahankan, sehingga
   deploy berikutnya gagal dengan arahan ke `tera recover`, yang memilih node dari `grastate.dat` (ADR 0006).
   Di mode standalone deploy berikutnya langsung memakai datadir lama.

6. Monitoring: exporter, unit, user OS, `/etc/tera-exporter`, direktori textfile, unduhan, dan rule firewalld
   exporter dihapus. User MariaDB `tera-exporter` ikut datadir (tetap ada dengan `--keep-data`).
7. Backup: timer, unit, script, dan `/etc/tera/backup` dihapus. Isi `mariadb_backup_dir` di node dan backup di
   host backup **tidak pernah dihapus** (juga tanpa `--keep-data`); ringkasan menyebut lokasinya.

Paket, repo MariaDB, dan boolean SELinux `haproxy_connect_any` tidak disentuh.

## Menambah engine baru

1. Group inventory baru (mis. `postgresql`).
2. `roles/<engine>/` dengan file task per action.
3. `playbooks/<engine>.yml` yang di-import oleh `site.yml`.
4. Pola custom config `config/<engine>/` (global) lalu `config/<engine>/<host>/` (per host).
5. Role `loadbalancer` dipakai ulang.
