# Testing

## Level

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

| Skenario | Verify |
|---|---|
| `standalone` | service aktif; login admin via TCP; user anonymous & database `test` tidak ada; header Tera ada di `99-tera.cnf` |
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
