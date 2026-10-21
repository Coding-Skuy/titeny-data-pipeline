"""Konektor baca S1-S10 -> event 11 terkunci. SEMUA akses sumber lewat `sumber_readonly.baca`.

ASUMSI SKEMA SUMBER: dokumen beku hanya menyebut isi logis tiap sumber (data/10-sumber-data.md),
bukan nama tabel/kolom DB Lumbung/TitipO/Pasaree. Nama tabel di bawah adalah asumsi dan wajib
dikonfirmasi pemilik sumber; kolom dipilih eksplisit (tanpa `SELECT *`) dan tidak memuat data
pribadi (nama, alamat, telepon). Transaksi hanya membawa `zona_rute` + id anonim.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine

from .skema import EventDitolak, validasi_event
from .sumber_readonly import baca

KOLOM_PRIBADI = frozenset(
    {
        "nama",
        "nama_pembeli",
        "nama_petani",
        "alamat",
        "telepon",
        "no_hp",
        "email",
        "petani_id",
        "pembeli_id",
        "ktp",
    }
)

# Rentang wajar per komoditas (S1 "Kualitas V1"); hanya yang disebut dokumen.
RENTANG_WAJAR_HARGA: dict[str, tuple[int, int]] = {"cmd_cabai_merah": (15_000, 120_000)}


class GeneratorEventId:
    """`evt_YYYYMMDD_NNNNNN`, urutan per tanggal. Pemanggil menyimpan `awal` antar-proses."""

    def __init__(self, awal: dict[str, int] | None = None):
        self._n: dict[str, int] = defaultdict(int, awal or {})

    def baru(self, tanggal: date) -> str:
        k = f"{tanggal:%Y%m%d}"
        self._n[k] += 1
        if self._n[k] > 999_999:
            raise OverflowError("urutan event_id harian melebihi 999999")
        return f"evt_{k}_{self._n[k]:06d}"


@dataclass
class HasilBaca:
    sid: str
    events: list[dict[str, Any]] = field(default_factory=list)
    ditolak: list[EventDitolak] = field(default_factory=list)
    jumlah_baris_sumber: int = 0


def _iso(v: Any) -> str:
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _tgl(v: Any) -> str:
    if isinstance(v, datetime):
        return v.date().isoformat()
    return str(v)[:10]


def _angka(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    return v


def _dt(v: Any) -> datetime:
    """Waktu dari sumber; yang tanpa zona dianggap WIB (konvensi Asia/Jakarta)."""
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return d if d.tzinfo else d.replace(tzinfo=_wib())


@dataclass
class Konteks:
    gen: GeneratorEventId
    sekarang: Callable[[], datetime]

    def amplop(
        self,
        tipe: str,
        source: str,
        occurred: Any,
        payload: dict[str, Any],
        label_batch: str,
    ) -> dict[str, Any]:
        occ = _dt(occurred)
        rec = self.sekarang()
        return {
            "event_id": self.gen.baru(occ.date()),
            "event_type": tipe,
            "schema_version": 1,
            "source": source,
            "occurred_at": occ.isoformat(),
            "received_at": rec.isoformat(),
            "batch_id": f"batch_{source}_{occ:%Y%m%d}_{label_batch}",
            "payload": payload,
        }


@dataclass(frozen=True)
class KonektorSql:
    """Konektor deklaratif: satu SELECT + pemeta baris -> amplop event."""

    sid: str
    sql: str
    peta: Callable[[list[dict[str, Any]], Konteks], list[dict[str, Any]]]

    def baca(self, mesin: Engine, ctx: Konteks, **param: Any) -> HasilBaca:
        baris = baca(mesin, self.sql, **param)
        return _selesaikan(self.sid, baris, self.peta(baris, ctx))


def _selesaikan(sid: str, baris: list[Any], events: list[dict[str, Any]]) -> HasilBaca:
    hasil = HasilBaca(sid, jumlah_baris_sumber=len(baris))
    for ev in events:
        try:
            validasi_event(ev)
        except EventDitolak as e:  # baris sumber buruk: tandai, jangan dibuang diam-diam
            hasil.ditolak.append(e)
        else:
            hasil.events.append(ev)
    return hasil


# --- S1 harga pasar harian (Pasaree) --------------------------------------------------------
SQL_S1 = (
    "SELECT pasar_id, komoditas_id, lapak_id, harga_per_kg, satuan, waktu_catat "
    "FROM harga_lapak WHERE waktu_catat >= :sejak AND waktu_catat < :sampai"
)


def _peta_s1(baris: list[dict[str, Any]], ctx: Konteks) -> list[dict[str, Any]]:
    grup: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for b in baris:
        grup[(b["pasar_id"], b["komoditas_id"], _tgl(b["waktu_catat"]))].append(b)
    out = []
    for (pasar, kom, tgl), rows in sorted(grup.items()):
        harga = int(round(statistics.median(float(_angka(r["harga_per_kg"])) for r in rows)))
        sampel = len({r["lapak_id"] for r in rows})
        rentang = RENTANG_WAJAR_HARGA.get(kom)
        luar = bool(rentang and not rentang[0] <= harga <= rentang[1])
        flag = "perlu_verifikasi" if sampel < 3 or luar else "ok"
        terakhir = max(_dt(r["waktu_catat"]) for r in rows)
        out.append(
            ctx.amplop(
                "harga.diperbarui",
                "pasaree",
                terakhir,
                {
                    "pasar_id": pasar,
                    "komoditas_id": kom,
                    "tanggal": tgl,
                    "harga_per_kg": harga,
                    "satuan": "kg",
                    "jumlah_sampel_lapak": sampel,
                    "flag": flag,
                },
                "pagi",
            )
        )
    return out


# --- S2 stok (Lumbung): mutasi real-time + snapshot 23.00 ---------------------------------
SQL_S2_MUTASI = (
    "SELECT gudang_id, komoditas_id, perubahan_kg, stok_akhir_kg, alasan, waktu_mutasi "
    "FROM mutasi_stok WHERE waktu_mutasi >= :sejak AND waktu_mutasi < :sampai"
)
SQL_S2_SNAPSHOT = (
    "SELECT gudang_id, komoditas_id, stok_kg FROM stok_gudang WHERE stok_kg IS NOT NULL"
)


def _peta_s2_mutasi(baris: list[dict[str, Any]], ctx: Konteks) -> list[dict[str, Any]]:
    return [
        ctx.amplop(
            "stok.berubah",
            "lumbung",
            b["waktu_mutasi"],
            {
                "gudang_id": b["gudang_id"],
                "komoditas_id": b["komoditas_id"],
                "perubahan_kg": _angka(b["perubahan_kg"]),
                "stok_akhir_kg": _angka(b["stok_akhir_kg"]),
                "alasan": b["alasan"],
            },
            "realtime",
        )
        for b in baris
    ]


def peta_s2_snapshot(
    tanggal: date,
) -> Callable[[list[dict[str, Any]], Konteks], list[dict[str, Any]]]:
    def _peta(baris: list[dict[str, Any]], ctx: Konteks) -> list[dict[str, Any]]:
        per_gudang: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for b in baris:
            per_gudang[b["gudang_id"]].append(
                {"komoditas_id": b["komoditas_id"], "stok_kg": _angka(b["stok_kg"])}
            )
        return [
            ctx.amplop(
                "stok.snapshot_harian",
                "lumbung",
                datetime(tanggal.year, tanggal.month, tanggal.day, 23, 0, tzinfo=_wib()),
                {
                    "gudang_id": g,
                    "tanggal": tanggal.isoformat(),
                    "baris": rows,
                    "jumlah_baris": len(rows),
                },
                "snapshot_malam",
            )
            for g, rows in sorted(per_gudang.items())
        ]

    return _peta


def _wib():
    from .jadwal_sla import WIB

    return WIB


# --- S3 transaksi komunitas (TitipO): TANPA data pribadi ---------------------------------
SQL_S3 = (
    "SELECT transaksi_id, komoditas_id, qty_kg, harga_satuan, vendor_id, zona_rute, waktu "
    "FROM transaksi WHERE waktu >= :sejak AND waktu < :sampai"
)


def _peta_s3(baris: list[dict[str, Any]], ctx: Konteks) -> list[dict[str, Any]]:
    return [
        ctx.amplop(
            "transaksi.dibuat",
            "titipo",
            b["waktu"],
            {
                "transaksi_id": b["transaksi_id"],
                "komoditas_id": b["komoditas_id"],
                "qty_kg": _angka(b["qty_kg"]),
                "harga_satuan": int(_angka(b["harga_satuan"])),
                "vendor_id": b["vendor_id"],
                "zona_rute": b["zona_rute"],
                "waktu": _iso(_dt(b["waktu"])),
            },
            "realtime",
        )
        for b in baris
    ]


# --- S4 lapak (Pasaree) ----------------------------------------------------------------------
SQL_S4 = (
    "SELECT lapak_id, status, komoditas_utama, diubah_pada "
    "FROM lapak WHERE diubah_pada >= :sejak AND diubah_pada < :sampai"
)


def _peta_s4(baris: list[dict[str, Any]], ctx: Konteks) -> list[dict[str, Any]]:
    return [
        ctx.amplop(
            "lapak.status_berubah",
            "pasaree",
            b["diubah_pada"],
            {
                "lapak_id": b["lapak_id"],
                "status": b["status"],
                "komoditas_utama": b["komoditas_utama"],
            },
            "realtime",
        )
        for b in baris
    ]


# --- S5 panen (Lumbung) ---------------------------------------------------------------------
SQL_S5 = (
    "SELECT panen_id, komoditas_id, lahan_ha, hasil_kg, tanggal_panen, mutu, kabupaten_id, "
    "keterangan, dicatat_pada FROM panen WHERE dicatat_pada >= :sejak AND dicatat_pada < :sampai"
)


def _peta_s5(baris: list[dict[str, Any]], ctx: Konteks) -> list[dict[str, Any]]:
    return [
        ctx.amplop(
            "panen.dicatat",
            "lumbung",
            b["dicatat_pada"],
            {
                "panen_id": b["panen_id"],
                "komoditas_id": b["komoditas_id"],
                "lahan_ha": _angka(b["lahan_ha"]),
                "hasil_kg": _angka(b["hasil_kg"]),
                "tanggal_panen": _tgl(b["tanggal_panen"]),
                "mutu": b["mutu"],
                "kabupaten_id": b["kabupaten_id"],
                "keterangan": b["keterangan"] or "",
            },
            "per_kejadian",
        )
        for b in baris
    ]


# --- S6 logistik (TitipO + Pasaree) -----------------------------------------------------------
SQL_S6 = (
    "SELECT rute_id, jarak_km, biaya_per_kg, moda, berlaku_mulai, sebab, diubah_pada "
    "FROM rute_biaya WHERE diubah_pada >= :sejak AND diubah_pada < :sampai"
)


def _peta_s6(baris: list[dict[str, Any]], ctx: Konteks) -> list[dict[str, Any]]:
    return [
        ctx.amplop(
            "logistik.biaya_diperbarui",
            "titipo",
            b["diubah_pada"],
            {
                "rute_id": b["rute_id"],
                "jarak_km": _angka(b["jarak_km"]),
                "biaya_per_kg": int(_angka(b["biaya_per_kg"])),
                "moda": b["moda"],
                "berlaku_mulai": _tgl(b["berlaku_mulai"]),
                "sebab": b["sebab"],
            },
            "episodik",
        )
        for b in baris
    ]


# --- S7 vendor (TitipO + Pasaree) -------------------------------------------------------------
SQL_S7 = (
    "SELECT vendor_id, jenis, status_aktif, zona_operasi, kapasitas_harian_kg, diubah_pada "
    "FROM vendor WHERE diubah_pada >= :sejak AND diubah_pada < :sampai"
)


def _peta_s7(baris: list[dict[str, Any]], ctx: Konteks) -> list[dict[str, Any]]:
    return [
        ctx.amplop(
            "vendor.status_berubah",
            "titipo",
            b["diubah_pada"],
            {
                "vendor_id": b["vendor_id"],
                "jenis": b["jenis"],
                "status_aktif": bool(b["status_aktif"]),
                "zona_operasi": b["zona_operasi"],
                "kapasitas_harian_kg": _angka(b["kapasitas_harian_kg"]),
            },
            "realtime",
        )
        for b in baris
    ]


# --- S10 keuangan harian (Lumbung) ------------------------------------------------------------
SQL_S10 = (
    "SELECT tanggal, omzet_idr, margin_kotor_idr, biaya_operasional_idr, piutang_idr, final "
    "FROM ringkasan_keuangan WHERE tanggal = :tanggal"
)


def _peta_s10(baris: list[dict[str, Any]], ctx: Konteks) -> list[dict[str, Any]]:
    out = []
    for b in baris:
        tgl = _tgl(b["tanggal"])
        out.append(
            ctx.amplop(
                "keuangan.ringkasan_harian",
                "lumbung",
                datetime.fromisoformat(tgl).replace(hour=23, minute=45, tzinfo=_wib()),
                {
                    "tanggal": tgl,
                    "omzet_idr": int(_angka(b["omzet_idr"])),
                    "margin_kotor_idr": int(_angka(b["margin_kotor_idr"])),
                    "biaya_operasional_idr": int(_angka(b["biaya_operasional_idr"])),
                    "piutang_idr": int(_angka(b["piutang_idr"])),
                    "final": bool(b["final"]),
                },
                "malam",
            )
        )
    return out


KONEKTOR_SQL: dict[str, KonektorSql] = {
    "S1": KonektorSql("S1", SQL_S1, _peta_s1),
    "S2": KonektorSql("S2", SQL_S2_MUTASI, _peta_s2_mutasi),
    "S3": KonektorSql("S3", SQL_S3, _peta_s3),
    "S4": KonektorSql("S4", SQL_S4, _peta_s4),
    "S5": KonektorSql("S5", SQL_S5, _peta_s5),
    "S6": KonektorSql("S6", SQL_S6, _peta_s6),
    "S7": KonektorSql("S7", SQL_S7, _peta_s7),
    "S10": KonektorSql("S10", SQL_S10, _peta_s10),
}
SEMUA_SQL: dict[str, str] = {
    **{k: v.sql for k, v in KONEKTOR_SQL.items()},
    "S2_SNAPSHOT": SQL_S2_SNAPSHOT,
}


def baca_snapshot_stok(mesin: Engine, ctx: Konteks, tanggal: date) -> HasilBaca:
    """S2 snapshot 23.00: `stok.snapshot_harian` per gudang."""
    baris = baca(mesin, SQL_S2_SNAPSHOT)
    return _selesaikan("S2", baris, peta_s2_snapshot(tanggal)(baris, ctx))


# --- S8 cuaca (BMKG, API eksternal, hanya GET) dan S9 kalender internal ------------------------
def baca_cuaca(
    ambil: Callable[[date], list[dict[str, Any]]], ctx: Konteks, tanggal: date
) -> HasilBaca:
    """S8: `ambil(tanggal)` mengembalikan baris per kabupaten (injeksi; hanya baca/GET)."""
    baris = ambil(tanggal)
    events = [
        ctx.amplop(
            "cuaca.diperbarui",
            "cuaca",
            datetime(tanggal.year, tanggal.month, tanggal.day, 5, 0, tzinfo=_wib()),
            {
                "kabupaten_id": b["kabupaten_id"],
                "tanggal": tanggal.isoformat(),
                "curah_hujan_mm": _angka(b["curah_hujan_mm"]),
                "suhu_avg_c": _angka(b["suhu_avg_c"]),
                "peringatan": b.get("peringatan", "tidak_ada"),
            },
            "pagi",
        )
        for b in baris
    ]
    return _selesaikan("S8", baris, events)


def baca_kalender(
    ambil: Callable[[int], list[dict[str, Any]]], ctx: Konteks, tahun: int
) -> HasilBaca:
    """S9: master kalender tahun `tahun`, dikunci 1 Desember tahun sebelumnya."""
    baris = ambil(tahun)
    kunci = datetime(tahun - 1, 12, 1, tzinfo=_wib())
    ev = ctx.amplop(
        "kalender.dikunci",
        "internal",
        kunci,
        {
            "tahun": tahun,
            "baris": [
                {"tanggal": _tgl(b["tanggal"]), "jenis_hari": b["jenis_hari"], "musim": b["musim"]}
                for b in baris
            ],
            "jumlah_baris": len(baris),
            "dikunci_pada": kunci.isoformat(),
        },
        "tahunan",
    )
    return _selesaikan("S9", baris, [ev])
