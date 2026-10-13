# 0001. Satu cluster satu folder inventory

- **Status:** Accepted
- **Tanggal:** 2026-10-14

## Konteks

Tera harus bisa mengelola banyak cluster dari satu repo. Variabel satu cluster tidak boleh bocor ke cluster lain, hostname bisa sama antar cluster, dan user harus bisa meng-override default tanpa melawan precedence Ansible.

## Keputusan

- Satu cluster = satu folder `inventory/<cluster>/` (pola kubespray); cluster baru dibuat dengan `tera new-cluster <nama>`.
- Default global ditaruh di role `tera_defaults` (hanya `defaults/main.yml`) yang dimuat di setiap play, sehingga `group_vars` inventory user selalu menang.
- Fact cache per cluster: CLI meng-export `ANSIBLE_CACHE_PLUGIN_CONNECTION=inventory/<cluster>/.facts_cache`.

## Alternatif yang ditolak

- **Satu inventory multi-group** untuk semua cluster: variabel mudah bocor antar cluster dan `--limit` rawan salah sasaran.
- **Default di `playbooks/group_vars/`**: precedence-nya lebih tinggi dari `group_vars` inventory, sehingga menimpa nilai user.

## Konsekuensi

- Setiap play wajib memuat role `tera_defaults`.
- Nilai yang dibutuhkan host lain harus di-`set_fact` (role defaults tidak terlihat via `hostvars`).
- Dua cluster dengan hostname sama aman karena cache terpisah.
