# Spike: upgrade minor MariaDB 11.4 di Galera (2026-10-16)

> Status: selesai untuk Ubuntu 24.04 dan Rocky 9. Hasilnya menjadi masukan ADR 0015.

## Lingkungan

- Topologi Molecule `loadbalancer` (3 node colocated, HAProxy `single_writer`, VIP 10.77.0.100).
- Versi awal dari archive upstream, lewat variabel role yang sudah ada:
  - Ubuntu: `molecule converge -s loadbalancer -- -e mariadb_repo_deb_url=https://archive.mariadb.org/mariadb-11.4.11/repo/ubuntu`
  - Rocky:  `molecule converge -s loadbalancer -- -e mariadb_repo_rpm_url=https://archive.mariadb.org/mariadb-11.4.11/yum/rhel/9/x86_64`
- Archive tersedia untuk 11.4.11, 11.4.12, 11.4.13 (Ubuntu noble dan EL9). Target: 11.4.13 dari mirror normal.
- Ubuntu 24.04: 11.4.11 + galera-4 26.4.26 → 11.4.13 + galera-4 26.4.27.
- Rocky 9: `MariaDB-server-11.4.11-1.el9` + `galera-4-26.4.26-1.el9` → `11.4.13-1.el9` + `26.4.27-1.el9`
  (repo dipindah ke `rpm.mariadb.org/11.4/rhel/9/$basearch`).

## Temuan Ubuntu 24.04 (paket deb)

1. **Upgrade paket me-restart MariaDB sendiri** (postinst: "Stopping ... 11.4.11", "Starting ... 11.4.13"),
   tanpa kendali Tera.
2. **Walaupun MariaDB dihentikan lebih dulu, postinst menyalakannya lagi** (db02: stop → apt upgrade →
   `active`). Dengan `/usr/sbin/policy-rc.d` (exit 101) selama upgrade, service tetap mati (db02 reinstall,
   db01 upgrade: `active=inactive`), lalu Tera menyalakan sendiri.
3. **Node kembali lewat IST**, bukan SST: `IST received`, donor `wsrep_sst_mariabackup --bypass`
   (db03: IST 17–18, db02: IST 19–20).
4. **`mariadb-upgrade` tidak berjalan otomatis** (`mariadb_upgrade_info` tetap 11.4.11 setelah upgrade paket).
   Tanpa `--force` ia menolak: "There is no need to run mariadb-upgrade again for 11.4.13-MariaDB, because
   they're both 11.4." (rc=0).
5. **Perubahan `mariadb-upgrade --force` tidak tereplikasi**: di db03 checksum tabel `mysql.*` berubah
   (6419bcec → 5d102d35) dan `mariadb_upgrade_info` → 11.4.13, tetapi `wsrep_last_committed` tetap 18 di ketiga
   node dan checksum `mysql.*` db01/db02 tidak berubah. Jadi jika diperlukan, harus dijalankan di setiap node;
   untuk patch dalam satu seri tidak diperlukan.
6. **Upgrade writer dengan drain** (stop `tera-clustercheck.socket` di db01 → HAProxy menandai DOWN, upgrade
   dengan policy-rc.d, start, tunggu Synced, `mariadb-upgrade`, start socket) sambil klien di db02 menulis lewat
   VIP setiap ~0,1 s dengan koneksi baru per write: 585 write, **0 gagal**; writer pindah ke db02 2,5 s setelah
   drain, kembali ke db01 ~2 s setelah socket dinyalakan; celah terbesar antar write sukses 1,0 s (saat db01
   menyusul lewat IST), celah saat perpindahan writer ≤ 0,2 s. Sesi yang sudah terbuka tetap diputus dua kali
   (`on-marked-down shutdown-sessions`, `on-marked-up shutdown-backup-sessions`; tidak diukur ulang di sini).
7. Endpoint Prometheus HAProxy tersedia di paket distro: EL9 HAProxy 2.8.14, Ubuntu 22.04 2.4.30, Ubuntu 24.04
   2.8.16, semuanya "Built with the Prometheus exporter as a service" (dicek di container).

## Temuan Rocky 9 (paket rpm)

1. **Upgrade paket me-restart MariaDB yang sedang berjalan**: scriptlet `postuninstall` menulis
   `/var/lib/rpm-state/mariadb/need-restart`, lalu `posttrans` menjalankan `systemctl restart` /
   `try-restart mariadb.service` (db03: MainPID 37517 → 50761, "Stopping ... Starting MariaDB 11.4.13").
2. **Berbeda dari deb: service yang dihentikan lebih dulu tetap mati** setelah upgrade (`try-restart` hanya
   me-restart yang aktif; db02 dan db01: `inactive` setelah `dnf upgrade`). Tidak perlu padanan
   `policy-rc.d`. Cabang `systemctl start mariadb` di `postinstall` hanya jalan bila
   `/etc/systemd/system/mariadb.service.d/migrated-from-my.cnf-settings.conf` belum ada; file itu dibuat saat
   instalasi pertama.
3. **Node kembali lewat IST** (pola bypass: `SST received` lalu `IST received`; donor: "mariabackup IST
   completed on donor").
4. **`mariadb_upgrade_info` hanya ada di node bootstrap** (db01: 11.4.11). db02/db03 tidak punya file itu:
   datadir mereka berasal dari SST mariabackup, yang tidak membawa file tersebut. Di node tanpa file,
   `mariadb-upgrade` berjalan penuh tanpa `--force` (rc=0) dan membuat file; run kedua menolak ("There is no
   need to run mariadb-upgrade again"). Di db01 (file 11.4.11) ia menolak seperti di Ubuntu (rc=0).
5. **Perubahan `mariadb-upgrade` tidak tereplikasi** (sama dengan Ubuntu): `wsrep_last_committed` tetap 23 di
   ketiga node; checksum `mysql.*` hanya berubah di db03, dan satu-satunya tabel yang berbeda adalah
   `mysql.proc` (rutin schema `sys` dibuat ulang).
6. **Upgrade writer dengan drain** (urutan sama dengan Ubuntu, tanpa `policy-rc.d`), klien di db02 menulis lewat
   VIP tiap ~0,1 s dengan koneksi baru per write: 569 write, **1 gagal** (`ERROR 2013 ... at 'handshake:
   reading initial communication packet'`) ~1,1 s setelah socket clustercheck db01 dinyalakan, yaitu saat
   writer kembali ke db01 dan `on-marked-up shutdown-backup-sessions` memutus koneksi yang sedang handshake
   ke db02. Writer pindah ke db02 ~1,2 s setelah drain; celah terbesar antar write sukses 0,59 s. Setelah
   selesai: 568 baris dan checksum `app.w` sama di ketiga node, cluster size 3, semua 11.4.13. Waktu dari
   jam VM (selisih antar VM < 0,3 s). Run Ubuntu 0 gagal; perbedaannya soal timing, bukan OS: klien harus
   siap me-retry koneksi saat interupsi kedua.
7. **Upgrade dapat menarik paket baru**: MariaDB-server 11.4.13 menambah Recommends `stunnel` (11.4.11:
   `MariaDB-server-compat lsof pv socat`); role memasang lewat `ansible.builtin.package` dengan weak deps
   default, sehingga `stunnel` ikut terpasang. Upgrade harus mencakup semua paket MariaDB yang terpasang
   (`MariaDB-*`, termasuk `-compat`, dan `galera-4`), bukan daftar tetap: upgrade yang hanya menyebut
   server/client/common/shared/backup meninggalkan `MariaDB-server-compat` dan `MariaDB-client-compat`
   di 11.4.11.
8. Satu `dnf upgrade` pertama di db02 gagal rc=1; output-nya tidak tersimpan, percobaan ulang langsung
   berhasil. Penyebab tidak diketahui — upgrade Tera perlu menampilkan error dnf apa adanya.

## Verifikasi lanjutan (container `standalone-podman` Ubuntu 24.04, 11.4.11 → 11.4.13)

1. **Paket deb menjalankan `mariadb-upgrade` sendiri setiap kali service start.** Unit `mariadb.service` paket
   upstream berisi `ExecStartPost=!/etc/mysql/debian-start`; skrip itu menjalankan
   `mariadb-upgrade --defaults-extra-file=/etc/mysql/debian.cnf --version-check --silent` **di background**
   (systemd tidak menunggunya), log dengan tag `/etc/mysql/debian-start` ("Upgrading MariaDB tables if
   necessary."). Diperiksa dari isi paket `mariadb-server_11.4.13+maria~ubu2404_amd64.deb` dan dari journal.
2. `mariadb_upgrade_info` dihapus lalu service di-restart: `debian-start` membuat file itu lagi (~4 s setelah
   start). Ini menjelaskan kenapa di Ubuntu file info ada di setiap node (termasuk joiner hasil SST) dan run
   manual menolak tanpa `--force`, sedangkan di Rocky joiner tidak punya file.
3. Setelah upgrade ke 11.4.13 dan restart, `debian-start` berjalan tetapi file info tetap `11.4.11-MariaDB`;
   `mariadb-upgrade` dengan atau tanpa `--version-check` menolak ("because they're both 11.4", rc=0).
4. **Perbedaan `CHECKSUM TABLE mysql.proc` hanya karena timestamp.** Sebelum dan sesudah
   `mariadb-upgrade --force`: checksum tabel berubah (3149042254 → 1920688944), `max(modified)` berubah, tetapi
   hash definisi 53 rutin (`db, name, type, md5(body), definer, sql_mode, security_type`) identik. Perbedaan
   `mysql.proc` antar node di temuan Rocky 5 karenanya bukan perbedaan definisi.
5. **Image container Ubuntu membawa `/usr/sbin/policy-rc.d` sendiri** (`exit 101`, bukan milik paket mana pun):
   di container, upgrade paket tidak me-restart MariaDB. `policy-rc.d` milik Tera tidak boleh menimpa atau
   menghapus file seperti ini.

## Implikasi untuk desain

- Selalu hentikan MariaDB sebelum upgrade paket agar restart dikendalikan Tera (bukan scriptlet). Ubuntu
  perlu `policy-rc.d` selama upgrade (kecuali sudah ada `policy-rc.d` asing); Rocky tidak.
- Join kembali lewat IST di kedua OS untuk upgrade cepat; gcache cukup untuk jeda ~1 menit di lab.
- `mariadb-upgrade` tanpa `--force` menghasilkan file info yang berbeda antar node (Rocky: node bootstrap
  tetap versi lama, joiner versi baru). Usulan Claude: `--force` di setiap node, setelah `mariadb-upgrade`
  background dari `debian-start` selesai (Ubuntu). Keputusan awal pemilik adalah tanpa `--force`; usulan ini
  disetujui pemilik pada review ADR 0015 (2026-10-16). Perbandingan `mysql.proc` antar node memakai definisi,
  bukan `CHECKSUM TABLE`.
- Lingkungan: jaringan Wi-Fi saat spike membuat dnsmasq libvirt tidak bisa meneruskan DNS; VM lab diberi
  DNS 1.1.1.1 lewat `nmcli` (tidak memengaruhi hasil, tidak dimasukkan ke role atau skenario).

Keputusan dari spike ini dicatat di ADR 0015.
