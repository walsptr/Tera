# Custom Config

Dokumen ini adalah **acuan perilaku** filter `merge_ini` (`plugins/filter/merge_ini.py`) dan
`roles/mariadb/tasks/config.yml`. Setiap contoh `CC-xx` di bawah **wajib** punya test
(`plugins/tests/test_merge_ini.py`, nama test menyebut ID-nya). Jika implementasi berbeda
dari dokumen ini, dokumen ini yang benar.

## Lokasi

```
{{ tera_config_dir }}/
├── mariadb/*.cnf                         # semua node mariadb
├── mariadb/<inventory_hostname>/*.cnf    # host tertentu
├── haproxy/haproxy.cfg                   # override penuh (opsional)
├── haproxy/conf.d/*.cfg                  # snippet di-append (opsional)
└── keepalived/keepalived.conf            # override penuh (opsional)
```

- Default `tera_config_dir` adalah `{{ inventory_dir }}/config`. Path relatif untuk `tera_config_dir` tidak didukung.
- File selain `*.cnf` di `mariadb/` diabaikan.
- Direktori yang tidak ada dianggap kosong (bukan error).

## Urutan merge (belakang menang)

1. Template role `tera.cnf.j2`
2. `mariadb/*.cnf` (urut alfabetis)
3. `mariadb/<inventory_hostname>/*.cnf` (urut alfabetis)

Hasil merge ditulis ke satu file drop-in `99-tera.cnf`.

Isi template role saat ini (mode standalone): `[mysqld]` dengan `bind_address = {{ tera_listen_address }}`,
`port = {{ mariadb_port }}`, dan `skip_name_resolve`. Semuanya bisa di-override atau dihapus (`__remove__`)
lewat custom config. File berubah → `mariadb_restart_required: true`; `config.yml` sendiri tidak pernah me-restart.

## Jinja2

Setiap custom file di-render dengan `lookup('ansible.builtin.template', …)` dalam konteks host target,
sehingga variabel seperti `{{ tera_listen_address }}` atau `{{ ansible_facts['memtotal_mb'] }}` bisa dipakai.
Error Jinja harus menyebut nama file yang bermasalah.

## Aturan parsing

| Aturan | Perilaku |
|---|---|
| Delimiter | hanya `=` (dipisah pada `=` pertama) |
| Key tanpa value | didukung (mis. `skip_name_resolve`) |
| Normalisasi key | trim spasi, lowercase, lalu `-` → `_` (`Max-Connections` = `max_connections`) |
| Nama section | case-sensitive, tidak diubah |
| Komentar | baris yang diawali `#` atau `;` dibuang; tidak ada inline comment |
| Key duplikat dalam satu file | terakhir menang |
| Key sebelum section | error |
| `!include` / `!includedir` | error |
| Value `__remove__` | key dihapus; jika key tidak ada, bukan error |
| Section kosong | tidak ditulis |

Value di-trim spasi di kedua sisi. Selain itu value dipertahankan apa adanya, termasuk tanda kutip.

## Format output

```
# Managed by Tera - JANGAN edit manual
# Ubah lewat custom config: config/mariadb/
# Sources: role:tera.cnf.j2[, <path relatif terhadap tera_config_dir>...]

[section]
key = value
key_tanpa_value
```

- Header tiga baris komentar, lalu satu baris kosong, lalu section.
- Setiap entri ditulis `key = value`, atau `key` saja untuk key tanpa value.
- Urutan section dan key = urutan kemunculan pertama. Override tidak memindahkan posisi.
- Satu baris kosong antar section; file diakhiri tepat satu newline.
- Header tanpa timestamp, tanpa hostname controller, tanpa path absolut.

## Contoh

Semua contoh memakai base (hasil render `tera.cnf.j2`) berikut:

```ini
[mysqld]
max_connections = 500
skip_name_resolve

[galera]
wsrep_on = ON
```

### CC-01 — global dan per host

Input `mariadb/my.cnf`:

```ini
[mysqld]
max-connections = 1000
innodb_io_capacity = 2000
```

Input `mariadb/db01/my.cnf`:

```ini
[mysqld]
innodb_io_capacity = 4000

[mariadb]
log_warnings = 3
```

Output db01:

```ini
# Managed by Tera - JANGAN edit manual
# Ubah lewat custom config: config/mariadb/
# Sources: role:tera.cnf.j2, mariadb/my.cnf, mariadb/db01/my.cnf

[mysqld]
max_connections = 1000
skip_name_resolve
innodb_io_capacity = 4000

[galera]
wsrep_on = ON

[mariadb]
log_warnings = 3
```

Output db02 (tidak punya file per host):

```ini
# Managed by Tera - JANGAN edit manual
# Ubah lewat custom config: config/mariadb/
# Sources: role:tera.cnf.j2, mariadb/my.cnf

[mysqld]
max_connections = 1000
skip_name_resolve
innodb_io_capacity = 2000

[galera]
wsrep_on = ON
```

### CC-02 — menghapus key

Input `mariadb/my.cnf`:

```ini
[mysqld]
skip_name_resolve = __remove__
```

Output:

```ini
# Managed by Tera - JANGAN edit manual
# Ubah lewat custom config: config/mariadb/
# Sources: role:tera.cnf.j2, mariadb/my.cnf

[mysqld]
max_connections = 500

[galera]
wsrep_on = ON
```

### CC-03 — normalisasi key (lowercase dan `-`)

Input `mariadb/my.cnf`:

```ini
[mysqld]
Max-Connections = 800
```

Output (`Max-Connections` dinormalisasi menjadi `max_connections`, sehingga meng-override key base
di posisi semula, bukan menambah key baru):

```ini
# Managed by Tera - JANGAN edit manual
# Ubah lewat custom config: config/mariadb/
# Sources: role:tera.cnf.j2, mariadb/my.cnf

[mysqld]
max_connections = 800
skip_name_resolve

[galera]
wsrep_on = ON
```

### CC-04 — key duplikat dalam satu file

Input `mariadb/my.cnf`:

```ini
[mysqld]
max_connections = 600
max_connections = 700
```

Output:

```ini
# Managed by Tera - JANGAN edit manual
# Ubah lewat custom config: config/mariadb/
# Sources: role:tera.cnf.j2, mariadb/my.cnf

[mysqld]
max_connections = 700
skip_name_resolve

[galera]
wsrep_on = ON
```

### CC-05 — value dengan tanda kutip dan `=`

Input `mariadb/galera.cnf`:

```ini
[galera]
wsrep_provider_options = "gcache.size=2G; gcs.fc_limit=256"
```

Output:

```ini
# Managed by Tera - JANGAN edit manual
# Ubah lewat custom config: config/mariadb/
# Sources: role:tera.cnf.j2, mariadb/galera.cnf

[mysqld]
max_connections = 500
skip_name_resolve

[galera]
wsrep_on = ON
wsrep_provider_options = "gcache.size=2G; gcs.fc_limit=256"
```

### CC-06 — key sebelum section

Input `mariadb/bad.cnf`:

```ini
max_connections = 1000

[mysqld]
skip_name_resolve
```

Output: **error**, tidak ada file yang ditulis. Pesan error menyebut path relatif file, mis.:

```
mariadb/bad.cnf: line 1: key 'max_connections' found before any [section] header
```

### CC-07 — section kosong

Input `mariadb/client.cnf`:

```ini
[client]
# belum ada isi
```

Output (section `[client]` tidak ditulis):

```ini
# Managed by Tera - JANGAN edit manual
# Ubah lewat custom config: config/mariadb/
# Sources: role:tera.cnf.j2, mariadb/client.cnf

[mysqld]
max_connections = 500
skip_name_resolve

[galera]
wsrep_on = ON
```

### CC-08 — tanpa custom config

Input: tidak ada file di `config/mariadb/`.

Output:

```ini
# Managed by Tera - JANGAN edit manual
# Ubah lewat custom config: config/mariadb/
# Sources: role:tera.cnf.j2

[mysqld]
max_connections = 500
skip_name_resolve

[galera]
wsrep_on = ON
```

### CC-09 — determinisme

Input yang sama (isi file dan path relatif terhadap `tera_config_dir`) harus menghasilkan output yang
**byte-identik**, termasuk jika repo/inventory berada di path absolut yang berbeda
(mis. `/home/a/tera/inventory/prod-a` vs `/srv/tera/inventory/prod-a`) dan jika dijalankan berulang.
Contoh: input CC-01 dari dua lokasi berbeda menghasilkan output db01 yang sama persis dengan output CC-01.

### CC-10 — value kosong

Input `mariadb/my.cnf`:

```ini
[mysqld]
init_connect =
```

Output (`init_connect = ` adalah string kosong, berbeda dari key tanpa value; perhatikan spasi setelah `=`):

```ini
# Managed by Tera - JANGAN edit manual
# Ubah lewat custom config: config/mariadb/
# Sources: role:tera.cnf.j2, mariadb/my.cnf

[mysqld]
max_connections = 500
skip_name_resolve
init_connect = 

[galera]
wsrep_on = ON
```

## Keterbatasan (untuk user)

- Opsi yang dalam MariaDB boleh berulang (mis. `plugin_load_add`) akan tergabung menjadi satu; yang terakhir menang.
  Gabungkan nilainya secara manual jika perlu.
- `!include` dan `!includedir` tidak didukung.
- `[DEFAULT]` diperlakukan sebagai section biasa.

## Integrasi dengan reconfigure

- Jika `99-tera.cnf` berubah, node ditandai `mariadb_restart_required: true` dan di-restart oleh play rolling restart.
- `tera reconfigure --check --diff` menampilkan diff tanpa mengubah apa pun.
  **Peringatan:** diff bisa menampilkan `wsrep_sst_auth` (password SST).
- Perubahan di `config/mariadb/<host>/` hanya me-restart host tersebut.

## HAProxy dan Keepalived

- `config/haproxy/haproxy.cfg` custom = pengganti penuh template role (tetap dirender sebagai Jinja2).
- `config/haproxy/conf.d/*.cfg` di-append ke `haproxy.cfg` dengan urutan alfabetis.
- `config/keepalived/keepalived.conf` custom = pengganti penuh template role.
- Validasi sebelum ditulis: `haproxy -c -f %s` dan `keepalived -t -f %s`.
- Perubahan diterapkan dengan reload, bukan restart.
