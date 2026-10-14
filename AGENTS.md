# AGENTS.md — titeny-data-pipeline

Pipeline ingest Titeny: memvalidasi dan mengirim 11 event terkunci ke `POST /api/v1/event/masuk` secara idempoten, menjalankan retry/DLQ, rekalkulasi H-1, retensi, dan arsip dingin.

## Sumber kebenaran

Semua requirement bersumber dari [Titeny-TownHall](https://github.com/Coding-Skuy/Titeny-TownHall) versi beku `v1.0.0`. Dilarang menduplikasi requirement di repo kode; requirement berubah = PR di TownHall dulu.

| Dokumen (Titeny-TownHall) | Isi |
|---|---|
| [`data/20-kontrak-event.md`](https://github.com/Coding-Skuy/Titeny-TownHall/blob/main/data/20-kontrak-event.md) | Kontrak 11 event terkunci + amplop (sumber utama) |
| [`data/10-sumber-data.md`](https://github.com/Coding-Skuy/Titeny-TownHall/blob/main/data/10-sumber-data.md) | S1-S10 dan matriks keterlacakan |
| [`platform/versions/v1.0.0/BRD/10-sumber-data.md`](https://github.com/Coding-Skuy/Titeny-TownHall/blob/main/platform/versions/v1.0.0/BRD/10-sumber-data.md) | Sumber data S1-S10 dan aturan keras |
| [`platform/versions/v1.0.0/FRD/10-fungsional.md`](https://github.com/Coding-Skuy/Titeny-TownHall/blob/main/platform/versions/v1.0.0/FRD/10-fungsional.md) | FR-001..FR-303 |
| [`platform/versions/v1.0.0/FSD/10-alur.md`](https://github.com/Coding-Skuy/Titeny-TownHall/blob/main/platform/versions/v1.0.0/FSD/10-alur.md) | Urutan ingest/hitung/tayang, jadwal job, urutan layar |
| [`platform/versions/v1.0.0/FSD/20-model-data.md`](https://github.com/Coding-Skuy/Titeny-TownHall/blob/main/platform/versions/v1.0.0/FSD/20-model-data.md) | Entitas, enum, aturan angka, retensi |
| [`platform/versions/v1.0.0/FSD/30-kontrak.md`](https://github.com/Coding-Skuy/Titeny-TownHall/blob/main/platform/versions/v1.0.0/FSD/30-kontrak.md) | Kontrak API, event, galat, stack pengikat |
| [`platform/versions/v1.0.0/SRS/40-acceptance-criteria.md`](https://github.com/Coding-Skuy/Titeny-TownHall/blob/main/platform/versions/v1.0.0/SRS/40-acceptance-criteria.md) | QA-001..QA-004 (QA gate) |
| [`KONTEKS-LINTAS-DIVISI.md`](https://github.com/Coding-Skuy/ChefGenie-TownHall/blob/main/KONTEKS-LINTAS-DIVISI.md) (ChefGenie-TownHall) | Event registry (bagian 3), satuan/ID/uang (bagian 6), metrik lintas-divisi (bagian 7) |
| [`townhall-roadmap.md`](https://github.com/Coding-Skuy/ChefGenie-TownHall/blob/main/townhall-roadmap.md) (ChefGenie-TownHall) | Epic E4 #5, batas blast radius (bagian 2), definisi selesai (bagian 6) |

Rujukan versi: `https://github.com/Coding-Skuy/Titeny-TownHall/tree/main/platform/versions/v1.0.0`.

## Tech stack terkunci

- **Python 3.12.7**; pydantic 2.9.2 (11 skema event), httpx 0.27.2 (ke `POST /api/v1/event/masuk`), sqlalchemy 2.0.36 (hanya DB `titeny`).
- Kontrak event berversi + amplop idempoten (`event_id` `evt_YYYYMMDD_NNNNNN`, `schema_version`, `source` dalam {lumbung, titipo, pasaree, cuaca, internal}, `occurred_at`/`received_at`, `batch_id`); header `X-Idempotency-Key: <event_id>`; timeout 10 detik; retry 3x (5/30/300 detik) lalu DLQ.
- Registry **terkunci 11 `event_type`**: `harga.diperbarui`, `stok.berubah`, `stok.snapshot_harian`, `transaksi.dibuat`, `lapak.status_berubah`, `panen.dicatat`, `logistik.biaya_diperbarui`, `vendor.status_berubah`, `cuaca.diperbarui`, `kalender.dikunci`, `keuangan.ringkasan_harian`. `pedaree.stok.v1` BUKAN bagian registry.
- Titeny read-only ke DB sumber (S1-S10). Kode kini memuat daftar event lama (`lumbung.stok.masuk`, dst.): wajib diganti ke 11 terkunci.
- **Dilarang**: event di luar 11; data pribadi (nama, alamat, telepon); INSERT/UPDATE/DELETE ke DB sumber.

Detail matriks: `versions/v1.0.0/docs/40-TECHSTACK.md`. Batas context: `versions/v1.0.0/docs/60-BLAST-RADIUS.md`.

## Aturan kerja AI

1. Baca `AGENTS.md` ini dan semua ADR di `docs/decisions/` sebelum coding.
2. TDD merah-hijau: tulis test yang gagal dulu; rilis diblokir bila QA gate gagal (QA-001..QA-004, tidak boleh skip test).
3. Kontrak API/event hanya diubah lewat bump versi + catatan di ADR baru; tidak ada `event_type` di luar 11 terkunci tanpa bump versi + dual-read 30 hari.
4. Commit memakai awalan `docs:` / `feat:` / `fix:` dan wajib memperbarui `CHANGELOG.md` repo.
5. Keputusan arsitektur baru = tambah ADR bernomor di `docs/decisions/`; jangan edit ADR lama (immutable, sama seperti aturan versi TownHall).
6. Dilarang menyentuh DB divisi lain: DB per service; Titeny read-only terhadap DB Lumbung, TitipO, dan Pasaree dan hanya menulis ke DB `titeny`.
7. Bahasa artefak: Indonesia; uang integer IDR; waktu ISO-8601 Asia/Jakarta; tanpa data pribadi di Titeny.

## Definisi selesai

Dari [`townhall-roadmap.md` bagian 6](https://github.com/Coding-Skuy/ChefGenie-TownHall/blob/main/townhall-roadmap.md):

- Dokumen versi lengkap (BRD/FRD/FSD/PRD/SRS) + `SNAPSHOT-ROADMAP.md` di TownHall; dokumen beku tidak diedit.
- QA gate berbasis SRS lulus (TDD merah-hijau, QA-001..QA-004); rilis diblokir bila gagal.
- Kontrak API terbit; audit keamanan bersih (JWT audiens `titeny` + DB per service).
- Bukti metrik lintas-divisi (KONTEKS-LINTAS-DIVISI.md bagian 7) tercatat: MAPE harga H+1 <= 8% median / H+7 <= 12%, demand H+7 <= 15%, panen <= 20%, cakupan P10-P90 70-90%.
- CHANGELOG repo dan CHANGELOG versi diperbarui.
