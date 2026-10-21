"""Ingest Pasaree: validasi berkas event (JSON array amplop) terhadap 11 skema terkunci."""

import argparse
import json

from .skema import EventDitolak, validasi_event

SUMBER = "pasaree"


def validasi_berkas(jalur: str) -> int:
    """Validasi semua event sumber ini di berkas; kembalikan jumlah yang lolos."""
    with open(jalur, encoding="utf-8") as f:
        data = json.load(f)
    lolos = 0
    for ev in data:
        if ev.get("source") != SUMBER:
            continue
        validasi_event(ev)
        lolos += 1
    return lolos


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sumber", required=True, help="berkas JSON array event")
    a = p.parse_args()
    try:
        print(f"OK Pasaree: {validasi_berkas(a.sumber)} event lolos validasi")
    except EventDitolak as e:
        raise SystemExit(f"DITOLAK [{e.alasan}] {e.field}: {e.pesan}") from e
