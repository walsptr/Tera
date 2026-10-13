# 0008. Root MariaDB via unix_socket, admin remote terpisah

- **Status:** Accepted
- **Tanggal:** 2026-10-14

## Konteks

Ansible perlu akses administratif ke MariaDB di node, dan operator/aplikasi perlu akses remote. Menyimpan password root di node menambah secret yang harus dikelola.

## Keputusan

- User `root@localhost` tetap memakai autentikasi `unix_socket`; Ansible login via socket sebagai root (become).
- Akses remote memakai user admin terpisah yang passwordnya ada di `passwords.yml`.

## Alternatif yang ditolak

- **Password root**: secret tambahan di node (mis. `/root/.my.cnf`) yang harus dirotasi dan dijaga.

## Konsekuensi

- Module `ansible.mysql` dipanggil dengan `login_unix_socket`.
- Tidak ada `/root/.my.cnf` yang dikelola Tera.

## Revisi

- 2026-10-14: erratum — `community.mysql` diganti `ansible.mysql` (modul `community.mysql` kini hanya redirect deprecated); keputusan tidak berubah.
