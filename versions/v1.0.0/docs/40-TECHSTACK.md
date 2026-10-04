> Versi: v1.0.0 | Status: disetujui | Menggantikan: -

# 40-TECHSTACK — titeny-data-pipeline

Mengacu: Titeny-TownHall v1.0.0 (https://github.com/Coding-Skuy/Titeny-TownHall/tree/main/versions/v1.0.0).

## Konteks TownHall

Stack divisi dikunci di TownHall v1.0.0: web Bun latest + Svelte 5 + SvelteKit Kit 2 + TypeScript latest; analis-desktop KMP Windows; backend Rust axum 0.8.4; model dan pipeline Python 3.12. Repo ini adalah pipeline Python 3.12 untuk ingest 11 event idempoten.

## Stack Repo Ini

| Lapisan | Pilihan | Versi target | STATUS |
|---|---|---|---|
| Bahasa | Python | 3.12 (repo `==3.12.7`) | defined |
| Validasi | pydantic | 2.9.2 mengikuti 11 skema event | defined |
| HTTP | httpx | 0.27.2 ke `POST /api/v1/event/masuk` | defined |
| ORM | sqlalchemy | 2.0.36 ke DB `titeny` saja | defined |
| Uji | pytest + 11 fixture event | — | defined |

Aturan kirim: header `X-Idempotency-Key: <event_id>`, timeout 10 detik, retry 5/30/300 detik lalu DLQ, toleransi keterlambatan 24 jam dengan rekalkulasi H-1. Tiap batch membawa `batch_id` dan `jumlah_baris`.

## Perintah

```bash
pytest
```

## Batasan

Batasan dokumen ini: hanya stack pipeline. Dilarang menambah koneksi ke DB selain `titeny`. Perubahan tak-kompatibel menaikkan `schema_version` mayor dengan dual-read 30 hari.
