> Versi: v1.0.0 | Status: disetujui | Menggantikan: -

# 40-TECHSTACK — titeny-data-pipeline

Mengacu: Titeny-TownHall v1.0.0 (`https://github.com/Coding-Skuy/Titeny-TownHall/tree/main/platform/versions/v1.0.0`). Stack pengikat divisi: [`FSD/30-kontrak.md`](https://github.com/Coding-Skuy/Titeny-TownHall/blob/main/platform/versions/v1.0.0/FSD/30-kontrak.md).

## Konteks TownHall

Stack divisi dikunci di TownHall v1.0.0: web Bun + Svelte 5 + SvelteKit 2 + TypeScript; analis-desktop KMP Windows (Kotlin, Compose Multiplatform, Navigation3); backend Rust Axum 0.8; model dan pipeline Python 3.12. Repo ini: Pipeline ingest Titeny: memvalidasi dan mengirim 11 event terkunci ke `POST /api/v1/event/masuk` secara idempoten, menjalankan retry/DLQ, rekalkulasi H-1, retensi, dan arsip dingin.

## Stack Repo Ini

| Lapisan | Pilihan | Versi target | STATUS |
|---|---|---|---|
| Bahasa | Python | 3.12 (repo `==3.12.7`) | defined |
| Validasi | pydantic, 11 skema event | 2.9.2 | defined |
| HTTP | httpx ke `POST /api/v1/event/masuk` | 0.27.2 | defined |
| ORM | sqlalchemy, DB `titeny` saja | 2.0.36 | defined |
| Pengiriman | `X-Idempotency-Key`, timeout 10 dtk, retry 3x 5/30/300 dtk, DLQ + pager | - | defined |
| Jadwal | Snapshot stok 23.00, transaksi agregat 23.30, keuangan 23.45, cuaca 05.00 WIB | - | defined |
| Arsip | JSONL gzip per `batch_id` + SHA-256, `data/arsip/manifest.csv` | retensi mentah 365 hari, agregat 3 tahun | defined |
| Uji | pytest + 11 fixture event + kirim ulang duplikat | - | defined |

## Perintah

```bash
pytest
```

## Registry 11 Event dan Kunci Idempoten

| # | `event_type` | Sumber | Kunci idempoten |
|---|---|---|---|
| 1 | `harga.diperbarui` | pasaree | `pasar_id + komoditas_id + tanggal` |
| 2 | `stok.berubah` | lumbung | `event_id` |
| 3 | `stok.snapshot_harian` | lumbung | `gudang_id + tanggal` |
| 4 | `transaksi.dibuat` | titipo | `transaksi_id` |
| 5 | `lapak.status_berubah` | pasaree | `lapak_id + occurred_at` |
| 6 | `panen.dicatat` | lumbung | `panen_id` |
| 7 | `logistik.biaya_diperbarui` | titipo/pasaree | `rute_id + berlaku_mulai` |
| 8 | `vendor.status_berubah` | titipo/pasaree | `vendor_id + occurred_at` |
| 9 | `cuaca.diperbarui` | cuaca | `kabupaten_id + tanggal` |
| 10 | `kalender.dikunci` | internal | `tahun` |
| 11 | `keuangan.ringkasan_harian` | lumbung | `tanggal` |

## Kewajiban Selaras Kode (migrasi)

Daftar `EVENT_BAKU` di `src/pipeline/events.py` masih memakai nama lama (`lumbung.stok.masuk`, `titipo.pesanan.buat`, `titeny.insight.minta`, dst.). Wajib diganti ke 11 terkunci di atas sebelum rilis; event ke-12 hanya lewat bump versi + 30 hari dual-read.

## Batasan

Dokumen ini hanya mengatur stack repo `titeny-data-pipeline`. Perubahan versi pustaka atau stack dicatat sebagai ADR baru di `docs/decisions/` dan dilaporkan ke TownHall. Titeny read-only terhadap DB sumber; satu-satunya basis tulis adalah DB `titeny`.
