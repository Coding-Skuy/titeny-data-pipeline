# titeny-data-pipeline

Pipa data **inti** divisi **Titeny (AI Insight)**, org **Coding-Skuy**. Tugasnya ingest dari **Lumbung, TitipO, Pasaree** dengan **11 event baku**.

Ekosistem: [Titeny-TownHall](https://github.com/Coding-Skuy/Titeny-TownHall).

## 11 event baku

1. `lumbung.stok.masuk`
2. `lumbung.stok.keluar`
3. `lumbung.panen.catat`
4. `lumbung.harga.perbarui`
5. `titipo.pesanan.buat`
6. `titipo.pesanan.antar`
7. `titipo.pesanan.batal`
8. `pasaree.lapak.buka`
9. `pasaree.transaksi.bayar`
10. `pasaree.ulasan.kirim`
11. `titeny.insight.minta`

## Prasyarat (versi dipin)

- Python 3.12.7
- pydantic 2.9.2
- httpx 0.27.2
- sqlalchemy 2.0.36

## Cara jalan

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m pipeline.ingest_lumbung --sumber contoh.json
python -m pipeline.ingest_titipo --sumber contoh.json
python -m pipeline.ingest_pasaree --sumber contoh.json
```

Setiap ingest memvalidasi event lalu meneruskannya ke `POST /ingest/event` milik `titeny-backend-service`.
