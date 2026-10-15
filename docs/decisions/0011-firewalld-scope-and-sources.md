# 0011. Firewalld untuk semua mode, sumber klien, dan clustercheck hanya dari load balancer

- **Status:** Supersedes 0010
- **Tanggal:** 2026-10-15 (diterima dengan tambahan: tampilan rule yang dihapus dan `tera_manage_firewall`)

## Konteks

ADR 0010 mengelola firewalld hanya di mode galera dan membuka 3306 serta 9200 untuk seluruh zona default.
Akibatnya:

- standalone di Rocky/Alma 9 dengan firewalld aktif menolak koneksi remote ke 3306;
- `tera-clustercheck` (9200) terbuka untuk siapa pun, padahal hanya HAProxy yang membutuhkannya;
- operator tidak bisa membatasi asal klien 3306 lewat Tera.

## Keputusan

- Jika service `firewalld` berjalan dan `mariadb_firewall_manage: true` (default), Tera mengelola firewalld di
  zona default untuk **kedua mode** (standalone dan galera). Tera tidak menyalakan firewalld.
- `mariadb_port` (3306/tcp) dibuka dari `mariadb_client_sources` (list CIDR/IPv4, default `["0.0.0.0/0"]`,
  yaitu tetap terbuka). Jika list berisi `0.0.0.0/0`, port dibuka untuk zona; selain itu satu rich rule per
  sumber dan port zona untuk 3306 ditutup.
- `mariadb_clustercheck_port` (9200/tcp, mode galera) hanya dari alamat node group `loadbalancer`. Group kosong
  = tidak dibuka.
- Port Galera (4567/tcp+udp, 4568/tcp, 4444/tcp) tetap hanya dari alamat node cluster (seperti ADR 0010).
- **Tera memiliki rich rule untuk port-port di atas di zona default.** Setiap deploy/reconfigure menyamakan
  rich rule port itu dengan yang diharapkan: rule dengan sumber yang tidak lagi diharapkan (sumber dihapus dari
  `mariadb_client_sources`, node keluar dari inventory, aturan lama ADR 0010) dihapus. Port zona 9200/tcp dari
  ADR 0010 ditutup. Aturan untuk port lain tidak disentuh.
- Sebelum menghapus rule miliknya, setiap host menampilkan rich rule dan port zona yang akan dihapus. Pesan
  yang sama muncul di `--check --diff`, yang tidak mengubah apa pun.
- `tera_manage_firewall` (global, default `true`): jika `false`, Tera sama sekali tidak menyentuh firewalld
  (deploy, reconfigure, destroy; role `mariadb` dan `loadbalancer`), apa pun nilai `mariadb_firewall_manage`
  atau `loadbalancer_firewall_manage`. Kedua variabel per role itu hanya mematikan satu role.
- Isi `mariadb_client_sources` divalidasi di prechecks (tidak kosong, setiap entri CIDR IPv4 valid).
- ufw tidak dikelola; prechecks memberi peringatan di kedua mode jika ufw aktif.
- Port load balancer (VIP, stats, VRRP) diputuskan bersama role `loadbalancer` di Fase 3.

## Alternatif yang ditolak

- **Catatan revisi di ADR 0010**: memperluas cakupan dan mempersempit sumber adalah perubahan keputusan,
  bukan erratum.
- **Tetap hanya mode galera**: standalone di RHEL dengan firewalld tidak bisa diakses dari luar.
- **Membiarkan rich rule lama**: sumber yang dicabut dari `mariadb_client_sources` tetap bisa terhubung.

## Konsekuensi

- Rich rule buatan tangan di zona default untuk 3306, 9200, 4567, 4568, atau 4444 akan dihapus Tera; batasi
  akses lewat `mariadb_client_sources`, atau set `tera_manage_firewall: false` untuk mengelola firewalld
  sendiri. Jalankan `--check --diff` lebih dulu untuk melihat rule yang akan dihapus.
- Upgrade dari ADR 0010: deploy/reconfigure berikutnya menutup port zona 9200/tcp.
- Uji koneksi TCP dari luar VM (host Molecule) menjadi bagian skenario `standalone` dan `galera`.

## Revisi

- 2026-10-15: dua tambahan yang menjadi syarat penerimaan ADR ini oleh pemilik proyek (bukan perubahan
  keputusan setelah diterima): rule yang akan dihapus ditampilkan saat run dan di `--check --diff`, serta
  saklar global `tera_manage_firewall`.
