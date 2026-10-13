# 0009. Restart pending marker

- **Status:** Accepted
- **Tanggal:** 2026-10-14

## Konteks

`mariadb_restart_required` hanya hidup di memori satu run `ansible-playbook`. Jika run gagal atau
terputus setelah `99-tera.cnf` ditulis tetapi sebelum rolling restart, run berikutnya melihat file
sudah sama (tidak `changed`) sehingga tidak ada restart, dan config baru tidak pernah aktif tanpa
ada yang menyadarinya.

## Keputusan

- Marker persisten di node: `{{ tera_state_dir }}/mariadb-restart-pending` (default
  `/etc/tera/mariadb-restart-pending`), di `/etc/tera` sesuai aturan state Tera (bukan di datadir).
- `config.yml` mendeteksi perubahan dulu dengan `copy` `check_mode: true`. Jika `99-tera.cnf` akan
  berubah, marker ditulis **sebelum** file config ditulis. Pada run `--check`, marker tidak ditulis.
- Restart dijalankan jika `mariadb_restart_required` true **atau** marker ada. Marker dibaca di
  `config.yml` (action `deploy`/`reconfigure`) dan digabung ke flag; action `prechecks` tidak pernah
  me-restart.
- Marker dihapus hanya setelah restart sukses: port terbuka dan, untuk galera, node Synced.
- Jalur yang menyalakan service dengan config terbaru (start pertama standalone; nanti bootstrap/join
  galera) juga menghapus marker.
- Restart tetap hanya lewat play rolling restart (ADR 0007).

## Alternatif yang ditolak

- **Flag di memori saja**: perubahan config bisa "hilang" setelah run gagal.
- **Menyimpan flag di fact cache controller**: cache bisa dihapus, berbeda antar operator/controller,
  dan tidak mencerminkan state node.
- **Membandingkan waktu start service dengan mtime config**: rapuh (jam, restart manual, `touch`)
  dan sulit dijelaskan ke operator.

## Konsekuensi

- Run yang terputus di tengah selalu dilanjutkan dengan restart pada run `deploy`/`reconfigure` berikutnya.
- Perubahan metadata saja pada `99-tera.cnf` (owner/mode diubah manual) juga memicu restart.
- Operator bisa melihat node yang menunggu restart dengan memeriksa marker.
