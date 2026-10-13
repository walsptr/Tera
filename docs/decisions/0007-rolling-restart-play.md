# 0007. Rolling restart lewat play serial: 1, bukan handler

- **Status:** Accepted
- **Tanggal:** 2026-10-14

## Konteks

Handler Ansible berjalan di semua host secara paralel di akhir play. Untuk Galera, me-restart semua node bersamaan menghilangkan quorum.

## Keputusan

- Restart MariaDB hanya lewat play rolling restart: `serial: 1`, `max_fail_percentage: 0`, hanya node dengan `mariadb_restart_required`, menunggu port dan (galera) Synced sebelum node berikutnya.
- HAProxy dan Keepalived boleh memakai handler karena hanya reload.

## Alternatif yang ditolak

- **Handler untuk restart MariaDB**: semua node restart bersamaan, quorum hilang.

## Konsekuensi

- Flag `mariadb_restart_required` harus di-set oleh task config dan di-reset setelah restart sukses.
- Kegagalan satu node menghentikan rolling restart; node lain tidak disentuh.
