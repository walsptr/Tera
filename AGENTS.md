# AGENTS.md — Tera

Panduan utama untuk semua AI agent dan kontributor yang bekerja di repository ini.

## Tentang project

Tera adalah tool otomasi berbasis Ansible untuk deploy dan mengelola database.
Engine pertama: **MariaDB** (standalone dan Galera HA). PostgreSQL menyusul (Patroni + etcd).

Tera menggabungkan dua pola:

- **kubespray** — satu cluster = satu folder `inventory/<cluster>/`. Cluster baru cukup `tera new-cluster <nama>`.
- **kolla-ansible** — custom config di `inventory/<cluster>/config/`. `tera reconfigure` me-merge config,
  mengirimnya ke node, lalu rolling restart hanya node yang config-nya berubah.

## Status & target

- Fase aktif: **Fase 3 — Load balancer** (Fase 2 selesai, tag `v0.2.0`; Fase 1 tag `v0.1.0`). Checklist di `docs/ROADMAP.md`.
- OS target: Ubuntu 22.04 / 24.04, Rocky Linux 9, AlmaLinux 9. Jangan menambah OS lain tanpa diminta.
- MariaDB dari repo upstream, default `mariadb_version: "11.4"`.
- ansible-core >= 2.16 (syarat `ansible.mysql`). Dev/CI memakai versi yang di-pin di `requirements-dev.txt`. Collections: `ansible.mysql`, `community.general`, `ansible.posix`.

## Struktur repo

Ringkas (detail di `docs/ARCHITECTURE.md`):

```
tera                  # CLI bash di atas ansible-playbook
ansible.cfg  requirements.yml  site.yml
playbooks/            # facts, common, mariadb, loadbalancer, mariadb-recover, destroy
plugins/filter/       # merge_ini.py, tera_ip.py + tests/
roles/tera_defaults/  # hanya defaults/main.yml — default global
roles/common/  roles/mariadb/  roles/loadbalancer/
inventory/sample/     # template cluster: hosts.yml, group_vars/all/, config/
docs/                 # spesifikasi, roadmap, ADR
molecule/             # skenario test
```

## Setup lingkungan dev

Semua alat dipasang lokal di root repo (`.venv/` dan `collections/`, keduanya di-gitignore);
`ansible.cfg` sudah menunjuk `collections_path = ./collections`.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ansible-galaxy collection install -r requirements.yml -p ./collections
.venv/bin/ansible-galaxy collection install -r molecule/requirements.yml -p ./collections   # test only
source .venv/bin/activate        # atau panggil .venv/bin/<alat> langsung
```

## Perintah

```bash
ansible-lint
ansible-playbook -i inventory/sample/hosts.yml site.yml --syntax-check
pytest plugins/
molecule test -s <scenario>        # standalone | standalone-podman | galera | reconfigure | recover | scale

./tera new-cluster prod-a
./tera genpwd      -i inventory/prod-a
./tera prechecks   -i inventory/prod-a
./tera deploy      -i inventory/prod-a
./tera reconfigure -i inventory/prod-a [--check --diff]
./tera recover     -i inventory/prod-a [-e mariadb_recover_from=db02]
./tera destroy     -i inventory/prod-a --yes-i-really-really-mean-it [--keep-data]
```

## Konsep inti

- **Action pattern**: CLI mengirim `-e tera_action=<action>`; playbook memanggil `include_role` dengan `tasks_from: "{{ tera_action }}.yml"`. Setiap role wajib punya file untuk setiap action yang didukung.
- **Urutan play**: validate → facts → common → mariadb → rolling restart mariadb (`serial: 1`) → loadbalancer.
- **Default global** ada di role `tera_defaults` yang dimuat di setiap play, bukan di `group_vars` milik playbook.
- **Nilai lintas host** (mis. `tera_listen_address`) wajib di-`set_fact` di play facts: host var `ip` → `tera_network_interface` → default route.
- **Fact cache per cluster**: CLI meng-export `ANSIBLE_CACHE_PLUGIN_CONNECTION=inventory/<cluster>/.facts_cache`.
- **Custom config MariaDB**: filter `merge_ini` (template role → `config/mariadb/*.cnf` → `config/mariadb/<host>/*.cnf`, belakang menang) ke satu file `99-tera.cnf`.
- **Mode**: `mariadb_cluster_mode: standalone | galera`. Load balancer hanya aktif di mode galera.

## Aturan keras (WAJIB)

1. **Jangan pernah bootstrap Galera otomatis** jika marker `/etc/tera/mariadb-galera.bootstrapped` ada di salah satu node dan tidak ada node Primary. Gagalkan run dan arahkan ke `tera recover`.
2. **Jangan pakai handler untuk restart MariaDB.** Restart hanya lewat play rolling restart: `serial: 1`, `max_fail_percentage: 0`, hanya node dengan `mariadb_restart_required`, tunggu Synced sebelum node berikutnya.
3. **Marker dan state Tera di `/etc/tera/`**, bukan di datadir (SST menimpa datadir).
4. **User SST harus dibuat di node bootstrap sebelum joiner di-start.**
5. **Tolak `--limit` saat `deploy` mode Galera.**
6. **Output config deterministik**: tanpa timestamp, tanpa path absolut controller.
7. **Idempotent**: run kedua `deploy` pada cluster sehat harus `changed=0`.
8. **Tidak ada secret di repo.** `passwords.yml` sample hanya berisi key kosong. Task yang memuat password wajib `no_log: true`.
9. **Root MariaDB tetap `unix_socket`.** Ansible login via socket sebagai root (become). Akses remote via user admin terpisah.
10. **Jangan mengubah keputusan di `docs/decisions/` tanpa diskusi.** Usulkan ADR baru.
11. **Jangan menaruh default di `playbooks/group_vars/`** (precedence-nya menimpa `group_vars` inventory user).

## Cara kerja agent

- Untuk perubahan multi file: buat rencana dulu dan minta persetujuan sebelum menulis kode.
- Kerjakan satu item `docs/ROADMAP.md` per kali.
- Setelah perubahan, jalankan verifikasi yang relevan dan laporkan hasilnya apa adanya.
- Jika perilaku berubah, perbarui `docs/` dalam perubahan yang sama.
- Centang item ROADMAP setelah verifikasi lulus, dalam commit yang sama.
- Jika ragu tentang Galera, SST, restart, atau apa pun yang menyangkut keamanan data: tanyakan, jangan menebak.
- Jangan pernah menjalankan playbook terhadap host nyata. Hanya Molecule atau lab yang disepakati.
- Dokumentasi berbahasa Indonesia. Nama task, nama variabel, dan komentar kode berbahasa Inggris.

## Dokumen referensi

- `docs/ARCHITECTURE.md` — struktur, alur play, CLI, variabel, topologi HA. Baca saat menambah file/role/play.
- `docs/CONVENTIONS.md` — konvensi kode. **Selalu dibaca sebelum menulis kode.**
- `docs/CUSTOM-CONFIG.md` — spesifikasi merge + contoh CC-xx. Wajib sebelum menyentuh `merge_ini` atau `roles/mariadb/tasks/config.yml`.
- `docs/GALERA-LIFECYCLE.md` — state machine bootstrap/join/restart/recover. **Wajib** sebelum menyentuh `status.yml`, `galera.yml`, `restart.yml`, `recover.yml`, `wait_synced.yml`.
- `docs/ROADMAP.md` — fase dan checklist.
- `docs/TESTING.md` — level test, skenario Molecule, definition of done.
- `docs/decisions/` — ADR. Baca sebelum mengusulkan perubahan desain.
