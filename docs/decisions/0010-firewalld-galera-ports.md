# 0010. Tera mengelola firewalld untuk port Galera

- **Status:** Accepted
- **Tanggal:** 2026-10-14

## Konteks

Rocky Linux 9 dan AlmaLinux 9 menyalakan firewalld secara default; zona `public` hanya mengizinkan ssh,
cockpit, dan dhcpv6-client. Akibatnya joiner Galera tidak bisa menghubungi node lain di port 4567
(`No route to host`) dan gagal start. Ubuntu tidak menyalakan firewall secara default. Sebelum ADR ini,
Tera tidak punya kebijakan firewall sama sekali.

## Keputusan

- Di mode galera, jika service `firewalld` berjalan dan `mariadb_firewall_manage: true` (default), Tera
  membuka port lewat `ansible.posix.firewalld` di zona default (`permanent` dan `immediate`):
  - port replikasi Galera (4567/tcp, 4567/udp, 4568/tcp IST, 4444/tcp SST) **hanya dari alamat node
    cluster** (`tera_listen_address` setiap host group `mariadb`), lewat rich rule per alamat;
  - `mariadb_port` (3306/tcp) dan `mariadb_clustercheck_port` (9200/tcp) di zona default, karena klien dan
    HAProxy bisa berada di luar cluster.
- Jika firewalld tidak berjalan, Tera tidak menyalakannya.
- ufw tidak dikelola. Prechecks memberi peringatan jika ufw aktif, dengan port yang harus dibuka.
- Mode standalone tidak dikelola (perilaku Fase 1 tetap).

## Alternatif yang ditolak

- **Prasyarat host saja (prechecks gagal jika port tertutup)**: operator harus menyalin aturan yang sama ke
  setiap node, padahal Tera sudah tahu alamat semua node.
- **Dokumentasi saja**: error baru terlihat saat joiner gagal start, jauh dari penyebabnya.
- **Membuka port Galera untuk semua sumber**: port replikasi dan SST tidak perlu diakses dari luar cluster.

## Konsekuensi

- Rich rule untuk alamat node yang sudah dihapus dari inventory (scale in) tidak dihapus otomatis.
- Operator yang mengelola firewall sendiri bisa mematikan pengelolaan dengan `mariadb_firewall_manage: false`.
- Port HAProxy, stats, dan VRRP diputuskan di Fase 3.
