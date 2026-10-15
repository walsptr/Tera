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

### Skenario 3 node (`galera`, `reconfigure`, `recover`)

- Tiga VM `db01`..`db03`, masing-masing 2 vCPU dan **1536 MiB** RAM (total sekitar 5 GiB termasuk overhead
  QEMU), disk overlay 5–7,5 GiB per run. OS dipilih dengan variabel `TERA_BOX*` yang sama seperti
  `standalone`.
- **Jangan pernah menjalankan dua skenario 3 node bersamaan.**
- Matriks lokal: loop pengembangan di Ubuntu 24.04; sebelum mencentang item, `galera` di Ubuntu 22.04,
  Ubuntu 24.04, dan Rocky 9 (berurutan); `reconfigure` dan `recover` di Ubuntu 24.04 dan Rocky 9 (satu per
  keluarga OS, Rocky untuk SELinux). AlmaLinux 9 opsional. Skenario ini tidak dijalankan di CI.

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

Catatan: podman rootless menyalin IP host ke setiap container, sehingga skenario multi-node tidak bisa
memakai pola ini.

### Skenario

Playbook converge/verify/prepare dipakai bersama di `molecule/shared/`.

| Skenario | Verify |
|---|---|
| `standalone`, `standalone-podman` | service aktif; (vagrant) koneksi TCP ke 3306 dari host Molecule (luar VM) membaca greeting MariaDB; login admin via TCP; user anonymous & database `test` tidak ada; header Tera ada di `99-tera.cnf`; config per host aktif. Side effect: (pengaman datadir) MariaDB dihentikan, datadir diganti direktori kosong, `deploy` gagal dengan pesan cek mount/disk dan direktori tetap kosong, datadir dikembalikan; (ADR 0011, vagrant + firewalld) `deploy` dengan `mariadb_client_sources` terbatas dan `tera_manage_firewall=false` tidak menyentuh firewalld (host tetap terhubung); dengan pengelolaan aktif host ditolak; `deploy --check --diff` kembali ke sumber default menampilkan rule yang akan dihapus tanpa mengubah apa pun (host tetap ditolak); `converge` berikutnya memulihkan; (ADR 0009) run `--check` tidak menulis restart pending marker; run yang terputus setelah config ditulis meninggalkan marker dan config belum aktif; `converge` berikutnya me-restart, config aktif, marker hilang |
| `galera` (3 node) | fresh bootstrap; cluster size 3; semua Synced dan Primary; marker ada; tidak ada restart pending marker; `98-tera-sst.cnf` `0640 root:mysql`; `99-tera.cnf` punya `[galera]` dan tidak berisi secret; tulis di db01 terbaca di db03; login admin via TCP; `tera-clustercheck` 200 di setiap node; idempotence `changed=0`. Rocky: aturan firewalld (ADR 0011: 3306 terbuka, 9200 tidak terbuka untuk zona dan ditolak dari host, port Galera hanya dari node) dan tanpa denial SELinux untuk `mysqld_t`. Dari host: 3306 membaca greeting MariaDB. Side effect: (1) prechecks menolak node kurang dari minimal, `deploy --limit`, password SST kosong, dan `wsrep_sst_auth` di custom config (run `ansible-playbook` terpisah, pesan di-assert); (2) db02 di-stop (clustercheck db02 503, socket tetap menjawab), `deploy` me-join db02 tanpa bootstrap ulang dan tanpa me-restart db01/db03; `wsrep_desync=ON` di db03 → clustercheck 503, `OFF` → 200; (3) db03 di-stop dan marker-nya dihapus: `deploy` ditolak pengaman SST (menyebut db03 dan database `app`), lalu `deploy -e mariadb_galera_allow_sst_overwrite=true` me-join db03; (4) pengaman datadir: datadir db02 dikosongkan (marker datadir ada) → `deploy` gagal dengan pesan mount/disk, datadir db02 tetap kosong (tidak diisi SST), db01/db03 tetap Primary dengan size 2; datadir dikembalikan → `deploy` me-join db02. Login via VIP dan backend HAProxy diverifikasi di Fase 3 |
| `reconfigure` | config global (`wait_timeout`) aktif di semua node; selama rolling restart monitor di setiap node (`tera-monitor.sh`, sampel 0,2 detik) membuktikan setiap sampel Synced adalah Primary dengan size ≥ 2, setiap detik ada node Synced dengan size ≥ 2, setiap node tepat satu kali down, tidak tumpang tindih, urutan db01 → db02 → db03 (`check_rolling.py`); config per host (`db02`) hanya me-restart db02; run ulang `changed=0` tanpa restart |
| `recover` | prepare memasang drop-in `Restart=no` (khusus test). A: writer di db03 meng-commit baris ke db01, `kill -9` semua node → `grastate` `seqno: -1` → deploy FAIL dengan pesan recover → `tera recover` (jalur `--wsrep-recover`, seqno tertinggi) → setiap baris yang di-ack ada di semua node → deploy `changed=0`. B: stop rapi db01, db02, db03 → recover memilih db03 (`safe_to_bootstrap: 1`). C: `kill -9` lagi → recover dengan `mariadb_recover_from=db02`. Verify = verify `galera` |
| `recover-poweroff` (opsional, tidak masuk run default) | semua node di-hard-reset bersamaan (`sysrq b`) saat writer berjalan, policy restart upstream dipertahankan. Jalur yang terjadi dicatat di `poweroff-path.txt`: (i) pulih sendiri (`pc.recovery`) → deploy `changed=0`, atau (ii) tidak ada Primary → deploy FAIL dengan pesan recover → `tera recover`. Keduanya wajib tanpa kehilangan baris yang di-ack |
| `loadbalancer` (3 node, galera + HAProxy + Keepalived colocated) | jaringan privat libvirt tanpa DHCP `10.77.0.0/24` (host = `10.77.0.1`, VIP `10.77.0.100`). Verify: VIP di tepat satu node; dari host VIP:3306 membaca greeting MariaDB, stats 401 tanpa auth dan 200 dengan auth; writer via VIP = db01; config HAProxy/Keepalived (header, backup, `on-marked-up shutdown-backup-sessions`, `nopreempt`); `ip_nonlocal_bind = 1`; Rocky: rich rule 9200 dari node LB, VRRP dari peer, stats dari host, tanpa denial SELinux untuk `mysqld_t`/`haproxy_t`/`keepalived_t`; idempotence `changed=0` (prechecks tidak menolak VIP yang dipegang node LB). Side effect: prechecks menolak VIP di luar subnet, VIP yang dijawab host lain (ARP), VRID 0, `haproxy_stats_sources` tidak valid; snippet `conf.d` tidak valid ditolak `haproxy -c`, yang valid di-append; `multi_writer` (leastconn tanpa backup, login via VIP); failover dengan probe dari host tiap 0,2 detik dan monitor VIP di setiap node: writer down, writer kembali (5 sesi di backup diputus dan dihitung), haproxy di-stop, keepalived di-stop, hard reset pemegang VIP. Downtime per jenis ≤ 10 detik (angka di `failover-results.txt`), tidak pernah dua pemegang VIP, VIP tidak pindah balik saat node kembali (`nopreempt`). Rocky (firewalld): rich rule 8404 buatan tangan di db01 tetap ada setelah `deploy -e tera_manage_firewall=false`, disebut sebagai rule yang akan dihapus oleh `deploy --check --diff` (tanpa mengubah apa pun), dan hilang (runtime dan permanent) setelah deploy biasa |
| `destroy` (3 node, topologi `loadbalancer`) | playbook destroy tanpa konfirmasi ditolak, CLI tanpa flag ditolak; `--keep-data`: ringkasan menyebut database `app` dipertahankan, datadir dan marker tetap, file/service/firewall/SELinux Tera hilang; deploy gagal dengan pesan recover, `tera recover` mengembalikan data; destroy penuh: ringkasan menyebut data ikut dihapus, datadir dan `/etc/tera` hilang, deploy membangun cluster baru tanpa data lama. Verify = verify `loadbalancer` (verify menunggu VIP melayani 3306 dari host, maks 30 detik, karena Keepalived baru memilih master sekitar 3 advert setelah start dan verify ini berjalan langsung setelah deploy) |
| `scale` | node ke-4 join; node lama rolling restart; backend HAProxy bertambah |

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
