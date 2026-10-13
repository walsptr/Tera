# 0002. Custom config via merge_ini ke satu file 99-tera.cnf

- **Status:** Accepted
- **Tanggal:** 2026-10-14

## Konteks

User perlu meng-override opsi MariaDB secara global maupun per host tanpa menyentuh role, dengan hasil yang mudah dipahami dan deterministik (agar tidak memicu restart yang tidak perlu).

## Keputusan

- Custom config MariaDB ditaruh di `config/mariadb/*.cnf` dan `config/mariadb/<host>/*.cnf`.
- Filter `merge_ini` menggabungkan template role → global → per host (belakang menang) menjadi satu file drop-in `99-tera.cnf`.
- Custom file dirender sebagai Jinja2 dalam konteks host target.
- Spesifikasi lengkap di `docs/CUSTOM-CONFIG.md`.

## Alternatif yang ditolak

- **Copy file apa adanya ke `conf.d`**: hasil override tersebar di banyak file dan sulit dipahami nilai efektifnya.
- **Dict variabel per opsi** (`mariadb_config_overrides: {...}`): kurang familiar bagi DBA, dan override per host tidak natural.

## Konsekuensi

- Nilai efektif terlihat di satu file.
- Opsi berulang (mis. `plugin_load_add`) tergabung; `!include` tidak didukung.
- `merge_ini` wajib punya test untuk setiap contoh CC-xx.
