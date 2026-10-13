# Konvensi Kode

Dokumen ini wajib dibaca sebelum menulis kode.

## Ansible

- Gunakan **FQCN** untuk semua module (`ansible.builtin.copy`, `ansible.mysql.mysql_user`).
- Module MySQL/MariaDB memakai collection `ansible.mysql`. Jangan memakai `community.mysql`
  (modulnya hanya redirect deprecated ke `ansible.mysql`).
- Prefix variabel:
  - `tera_` — global
  - `mariadb_`, `postgresql_`, `haproxy_`, `keepalived_` — per komponen
  - `_` di depan — variabel internal role (mis. `_mariadb_running`)
- Gunakan `ansible_facts['...']`, bukan fact yang di-inject sebagai variabel (`ansible_os_family`).
- `command`/`shell` wajib punya `changed_when`. Query read-only diberi `check_mode: false` agar `--check --diff` tetap akurat.
- Jangan pakai `shell` jika module setara tersedia.
- Fact boolean di-set dengan `| bool` agar bertipe boolean, bukan string.
- Hindari `run_once` + `set_fact` untuk nilai agregat; hitung di setiap host dari `ansible_play_hosts`.
- Perbedaan OS ditaruh di `roles/<role>/vars/{Debian,RedHat}.yml` dan dimuat oleh `vars.yml`, bukan `when` yang tersebar.
- Template Jinja: waspadai `{#` di script bash (mis. `${#var}`) karena dianggap awal komentar Jinja; gunakan alternatif atau `{% raw %}`.
- Nama task dalam bahasa Inggris, kalimat imperatif (`Install MariaDB packages`).
- `fail_msg` untuk user boleh bahasa Indonesia dan wajib menyebut langkah perbaikan.
- Task yang memuat password: `no_log: true`, dan tetap isi `loop_control.label`. Catatan: di ansible-core
  terbaru (teruji 2.21) label ikut disensor saat `no_log: true`; keamanan password didahulukan.

## Lint

- `ansible-lint` memakai profil `production`.
- Rule `var-naming[no-role-prefix]` dimatikan di `.ansible-lint`. Alasannya: prefix variabel Tera mengikuti
  komponen, bukan nama role (`tera_` di role `tera_defaults`, `haproxy_`/`keepalived_` di role
  `loadbalancer`). Rule `var-naming` lainnya tetap aktif.

## Bash

- `set -euo pipefail`.
- Lolos `shellcheck`.

## Python

- Lolos `ruff`.
- Setiap filter/plugin punya test pytest.
