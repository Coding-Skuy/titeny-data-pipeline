"""Penyimpanan DB `titeny` (satu-satunya basis tulis Titeny) + rekalkulasi H-1 + retensi/arsip.

Tabel: `event_mentah` (panas 365 hari), `agregat_harian` (3 tahun), `rekalkulasi_log`.
Tidak menyentuh DB sumber; modul ini satu-satunya (selain `sumber_readonly`) yang membuat engine.

ASUMSI (dokumen tidak merinci):
- Hanya `transaksi.dibuat` dan `stok.berubah` membentuk `agregat_harian` (FR-005: stok/transaksi).
- Omzet = sum(round(qty_kg * harga_satuan)); `harga_satuan` dibaca sebagai IDR per kg (§3.4).
- Event on-time tidak memicu rekalkulasi (agregat hari berjalan dihitung job penutupan hari lewat
  `rekalkulasi_harian`); event terlambat <= 24 jam memicu rekalkulasi tanggal kejadiannya (H-1);
  terlambat > 24 jam disimpan + diflag `terlambat_lebih_24j`, TANPA rekalkulasi otomatis
  (agregat lama bisa sudah dipakai model; jalankan `rekalkulasi_harian` manual setelah ditinjau).
- Arsip dingin per `batch_id` hanya bila SEMUA event batch itu sudah lewat retensi mentah.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    Engine,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    insert,
    select,
)

from .jadwal_sla import WIB
from .skema import validasi_event

RETENSI_MENTAH_HARI = 365
RETENSI_AGREGAT_TAHUN = 3
AMBANG_TERLAMBAT = timedelta(hours=24)
TIPE_AGREGAT = ("transaksi.dibuat", "stok.berubah")
MANIFEST_KOLOM = ("batch_id", "berkas", "jumlah_baris", "sha256", "diarsipkan_pada")
POLA_BATCH_AMAN = re.compile(r"^[A-Za-z0-9_.-]+$")

meta = MetaData()
event_mentah = Table(
    "event_mentah",
    meta,
    Column("event_id", String(64), primary_key=True),
    Column("event_type", String(64), nullable=False),
    Column("source", String(16), nullable=False),
    Column("batch_id", String(128), nullable=False, index=True),
    Column("occurred_at", String(40), nullable=False),
    Column("received_at", String(40), nullable=False),
    Column("tanggal_kejadian", String(10), nullable=False, index=True),
    Column("terlambat_detik", Integer, nullable=False, default=0),
    Column("payload", Text, nullable=False),
)
agregat_harian = Table(
    "agregat_harian",
    meta,
    Column("tanggal", String(10), primary_key=True),
    Column("komoditas_id", String(64), primary_key=True),
    Column("jumlah_transaksi", Integer, nullable=False),
    Column("total_qty_kg", Float, nullable=False),
    Column("omzet_idr", Integer, nullable=False),
    Column("jumlah_mutasi_stok", Integer, nullable=False),
    Column("perubahan_stok_kg", Float, nullable=False),
    Column("direkalkulasi_pada", String(40), nullable=False),
)
rekalkulasi_log = Table(
    "rekalkulasi_log",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tanggal", String(10), nullable=False),
    Column("alasan", String(64), nullable=False),
    Column("event_id", String(64)),
    Column("dibuat_pada", String(40), nullable=False),
)


def buka_titeny(url: str) -> Engine:
    """Engine ke DB `titeny` (tulis diizinkan HANYA di sini) dan pastikan tabel ada."""
    mesin = create_engine(url)
    meta.create_all(mesin)
    return mesin


@dataclass
class HasilTerima:
    event_id: str
    status: str  # diterima | duplikat_diabaikan
    terlambat_detik: int = 0
    direkalkulasi: date | None = None
    flag: list[str] = field(default_factory=list)


def terima_event(mesin: Engine, mentah: dict[str, Any], sekarang: datetime) -> HasilTerima:
    """Simpan satu event (validasi dulu). Duplikat `event_id` -> `duplikat_diabaikan`."""
    ev = validasi_event(mentah)
    a = ev.amplop
    telat = a.received_at - a.occurred_at
    detik = max(0, int(telat.total_seconds()))
    tgl_kejadian = a.occurred_at.astimezone(WIB).date()
    tgl_terima = a.received_at.astimezone(WIB).date()

    with mesin.begin() as conn:
        ada = conn.execute(
            select(event_mentah.c.event_id).where(event_mentah.c.event_id == a.event_id)
        ).first()
        if ada:
            return HasilTerima(a.event_id, "duplikat_diabaikan")
        conn.execute(
            insert(event_mentah).values(
                event_id=a.event_id,
                event_type=a.event_type,
                source=a.source,
                batch_id=a.batch_id,
                occurred_at=a.occurred_at.isoformat(),
                received_at=a.received_at.isoformat(),
                tanggal_kejadian=tgl_kejadian.isoformat(),
                terlambat_detik=detik,
                payload=json.dumps(mentah["payload"], ensure_ascii=False, sort_keys=True),
            )
        )

    hasil = HasilTerima(a.event_id, "diterima", detik)
    if a.event_type in TIPE_AGREGAT and tgl_kejadian < tgl_terima:
        if telat <= AMBANG_TERLAMBAT:
            rekalkulasi_harian(mesin, tgl_kejadian, sekarang, "terlambat_H-1", a.event_id)
            hasil.direkalkulasi = tgl_kejadian
        else:
            hasil.flag.append("terlambat_lebih_24j")
    return hasil


def rekalkulasi_harian(
    mesin: Engine,
    tanggal: date,
    sekarang: datetime,
    alasan: str = "job_harian",
    event_id: str | None = None,
) -> int:
    """Hitung ulang agregat `tanggal` dari event mentah (idempoten: ganti, bukan tambah).

    Mengembalikan jumlah baris agregat hasil. Hanya menulis ke DB `titeny`.
    """
    iso = tanggal.isoformat()
    with mesin.begin() as conn:
        baris = conn.execute(
            select(event_mentah.c.event_type, event_mentah.c.payload).where(
                event_mentah.c.tanggal_kejadian == iso,
                event_mentah.c.event_type.in_(TIPE_AGREGAT),
            )
        ).all()
        per: dict[str, dict[str, float]] = defaultdict(
            lambda: {"n": 0, "qty": 0.0, "omzet": 0, "mut": 0, "dstok": 0.0}
        )
        for tipe, payload in baris:
            p = json.loads(payload)
            a = per[p["komoditas_id"]]
            if tipe == "transaksi.dibuat":
                a["n"] += 1
                a["qty"] += p["qty_kg"]
                a["omzet"] += round(p["qty_kg"] * p["harga_satuan"])
            else:
                a["mut"] += 1
                a["dstok"] += p["perubahan_kg"]
        conn.execute(delete(agregat_harian).where(agregat_harian.c.tanggal == iso))
        for kom, a in sorted(per.items()):
            conn.execute(
                insert(agregat_harian).values(
                    tanggal=iso,
                    komoditas_id=kom,
                    jumlah_transaksi=int(a["n"]),
                    total_qty_kg=round(a["qty"], 2),
                    omzet_idr=int(a["omzet"]),
                    jumlah_mutasi_stok=int(a["mut"]),
                    perubahan_stok_kg=round(a["dstok"], 2),
                    direkalkulasi_pada=sekarang.isoformat(),
                )
            )
        conn.execute(
            insert(rekalkulasi_log).values(
                tanggal=iso, alasan=alasan, event_id=event_id, dibuat_pada=sekarang.isoformat()
            )
        )
    return len(per)


def agregat(mesin: Engine, tanggal: date) -> dict[str, dict[str, Any]]:
    with mesin.connect() as conn:
        rows = conn.execute(
            select(agregat_harian).where(agregat_harian.c.tanggal == tanggal.isoformat())
        ).all()
    return {r.komoditas_id: dict(r._mapping) for r in rows}


# ---------------------------------------------------------------- retensi + arsip dingin


@dataclass
class HasilRetensi:
    batch_diarsipkan: list[str] = field(default_factory=list)
    baris_mentah_dihapus: int = 0
    baris_agregat_dihapus: int = 0
    batch_dilewati: list[str] = field(default_factory=list)


def _tulis_gzip_deterministik(baris: list[dict[str, Any]]) -> bytes:
    isi = "".join(json.dumps(b, ensure_ascii=False, sort_keys=True) + "\n" for b in baris)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:  # mtime=0 -> checksum stabil
        gz.write(isi.encode("utf-8"))
    return buf.getvalue()


def _baca_manifest(jalur: Path) -> list[dict[str, str]]:
    if not jalur.exists():
        return []
    with jalur.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _catat_manifest(jalur: Path, baris: dict[str, Any]) -> None:
    baru = not jalur.exists() or jalur.stat().st_size == 0
    with jalur.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_KOLOM)
        if baru:
            w.writeheader()
        w.writerow(baris)


def _kurangi_tahun(d: date, tahun: int) -> date:
    try:
        return d.replace(year=d.year - tahun)
    except ValueError:  # 29 Februari
        return d.replace(year=d.year - tahun, day=28)


def terapkan_retensi(
    mesin: Engine, sekarang: datetime, folder_arsip: str | Path = "data/arsip"
) -> HasilRetensi:
    """Arsipkan lalu hapus mentah > 365 hari (per batch) dan hapus agregat > 3 tahun.

    Mentah dihapus HANYA setelah arsip tertulis, dibaca ulang, dan SHA-256-nya cocok.
    """
    folder = Path(folder_arsip)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "manifest.csv"
    sudah = {r["batch_id"] for r in _baca_manifest(manifest)}
    batas_mentah = (
        sekarang.astimezone(WIB).date() - timedelta(days=RETENSI_MENTAH_HARI)
    ).isoformat()
    hasil = HasilRetensi()

    with mesin.connect() as conn:
        kandidat = [
            r.batch_id
            for r in conn.execute(
                select(event_mentah.c.batch_id)
                .group_by(event_mentah.c.batch_id)
                .having(func.max(event_mentah.c.tanggal_kejadian) < batas_mentah)
            )
        ]

    for batch in sorted(kandidat):
        if not POLA_BATCH_AMAN.match(batch):
            hasil.batch_dilewati.append(batch)  # nama tak aman untuk nama berkas
            continue
        with mesin.connect() as conn:
            rows = conn.execute(
                select(event_mentah)
                .where(event_mentah.c.batch_id == batch)
                .order_by(event_mentah.c.event_id)
            ).all()
        baris = [{**dict(r._mapping), "payload": json.loads(r.payload)} for r in rows]
        data = _tulis_gzip_deterministik(baris)
        sha = hashlib.sha256(data).hexdigest()
        berkas = folder / f"{batch}.jsonl.gz"
        if batch in sudah and berkas.exists():
            if hashlib.sha256(berkas.read_bytes()).hexdigest() != sha:
                hasil.batch_dilewati.append(batch)  # arsip lama beda isi: jangan hapus apa pun
                continue
        else:
            berkas.write_bytes(data)
            if hashlib.sha256(berkas.read_bytes()).hexdigest() != sha:
                raise OSError(f"checksum arsip {batch} tidak cocok setelah tulis")
            _catat_manifest(
                manifest,
                {
                    "batch_id": batch,
                    "berkas": berkas.name,
                    "jumlah_baris": len(baris),
                    "sha256": sha,
                    "diarsipkan_pada": sekarang.isoformat(),
                },
            )
        with mesin.begin() as conn:
            res = conn.execute(delete(event_mentah).where(event_mentah.c.batch_id == batch))
        hasil.baris_mentah_dihapus += res.rowcount
        hasil.batch_diarsipkan.append(batch)

    batas_agregat = _kurangi_tahun(sekarang.astimezone(WIB).date(), RETENSI_AGREGAT_TAHUN)
    with mesin.begin() as conn:
        res = conn.execute(
            delete(agregat_harian).where(agregat_harian.c.tanggal < batas_agregat.isoformat())
        )
    hasil.baris_agregat_dihapus = res.rowcount
    return hasil


def verifikasi_arsip(folder_arsip: str | Path = "data/arsip") -> list[str]:
    """Bandingkan SHA-256 berkas dengan manifest; kembalikan daftar masalah (kosong = utuh)."""
    folder = Path(folder_arsip)
    masalah: list[str] = []
    for r in _baca_manifest(folder / "manifest.csv"):
        berkas = folder / r["berkas"]
        if not berkas.exists():
            masalah.append(f"{r['berkas']}: berkas hilang")
        elif hashlib.sha256(berkas.read_bytes()).hexdigest() != r["sha256"]:
            masalah.append(f"{r['berkas']}: checksum tidak cocok")
        else:
            with gzip.open(berkas, "rt", encoding="utf-8") as f:
                n = sum(1 for _ in f)
            if n != int(r["jumlah_baris"]):
                masalah.append(f"{r['berkas']}: jumlah baris {n} != {r['jumlah_baris']}")
    return masalah
