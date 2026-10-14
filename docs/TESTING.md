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
| `standalone`, `standalone-podman` | service aktif; login admin via TCP; user anonymous & database `test` tidak ada; header Tera ada di `99-tera.cnf`; config per host aktif. Side effect (ADR 0009): run `--check` tidak menulis restart pending marker; run yang terputus setelah config ditulis meninggalkan marker dan config belum aktif; `converge` berikutnya me-restart, config aktif, marker hilang |
| `galera` (3 node, LB colocated) | cluster size 3; semua Synced; marker ada; tulis di node 1 terbaca di node 3; login via VIP; clustercheck 200 |
| `reconfigure` | config global aktif di semua node dengan restart berurutan; config per host hanya me-restart host itu; run ulang tanpa restart |
| `recover` | `kill -9` semua node → deploy FAIL dengan pesan recover → `tera recover` → size 3, data yang sudah commit utuh |
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
- [ ] Power off semua node → `tera recover`
- [ ] `tera recover -e mariadb_recover_from=<host>`
- [ ] Dua cluster dengan hostname sama tidak tertukar (fact cache per cluster)
- [ ] `tera destroy` lalu deploy ulang
