# Testing

## Level

Alat pengembangan dipasang lokal di `.venv/` dan `collections/` (langkah lengkap di `AGENTS.md`,
bagian "Setup lingkungan dev"). CI (`.github/workflows/ci.yml`) menjalankan
lint, syntax-check, dan pytest.

| Level | Perintah | Kapan |
|---|---|---|
| Lint | `ansible-lint`, `yamllint .`, `shellcheck tera`, `ruff check plugins/` | setiap perubahan |
| Syntax-check | `ansible-playbook -i inventory/sample/hosts.yml <playbook> --syntax-check` untuk `site.yml`, `playbooks/mariadb-recover.yml`, `playbooks/destroy.yml` | setiap perubahan |
| Unit | `pytest plugins/` | setiap perubahan di `plugins/` |
| Molecule | `molecule test -s <scenario>` | perubahan role/playbook |
| Lab manual | checklist di bawah | sebelum rilis |

## Unit test

- Satu test per contoh `CC-xx` di `docs/CUSTOM-CONFIG.md`; nama test menyebut ID-nya (mis. `test_cc01_global_and_host`).
- Test determinisme (input sama → output byte-identik, termasuk dari path repo berbeda).
- Test pesan error (path relatif file disebut, langkah perbaikan jelas).
- `tera_backup.py` (`plugins/tests/test_tera_backup.py`): rantai sah (LSN bersambung, urutan), pilihan backup
  berikutnya (incremental jatuh ke full tanpa rantai utuh atau setelah restore), retensi per jumlah rantai (tidak
  menghapus tanpa pengganti, rantai rusak tidak dihitung), resolusi id backup, parser `CHECK TABLE`.

## Molecule

- Memakai **VM dengan systemd penuh** (Vagrant/libvirt atau Incus), bukan Docker biasa.
- Matriks platform: Ubuntu 22.04, Ubuntu 24.04, Rocky Linux 9 (AlmaLinux 9 opsional).
- Setiap skenario: converge → idempotence (`changed=0`) → verify.
- Driver: `vagrant` + provider `libvirt` (`molecule-plugins[vagrant]` ada di `requirements-dev.txt`;
  `vagrant` dan plugin `vagrant-libvirt` dipasang terpisah di host).
- `vagrant` harus bisa memuat plugin `vagrant-libvirt` (`vagrant plugin list` harus menampilkannya).
  Vagrant dari HashiCorp memakai Ruby sendiri dan tidak melihat paket distro seperti `vagrant-libvirt`
  dari Fedora; pasang plugin lewat `vagrant plugin install vagrant-libvirt` atau pakai paket `vagrant` distro.
- Host Fedora (terverifikasi di Fedora 44: `vagrant` 2.3.4 + `vagrant-libvirt` 0.11.2 dari repo Fedora):
  - Jika repo HashiCorp terpasang, exclude paket vagrant agar tidak tertimpa saat update:
    `sudo dnf config-manager setopt hashicorp.excludepkgs='vagrant*'`. Cek: `dnf repoquery vagrant`
    hanya menampilkan repo `fedora`/`updates`, dan `vagrant plugin list` menampilkan `(system)`.
  - Paket `vagrant-libvirt` Fedora memakai `qemu:///session` secara default; VM tidak mendapat IP yang
    bisa dibaca Vagrant. Skenario Molecule memaksa `qemu:///system` lewat
    `provider_options: {qemu_use_session: false}`. User harus bisa menjalankan
    `virsh -c qemu:///system list` tanpa sudo (grup `libvirt`).
  - Firewall host harus mengizinkan DHCP/DNS dari bridge libvirt. firewalld (default Fedora) sudah
    menangani ini lewat zona `libvirt`. `iptables-services` dengan ruleset bawaan (`REJECT` di akhir
    chain INPUT) memblokir DHCP: VM boot tetapi tidak pernah mendapat IP dan `vagrant up` timeout.
  - dnsmasq libvirt meneruskan DNS ke resolver host. Di sebagian jaringan (terlihat 2026-10-16 di satu Wi-Fi),
    resolver itu tidak menjawab dari libvirt, sehingga `dnf`/`apt` di VM gagal dengan "Could not resolve
    host" walaupun VM punya koneksi IP. Cek dari host: `dig @<resolver> mariadb.org`. Workaround lab saja,
    di VM yang sudah dibuat (bukan bagian role atau skenario):
    `nmcli con mod "<koneksi eth0>" ipv4.ignore-auto-dns yes ipv4.dns 1.1.1.1 && nmcli con up "<koneksi eth0>"`
    (Rocky), lalu jalankan `molecule converge` lagi.
  - Docker di host yang sama memasang policy `FORWARD DROP` di iptables. VM tetap mendapat IP dan bisa
    ping gateway `192.168.121.1`, tetapi trafik keluar di-drop: task repo MariaDB gagal dengan
    "Could not fetch signed_by key" / "Network is unreachable" atau timeout. Izinkan jaringan manajemen
    vagrant-libvirt lewat chain `DOCKER-USER`:
    `sudo iptables -I DOCKER-USER -s 192.168.121.0/24 -j ACCEPT` dan
    `sudo iptables -I DOCKER-USER -d 192.168.121.0/24 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT`.
    Perintah `iptables` saja hilang setelah reboot; di lab pemilik kedua aturan dibuat permanen lewat service
    systemd `libvirt-docker-forward` yang memasangnya setelah `docker.service` start.
  - vagrant-libvirt 0.11 memakai `virtual_size` dari `metadata.json` box sebagai ukuran disk VM. Box
    Rocky 9.8 menulis `5` padahal image-nya 10 GiB, sehingga disk terpotong dan guest jatuh ke dracut
    emergency mode (tidak pernah mendapat IP). Skenario memaksa `machine_virtual_size: 10`; box dengan
    image lebih besar tetap memakai ukurannya sendiri.
  - Vagrant 2.4 menyimpan box di `~/.vagrant.d/boxes/<nama>/<versi>/<arch>/libvirt`, Vagrant 2.3 di
    `.../<versi>/libvirt`. Setelah pindah versi, `vagrant box list` bisa kosong; pindahkan folder
    `libvirt` ke level yang sesuai atau tambahkan ulang box-nya.
- Skenario single-node (`standalone`) menjalankan satu VM per run; OS dipilih lewat variabel `TERA_BOX*`.

#### Box Vagrant (libvirt, dipin)

Diverifikasi dengan `vagrant box add --provider libvirt` pada 2026-10-14. Utamakan box resmi vendor.

| OS | Box | Versi / pin | Catatan |
|---|---|---|---|
| Ubuntu 22.04 | `cloud-image/ubuntu-22.04` | `20260926.0.0` | Canonical tidak menerbitkan box libvirt; box ini dibangun dari cloud image resmi Ubuntu |
| Ubuntu 24.04 | `cloud-image/ubuntu-24.04` | `20260926.0.0` | sama seperti di atas |
| Rocky Linux 9 | `rockylinux/9.8-20260525` via `box_url` resmi `dl.rockylinux.org` | nama file bertanggal + SHA256 | box `rockylinux/9` di Vagrant Cloud: v6.0.0 (9.6) 404 karena file dipindah ke vault, v5.0.0 (9.5) masih bisa diunduh. Saat 9.9 rilis, URL di bawah pindah ke `https://dl.rockylinux.org/vault/rocky/9.8/images/x86_64/` |
| AlmaLinux 9 (opsional) | `almalinux/9` | `9.8.20260907` | box resmi AlmaLinux; checksum SHA256 diverifikasi Vagrant saat `box add`. Tidak dijalankan secara default |

Uji VM penuh keluarga EL9 diwakili Rocky Linux 9; AlmaLinux 9 diuji di `standalone-podman` (lokal dan CI)
dan hanya opsional di VM.

```bash
# Matriks default
TERA_BOX=cloud-image/ubuntu-22.04 TERA_BOX_VERSION=20260926.0.0 molecule test -s standalone
TERA_BOX=cloud-image/ubuntu-24.04 TERA_BOX_VERSION=20260926.0.0 molecule test -s standalone
TERA_BOX=rockylinux/9.8-20260525 TERA_BOX_VERSION= \
  TERA_BOX_URL=https://dl.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-Vagrant-Libvirt-9.8-20260525.0.x86_64.vagrant.libvirt.box \
  TERA_BOX_CHECKSUM=cb00248ee045fa24070d78820a5b5c8e549141b7a652166ffdbfea4924b37f9b TERA_BOX_CHECKSUM_TYPE=sha256 \
  molecule test -s standalone
# Opsional
TERA_BOX=almalinux/9 TERA_BOX_VERSION=9.8.20260907 molecule test -s standalone
```

**Memperbarui pin Rocky saat minor baru rilis** (mis. 9.9). Begitu rilis, file lama pindah ke
`https://dl.rockylinux.org/vault/rocky/9.<lama>/images/x86_64/` dan URL di atas 404:

1. Lihat `https://dl.rockylinux.org/pub/rocky/9/images/x86_64/` dan pilih
   `Rocky-9-Vagrant-Libvirt-9.<baru>-<tanggal>.0.x86_64.vagrant.libvirt.box` (nama bertanggal, bukan `latest`).
2. Ambil SHA256-nya dari file `CHECKSUM` di direktori yang sama.
3. `vagrant box add --provider libvirt --name rockylinux/9.<baru>-<tanggal> <url>` untuk verifikasi.
4. Perbarui tabel dan perintah di atas (`TERA_BOX`, `TERA_BOX_URL`, `TERA_BOX_CHECKSUM`), jalankan
   `molecule test -s standalone`, lalu commit. Box lama boleh dihapus dengan `vagrant box remove`.
- Password test dibuat saat run di direktori ephemeral Molecule (tidak ada secret di repo).

### Skenario 3 node (`galera`, `reconfigure`, `recover`, `loadbalancer`, `destroy`, `backup-galera`, `upgrade`)

- Tiga VM `db01`..`db03`, masing-masing 2 vCPU dan **1536 MiB** RAM (total sekitar 5 GiB termasuk overhead
  QEMU), disk overlay 5–7,5 GiB per run. OS dipilih dengan variabel `TERA_BOX*` yang sama seperti
  `standalone`.
- **Jangan pernah menjalankan dua skenario 3 node bersamaan.**
- Matriks lokal: loop pengembangan di Ubuntu 24.04; sebelum mencentang item, `galera` di Ubuntu 22.04,
  Ubuntu 24.04, dan Rocky 9 (berurutan); `reconfigure` dan `recover` di Ubuntu 24.04 dan Rocky 9 (satu per
  keluarga OS, Rocky untuk SELinux). AlmaLinux 9 opsional. Skenario ini tidak dijalankan di CI.
- `backup` (2 VM: db01 2 GiB + bk01 768 MiB) dan `backup-galera` (3 node) di Ubuntu 24.04 dan Rocky 9; `backup`
  juga di Ubuntu 22.04. `backup` boleh berjalan bersamaan dengan satu skenario 3 node hanya jika RAM host cukup.
- `upgrade` (3 node, topologi `loadbalancer`) di Ubuntu 24.04 dan Rocky 9. Versi awal dari archive upstream lewat
  `TERA_UPGRADE_FROM` (default `11.4.11`); targetnya patch terbaru di repo normal.

```bash
TERA_BOX=cloud-image/ubuntu-24.04 TERA_BOX_VERSION=20260926.0.0 molecule test -s galera
```

### `standalone-podman` (pelengkap cepat)

Skenario `standalone-podman` menjalankan playbook yang sama (`molecule/shared/`) di container podman
rootless dengan systemd, image dibangun sendiri dari `molecule/standalone-podman/Dockerfile.j2`.
Ini **pelengkap cepat, bukan pengganti VM**: Galera, Keepalived, sysctl, dan SELinux tetap wajib diuji
di VM. Juga dijalankan di CI (job `molecule-podman`).

```bash
for image in docker.io/library/ubuntu:22.04 docker.io/library/ubuntu:24.04 \
             docker.io/rockylinux/rockylinux:9 docker.io/library/almalinux:9; do
  TERA_PODMAN_IMAGE=$image molecule test -s standalone-podman
done
```

Skenario `upgrade-podman` (standalone, image yang sama, juga di CI) memasang `TERA_UPGRADE_FROM` lalu
menjalankan `tera upgrade` dua kali: ke patch eksplisit yang lebih lama dari patch terbaru (`TERA_UPGRADE_TO`,
default `11.4.12`), lalu ke `latest`. Repo normal MariaDB hanya menyimpan beberapa patch terakhir (2026-10-17:
11.4.12 dan 11.4.13). Jika `TERA_UPGRADE_TO` hilang dari repo, run gagal dengan "versi target tidak tersedia di
repo"; naikkan `TERA_UPGRADE_FROM` dan `TERA_UPGRADE_TO` (dan default di `molecule/upgrade*/`) ke dua patch
terakhir yang masih ada, dengan `TERA_UPGRADE_FROM` di bawah keduanya.

Catatan: podman rootless menyalin IP host ke setiap container, sehingga skenario multi-node tidak bisa
memakai pola ini.

### Skenario

Playbook converge/verify/prepare dipakai bersama di `molecule/shared/`.

| Skenario | Verify |
|---|---|
| `standalone`, `standalone-podman` | service aktif; (vagrant) koneksi TCP ke 3306 dari host Molecule (luar VM) membaca greeting MariaDB; login admin via TCP; user anonymous & database `test` tidak ada; header Tera ada di `99-tera.cnf`; config per host aktif. Side effect: (pengaman datadir) MariaDB dihentikan, datadir diganti direktori kosong, `deploy` gagal dengan pesan cek mount/disk dan direktori tetap kosong, datadir dikembalikan; (ADR 0011, vagrant + firewalld) `deploy` dengan `mariadb_client_sources` terbatas dan `tera_manage_firewall=false` tidak menyentuh firewalld (host tetap terhubung); dengan pengelolaan aktif host ditolak; `deploy --check --diff` kembali ke sumber default menampilkan rule yang akan dihapus tanpa mengubah apa pun (host tetap ditolak); `converge` berikutnya memulihkan; (ADR 0009) run `--check` tidak menulis restart pending marker; run yang terputus setelah config ditulis meninggalkan marker dan config belum aktif; `converge` berikutnya me-restart, config aktif, marker hilang; (`standalone-podman`, `mariadb_backup_enabled: true`, juga di CI) `tera backup`, baris baru, `tera backup --incremental`, tabel di-drop, `tera restore latest` mengembalikan semua baris |
| `galera` (3 node) | fresh bootstrap; cluster size 3; semua Synced dan Primary; marker ada; tidak ada restart pending marker; `98-tera-sst.cnf` `0640 root:mysql`; `99-tera.cnf` punya `[galera]` dan tidak berisi secret; tulis di db01 terbaca di db03; login admin via TCP; `tera-clustercheck` 200 di setiap node; idempotence `changed=0`. Rocky: aturan firewalld (ADR 0011: 3306 terbuka, 9200 tidak terbuka untuk zona dan ditolak dari host, port Galera hanya dari node) dan tanpa denial SELinux untuk `mysqld_t`. Dari host: 3306 membaca greeting MariaDB. Side effect: (1) prechecks menolak node kurang dari minimal, `deploy --limit`, password SST kosong, dan `wsrep_sst_auth` di custom config (run `ansible-playbook` terpisah, pesan di-assert); (2) db02 di-stop (clustercheck db02 503, socket tetap menjawab), `deploy` me-join db02 tanpa bootstrap ulang dan tanpa me-restart db01/db03; `wsrep_desync=ON` di db03 → clustercheck 503, `OFF` → 200; (3) db03 di-stop dan marker-nya dihapus: `deploy` ditolak pengaman SST (menyebut db03 dan database `app`), lalu `deploy -e mariadb_galera_allow_sst_overwrite=true` me-join db03; (4) pengaman datadir: datadir db02 dikosongkan (marker datadir ada) → `deploy` gagal dengan pesan mount/disk, datadir db02 tetap kosong (tidak diisi SST), db01/db03 tetap Primary dengan size 2; datadir dikembalikan → `deploy` me-join db02. Login via VIP dan backend HAProxy diverifikasi di Fase 3 |
| `reconfigure` | config global (`wait_timeout`) aktif di semua node; selama rolling restart monitor di setiap node (`tera-monitor.sh`, sampel 0,2 detik) membuktikan setiap sampel Synced adalah Primary dengan size ≥ 2, setiap detik ada node Synced dengan size ≥ 2, setiap node tepat satu kali down, tidak tumpang tindih, urutan db01 → db02 → db03 (`check_rolling.py`); config per host (`db02`) hanya me-restart db02; run ulang `changed=0` tanpa restart |
| `recover` | prepare memasang drop-in `Restart=no` (khusus test). A: writer di db03 meng-commit baris ke db01, `kill -9` semua node → `grastate` `seqno: -1` → deploy FAIL dengan pesan recover → `tera recover` (jalur `--wsrep-recover`, seqno tertinggi) → setiap baris yang di-ack ada di semua node → deploy `changed=0`. B: stop rapi db01, db02, db03 → recover memilih db03 (`safe_to_bootstrap: 1`). C: `kill -9` lagi → recover dengan `mariadb_recover_from=db02`. Verify = verify `galera` |
| `recover-poweroff` (opsional, tidak masuk run default) | semua node di-hard-reset bersamaan (`sysrq b`) saat writer berjalan, policy restart upstream dipertahankan. Jalur yang terjadi dicatat di `poweroff-path.txt`: (i) pulih sendiri (`pc.recovery`) → deploy `changed=0`, atau (ii) tidak ada Primary → deploy FAIL dengan pesan recover → `tera recover`. Keduanya wajib tanpa kehilangan baris yang di-ack |
| `loadbalancer` (3 node, galera + HAProxy + Keepalived colocated) | jaringan privat libvirt tanpa DHCP `10.77.0.0/24` (host = `10.77.0.1`, VIP `10.77.0.100`). Verify: VIP di tepat satu node; dari host VIP:3306 membaca greeting MariaDB, stats 401 tanpa auth dan 200 dengan auth; writer via VIP = db01; config HAProxy/Keepalived (header, backup, `on-marked-up shutdown-backup-sessions`, `nopreempt`); `ip_nonlocal_bind = 1`; Rocky: rich rule 9200 dari node LB, VRRP dari peer, stats dari host, tanpa denial SELinux untuk `mysqld_t`/`haproxy_t`/`keepalived_t`; idempotence `changed=0` (prechecks tidak menolak VIP yang dipegang node LB). Side effect: prechecks menolak VIP di luar subnet, VIP yang dijawab host lain (ARP), VRID 0, `haproxy_stats_sources` tidak valid; snippet `conf.d` tidak valid ditolak `haproxy -c`, yang valid di-append; `multi_writer` (leastconn tanpa backup, login via VIP); failover dengan probe dari host tiap 0,2 detik dan monitor VIP di setiap node: writer down, writer kembali (5 sesi di backup diputus dan dihitung), haproxy di-stop, keepalived di-stop, hard reset pemegang VIP. Downtime per jenis ≤ 10 detik (angka di `failover-results.txt`), tidak pernah dua pemegang VIP, VIP tidak pindah balik saat node kembali (`nopreempt`). Rocky (firewalld): rich rule 8404 buatan tangan di db01 tetap ada setelah `deploy -e tera_manage_firewall=false`, disebut sebagai rule yang akan dihapus oleh `deploy --check --diff` (tanpa mengubah apa pun), dan hilang (runtime dan permanent) setelah deploy biasa |
| `destroy` (3 node, topologi `loadbalancer`) | playbook destroy tanpa konfirmasi ditolak, CLI tanpa flag ditolak; `--keep-data`: ringkasan menyebut database `app` dipertahankan, datadir dan marker tetap, file/service/firewall/SELinux Tera hilang; deploy gagal dengan pesan recover, `tera recover` mengembalikan data; destroy penuh (setelah `tera backup` di db03): ringkasan menyebut data ikut dihapus, datadir dan `/etc/tera` hilang, timer/unit/script backup hilang tetapi rantai backup di `mariadb_backup_dir` tetap ada, deploy membangun cluster baru tanpa data lama. Verify = verify `loadbalancer` (verify menunggu VIP melayani 3306 dari host, maks 30 detik, karena Keepalived baru memilih master sekitar 3 advert setelah start dan verify ini berjalan langsung setelah deploy) |
| `backup` (db01 standalone + bk01 host backup, 768 MiB) | prepare membuat pasangan kunci gpg test di direktori ephemeral (public key ke `config/backup/`). Side effect: deploy dengan backup mati memberi peringatan dan menghapus timer; full (A) → incremental (B, lewat unit) → incremental (C, lewat `tera backup --incremental`) → baris D; `tera backup-status`; metadata (cluster, mode, sequence, LSN bersambung, sha256, `datadir_size_bytes`); status `last`/`targets`/`verify` OK (verifikasi level 2 otomatis setelah full); bk01: 3 backup `.verified`, semua payload `.gpg`; kunci node tidak bisa list/read/delete/shell/`../` dan isi bk01 utuh; payload incremental dirusak → `tera backup-verify` gagal (sha256) dan restore gagal di tahap 1 tanpa me-restart MariaDB, marker hilang, timer aktif, 400 baris utuh; lock backup dipegang → `reconfigure` dengan timeout 5 s gagal dengan pesan, setelah lock lepas restart terjadi (`max_connections` 345); backup menolak selama restore marker ada; tabel di-drop → `tera restore latest`: A+B+C, checksum sama dengan saat incremental terakhir, tanpa D, login admin TCP, restart/restore marker hilang, marker datadir dan `needs-full` ada, satu `.pre-restore-*`, timer aktif; backup `--incremental` berikutnya menjadi full di rantai baru dan `needs-full` hilang; restore dari bk01 tanpa private key gagal di tahap 1 (MariaDB tidak di-restart), dengan private key full pertama → hanya A, tanpa sisa kunci sementara/keyring; dua full lagi → 2 rantai di db01 dan di bk01. ADR 0014: selama `tera backup-verify` `mariadbd` sementara hanya terlihat sebagai `mysql`; entri `tera-restore` dengan `expiry-time` lampau ditolak sshd, entri berlaku hanya bisa menulis (tidak `--delete`, tidak `../`, tidak membaca); dengan `PermitRootLogin no` dan SSH bk01 → db01 diblokir nft, restore remote gagal di tahap 1 setelah kunci dipasang (pesan login), tanpa sisa entri, MariaDB tidak di-restart, timer aktif; tanpa blokir restore remote berhasil tanpa login root; `galera_position` tidak ada di metadata. Verify: timer enabled/active dengan jadwal default, config (target, fingerprint 40 hex), host key bk01 di-pin, mode `0711` untuk direktori backup dan direktori kerja, `0700`/`0600` untuk rahasia; user `tera-restore` terkunci tanpa entri sementara; di bk01 timer aktif dan satu entri `authorized_keys` dengan `rrsync -wo -no-del`, `restrict`, `from=` alamat db01 |
| `backup-galera` (3 node, topologi `loadbalancer`) | prepare: db01 di-deploy sendirian mode standalone (inventory sementara, nama cluster sama), tabel `app.sa`, satu backup standalone; converge memigrasikannya ke galera (db01 bootstrap host). Side effect: prechecks menolak `mariadb_backup_host=db01` (writer) dan lulus dengan `mariadb_backup_allow_writer`; full + incremental di db03 sambil klien di db02 menulis lewat VIP tiap 0,1 s: 0 write gagal, writer tetap db01; verifikasi level 2 OK; `galera_position` tidak ada di metadata; restart pending marker di db02, baris C setelah backup → `tera restore latest` (sumber db03, node restore db01, dikirim dengan kunci sementara): size 3, semua Synced/Primary, A+B dengan checksum yang sama di setiap node, tanpa C, restart/restore marker hilang, marker bootstrap/datadir/`needs-full` ada, `.pre-restore-*` hanya di db01; `deploy` berikutnya tanpa task changed; `tera recover` ditolak (masih Primary); restore backup standalone tanpa `mariadb_restore_allow_mode_change` ditolak (MariaDB tidak di-restart), dengan override: `app.sa` 50 baris di 3 node, `app.g` tidak ada. Verify = verify `loadbalancer` |
| `upgrade` (3 node, topologi `loadbalancer`, backup lokal di db03; ADR 0015) | converge memasang `TERA_UPGRADE_FROM` (default 11.4.11) dari `archive.mariadb.org`; idempotence di versi lama. Side effect: prechecks menolak tanpa target, seri lain (11.8.1), tanpa backup terverifikasi, backup mati tanpa override; setelah `tera backup` dan verifikasi otomatis: backup lebih tua dari `mariadb_upgrade_max_backup_age=1`, versi yang tidak ada (11.4.99), downgrade (repo archive 11.4.10); `--check` hanya menampilkan rencana; repo node tetap repo converge dan tidak ada direktori probe tersisa. Upgrade yang controller-nya beserta semua worker-nya di-kill di db02 (worker ansible-core punya session sendiri, jadi yang di-kill seluruh pohon proses dan dipastikan tidak ada yang tersisa) (Ubuntu: setelah `policy-rc.d` Tera terpasang, Rocky: setelah drain): db02 ter-drain; Ubuntu: `policy-rc.d` Tera menjawab 0 untuk `cron`/`ssh.service` dan 101 untuk `mariadb`, `invoke-rc.d cron restart` berhasil; `deploy` berikutnya memperingatkan socket mati, lock backup tertinggal, dan (Ubuntu) `policy-rc.d` Tera, menghapusnya; tidak ada `policy-rc.d` Tera di node mana pun dan semua node UP di HAProxy semua node LB. Upgrade ke `latest` (Ubuntu: `mariadb_upgrade_info` db02 dihapus dulu sehingga `debian-start` menjalankan `mariadb-upgrade` penuh) dengan probe VIP dari host (0,2 s) dan klien di db03 yang menulis lewat VIP tiap 0,1 s dengan koneksi baru: gangguan terpanjang ≤ 10 s untuk probe dan klien, write gagal ≤ 5, urutan db02 → db03 → db01; semua node versi MariaDB dan galera-4 sama dan lebih baru, tidak ada paket versi lama, jumlah baris sama di 3 node dan di antara write sukses dan sukses + gagal, definisi `mysql.proc` (tanpa `created`/`modified`) dan `mariadb_upgrade_info` sama di semua node, size 3 Synced, tanpa `policy-rc.d`; Ubuntu db02: Tera menunggu `mariadb-upgrade` dari `debian-start` (lebih dari satu pengecekan sebelum `--force`); upgrade kedua melewati semua node tanpa restart (timestamp start sama) dan `deploy` sesudahnya tanpa task changed. Angka di `upgrade-results.json`. Verify = verify `loadbalancer` |
| `upgrade-podman` (standalone, 4 image, juga di CI) | converge `TERA_UPGRADE_FROM`; backup mati: upgrade tanpa override ditolak; `--check` dengan repo baru menampilkan rencana; keduanya tidak mengubah repo node (tidak ada direktori probe tersisa); dengan `mariadb_upgrade_allow_without_backup` ke `TERA_UPGRADE_TO` (11.4.12, bukan patch terbaru) berhasil dan semua paket MariaDB tepat di versi itu, lalu ke `latest` berhasil; Ubuntu: `policy-rc.d` asing yang mengizinkan start tidak disentuh (isinya tetap), peringatan "bukan milik Tera", paket menyalakan MariaDB dan Tera menghentikannya lagi dengan peringatan; versi baru di server dan `mariadb_upgrade_info`, tanpa paket versi lama; upgrade kedua melewati node; `deploy` sesudahnya tanpa task changed |
| `monitoring` (3 node, topologi `loadbalancer`, backup lokal di db03, sumber = host; ADR 0016) | dari host: `mysql_up 1` dan `mysql_global_status_wsrep_cluster_size 3` di setiap node, `node_load1`, `tera_backup_scheduled` 1 hanya di db03 (timestamp 0 sebelum backup pertama, node lain tanpa timestamp), HAProxy `/metrics` 401 tanpa auth dan 200 dengan user stats di setiap LB (port stats terbuka untuk host hanya lewat `tera_monitoring_sources`); di node: exporter di `tera_listen_address`, login `tera-exporter` lewat `unix_socket` berhasil dan `tera-node-exporter` ditolak MariaDB, grant persis ADR (`PROCESS`, `SLAVE MONITOR`, `SELECT` `performance_schema`, `MAX_USER_CONNECTIONS 3`), file client tanpa password, `tera-node-exporter` bisa membaca direktori textfile dan `tera_backup.prom`; Rocky: rich rule 9104/9100/8404 dari host, tanpa denial SELinux untuk exporter. Side effect: backup full di db03 terlihat di metrik; sumber tanpa host: Rocky menolak host (9104, 9100, 8404) tanpa peringatan, Ubuntu tetap menjawab dan prechecks memperingatkan "sources tidak ditegakkan" di 3 node; sumber kosong: exporter hanya di `127.0.0.1`, tidak ada rich rule exporter (Rocky), run kedua tanpa task changed; checksum salah untuk versi `mysqld_exporter` lain ditolak; `deploy` mengembalikan sumber, `deploy` kedua tanpa task changed. Verify = verify `loadbalancer` |
| `monitoring-podman` (standalone, 4 image, juga di CI) | exporter hanya di `127.0.0.1`, `mysql_up 1`, metrik backup 0 sebelum backup pertama, cek user/grant/textfile yang sama dengan `monitoring`; setelah backup full dan verifikasi level 2: timestamp sukses dan verifikasi > 0; checksum salah untuk `node_exporter` 1.12.0 ditolak, 1.12.1 tetap terpasang dan tidak ada sisa unduhan 1.12.0; `deploy` sesudahnya tanpa task changed; monitoring dimatikan: unit, binary, `/etc/tera-exporter`, direktori textfile, unduhan, user OS, dan user MariaDB hilang, `metrics_path` di config `tera-backup` kosong, run kedua tanpa task changed |
| `scale` (4 node 1280 MiB, topologi `loadbalancer` colocated, backup aktif; ADR 0017) | converge db01-db03 (db04 di group `spare`); side effect memakai inventory per tahap (`stage-four`, `stage-three`, `stage-db02`; folder tetap bernama `inventory` agar nama cluster sama). Scale out: db04 join, size 4, 4 backend UP di setiap LB. Penolakan scale-in: CLI tanpa `--yes-i-really-mean-it`, writer, `mariadb_backup_host` (db04), di bawah `mariadb_galera_min_nodes`, cluster tidak sehat (db03 mati). VIP dipindah ke db02, lalu scale in db02 dengan probe VIP dari host dan klien yang menulis lewat VIP dari db03: gangguan terpanjang ≤ 10 s, write gagal ≤ 5 (angka di `scale-in-results.json`); db02: marker removed, MariaDB/Keepalived/HAProxy/socket clustercheck mati dan disabled, tidak memegang VIP, datadir tetap; node tersisa size 3, db02 DOWN di HAProxy. Lupa menghapus dari inventory: `reconfigure` dan `deploy` ditolak dengan pesan langkah 2, cluster tidak berubah. Cluster mati di antara langkah 1 dan 2: `recover` dan `restore` ditolak (pesan: hapus dari inventory lalu jalankan lagi), `recover` tanpa db02 berhasil. Langkah 2: `reconfigure --check --diff` dan `reconfigure` menyebut "ditulis tanpa restart (scale in, ADR 0017)" di 3 node, start time MariaDB sama, tanpa restart pending marker, `wsrep_cluster_address` tanpa db02, `keepalived.conf` tanpa db02, Rocky: tidak ada rich rule untuk alamat db02; run kedua tanpa task changed. Re-add db02: tanpa flag, hanya `mariadb_scale_in_allow_readd` (pesan salinan lama + kedua flag), hanya `mariadb_galera_allow_sst_overwrite` ditolak; kedua flag: size 4, marker hilang, Keepalived/HAProxy aktif. Scale in db02 lagi, langkah 2 bersama perubahan custom config lain: rolling restart (start time berubah, `net_read_timeout` 45, tanpa marker). `tera destroy` dengan inventory yang hanya berisi db02: `/etc/tera`, datadir, config HAProxy/Keepalived, unit clustercheck hilang; cluster tetap size 3. `deploy` akhir tanpa task changed |

## Definition of done

- Lint, syntax-check, dan unit test lulus.
- Skenario Molecule yang relevan lulus, termasuk idempotence.
- `--check --diff` berjalan tanpa error.
- Dokumen di `docs/` diperbarui jika perilaku berubah.
- Item `docs/ROADMAP.md` dicentang.

## Checklist lab manual

- [ ] Deploy di setiap OS target
- [ ] Reconfigure (global dan per host)
- [ ] Failover writer (stop db01, HAProxy pindah ke backup)
- [ ] Failover VIP (stop haproxy/keepalived di master)
- [ ] Power off semua node bersamaan (bukan stop rapi), nyalakan lagi: catat apakah cluster pulih sendiri
  (`pc.recovery`, deploy `changed=0`) atau butuh `tera recover`; data yang sudah commit utuh
- [ ] `tera recover -e mariadb_recover_from=<host>`
- [ ] Dua cluster dengan hostname sama tidak tertukar (fact cache per cluster)
- [ ] `tera destroy` lalu deploy ulang
