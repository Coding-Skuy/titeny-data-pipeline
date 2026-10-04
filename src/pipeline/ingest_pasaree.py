"""Ingest Pasaree: 3 event lapak/transaksi/ulasan."""
import argparse, json
from .events import EVENT_BAKU

IZIN = [e for e in EVENT_BAKU if e.startswith("pasaree.")]

def validasi(nama: str) -> bool:
    return nama in IZIN

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sumber", required=True)
    a = p.parse_args()
    data = json.load(open(a.sumber))
    for ev in data:
        assert validasi(ev["nama"]), f"event tak dikenal: {ev['nama']}"
        print(f"OK Pasaree {ev['nama']} -> POST /ingest/event")
