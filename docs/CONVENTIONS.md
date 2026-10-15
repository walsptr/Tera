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
- **Backslash di regex dalam `{{ }}` bergantung pada gaya scalar YAML** (teruji di ansible-core yang di-pin):
  - Scalar folded (`>-`, `|`) atau plain: tulis **satu** backslash (`'\s'`). Di sini `'\\s'` tidak di-unescape;
    regex menerima backslash literal dan **diam-diam tidak pernah cocok**.
  - String YAML double-quoted (`"{{ ... }}"`): tulis `'\\s'`, karena YAML sendiri mengubah `\\` menjadi `\`.
  - Di `that:`/`when:` kedua bentuk bekerja, tetapi tetap ikuti aturan di atas agar konsisten.
  - String literal Jinja memproses escape backslash: `'\b'` menjadi karakter backspace, `'\t'` menjadi tab.
    Jangan memakai `\b` di regex Jinja; untuk output tabular pilih perbandingan tanpa regex, mis.
    `stdout_lines | map('split') | map('join', '=')`. (`\s` lolos hanya karena bukan escape yang dikenal.)
  - Uji filter regex baru dengan playbook kecil sebelum dipakai. Bug ini pernah membuat `tera recover` tidak
    bisa membaca `WSREP: Recovered position`: posisi jatuh ke `-1`, dan recover menolak berjalan dengan pesan
    "uuid berbeda atau tidak ada posisi" yang menyesatkan.

  ```yaml
  # Salah: folded scalar + '\\s' -> tidak pernah cocok, _position selalu []
  _position: >-
    {{ log | regex_findall('Recovered position:\\s*([0-9a-f-]+):(-?[0-9]+)') | last | default([]) }}

  # Benar: folded scalar + '\s'
  _position: >-
    {{ log | regex_findall('Recovered position:\s*([0-9a-f-]+):(-?[0-9]+)') | last | default([]) }}

  # Benar: double-quoted YAML + '\\s'
  _uuid: "{{ grastate | regex_search('^uuid:\\s*(\\S+)', '\\1', multiline=True) | first }}"
  ```
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
