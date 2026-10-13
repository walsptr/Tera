# Custom config cluster

Spesifikasi lengkap: `docs/CUSTOM-CONFIG.md`.

- `mariadb/*.cnf` — berlaku untuk semua node MariaDB.
- `mariadb/<inventory_hostname>/*.cnf` — hanya untuk host tersebut (menang atas global).
- Hanya file berakhiran `.cnf` yang dibaca. File `*.cnf.example` di sini hanya contoh;
  salin menjadi `.cnf` untuk mengaktifkannya.
- Setiap file dirender sebagai Jinja2 untuk host target.
- Terapkan dengan `./tera reconfigure -i inventory/<cluster>` (pratinjau: tambahkan `--check --diff`).
