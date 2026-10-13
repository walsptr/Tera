# 0006. Tidak ada auto bootstrap cluster lama

- **Status:** Accepted
- **Tanggal:** 2026-10-14

## Konteks

Jika semua node Galera mati, bootstrap dari node yang salah (bukan yang punya seqno tertinggi) menyebabkan kehilangan data. SST menimpa datadir, sehingga state di datadir tidak dapat diandalkan sebagai penanda.

## Keputusan

- Marker `/etc/tera/mariadb-galera.bootstrapped` ditulis setelah cluster pertama kali berhasil di-bootstrap/join.
- `deploy` hanya mem-bootstrap otomatis jika tidak ada node Primary **dan** tidak ada marker di node mana pun. Jika marker ada dan tidak ada Primary, run gagal dan mengarahkan ke `tera recover`.
- Recover adalah perintah eksplisit (`tera recover`) yang memilih node berdasarkan grastate/seqno.

## Alternatif yang ditolak

- **Auto bootstrap dari node pertama**: berisiko kehilangan data.
- **Auto recover di dalam `deploy`**: operasi berisiko tinggi tersembunyi di balik perintah rutin.

## Konsekuensi

- Operator harus menjalankan `tera recover` secara sadar setelah full outage.
- State Tera disimpan di `/etc/tera/`, bukan di datadir.
