# 0014. Penerima restore khusus dan kunci sementara ber-TTL

- **Status:** Accepted, menggantikan bagian "Pengiriman backup ke node restore" di ADR 0013
- **Tanggal:** 2026-10-16

## Konteks

ADR 0013 mengirim rantai backup dari sumber (host backup atau node lain) ke node restore dengan kunci SSH
sementara yang dipasang di `authorized_keys` **root**, dibatasi `command="rrsync -wo <staging>"`, `restrict`, dan
`from=`. Review setelah Fase 4a menemukan:

- restore gagal di server yang melarang login root lewat SSH (`PermitRootLogin no`, umum di hardening CIS);
- tanpa `-no-del`, kunci itu bisa menghapus file di staging;
- tanpa `expiry-time`, kunci tertinggal tanpa batas waktu jika controller terputus sebelum blok `always`;
- tidak ada pemeriksaan dini, sehingga kegagalan login baru terlihat dari error rsync.

Terkait: `mariadbd` sementara untuk verifikasi dan restore berjalan sebagai root (ADR 0012, revisi), padahal
seharusnya sebagai `mysql`. Keduanya butuh direktori kerja yang bisa dilewati user non-root.

## Keputusan

### User penerima

- User sistem `tera-restore` (`mariadb_restore_user`) di setiap node MariaDB, dibuat saat deploy: password
  terkunci, home `/var/lib/tera-restore`, shell `/bin/sh` (sshd menjalankan forced command lewat shell user;
  shell tetap tidak interaktif karena `command=` dan `restrict`). `authorized_keys` kosong di luar restore.
- Staging restore: `<mariadb_backup_dir>/.incoming/<restore_id>/`, milik `tera-restore`, mode `0700`.

### Kunci sementara

Entri di `authorized_keys` `tera-restore` selama restore:

```
command="/usr/bin/rrsync -wo -no-del <staging>",restrict,from="<alamat sumber>",expiry-time="<waktu lokal + TTL>"
```

- `mariadb_restore_key_ttl` (detik, default `7200`). Waktu kedaluwarsa dihitung dari jam node restore, dalam
  zona waktu sistem node dan **tanpa** akhiran `Z`: OpenSSH 8.9 (Ubuntu 22.04) menolak seluruh baris kunci jika
  waktu memakai akhiran `Z` (UTC), sedangkan format lokal didukung sejak `expiry-time` ada.
- Sebelum menambah entri, entri `tera-restore-*` lama dihapus (sisa run yang terputus).
- **Cek dini:** setelah entri dipasang, sumber mencoba login dengan kunci itu. Kode keluar ssh 255 (koneksi atau
  autentikasi gagal, mis. `AllowUsers`/`AllowGroups`/`Match` di sshd, firewall) menggagalkan tahap 1 dengan pesan
  yang menyebut kemungkinan penyebab; MariaDB belum dihentikan.
- Entri dan kunci di sumber tetap dihapus di blok `always`. Jika controller terputus, entri kedaluwarsa sendiri
  dan restore berikutnya menghapusnya.

### Direktori kerja dan user `mysql`

- `mariadb_backup_dir` menjadi `0711` (bisa dilewati, tidak bisa didaftar). Induknya harus bisa dilewati:
  Tera mengelola mode `0711` untuk induk default (`/var/backups/tera`); untuk path lain prechecks menolak induk
  yang tidak bisa dilewati, dengan pesan.
- `.verify/`, `.restore/`, `.incoming/` milik root dengan mode `0711`. Direktori per run di bawahnya dimiliki
  user yang memakainya (`mysql` untuk hasil bongkar dan prepare, `tera-restore` untuk staging), mode `0700`.
- `mariadbd` sementara berjalan dengan `--user=mysql`. Isi rantai backup tetap `0700 root`.

## Alternatif yang ditolak

- **Tetap root:** gagal di server dengan `PermitRootLogin no`, dan kunci yang bocor menulis sebagai root.
- **User koneksi Ansible (`ansible_user`):** berbeda per lingkungan, sering punya sudo, dan staging harus bisa
  diakses user itu.
- **User baru yang dibuat dan dihapus per restore:** setiap restore mengubah `/etc/passwd`; user permanen yang
  terkunci lebih sederhana dan lebih mudah diizinkan di `AllowUsers`.
- **Node menarik dari host backup dengan kunci baca sementara:** node akan memegang kredensial baca untuk host
  backup (ditolak di ADR 0013).

## Konsekuensi

- Ada user permanen `tera-restore` di setiap node MariaDB. Kebijakan sshd organisasi (`AllowUsers`,
  `AllowGroups`) harus mengizinkannya agar restore dari host backup atau node lain berjalan; cek dini membuat
  kegagalan itu jelas.
- Kunci sementara tidak bisa menghapus atau menulis di luar staging, dan tidak berlaku lagi setelah TTL.
- Direktori backup bisa dilewati semua user lokal, tetapi tidak bisa didaftar; isi rantai tetap root-only.
