"""TTN-DATA-005: rekalkulasi H-1 (tanpa duplikasi), retensi 365 hari/3 tahun, arsip dingin."""

import csv
import gzip
import hashlib
import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from pipeline.jadwal_sla import WIB
from pipeline.penyimpanan import (
    agregat,
    agregat_harian,
    buka_titeny,
    event_mentah,
    rekalkulasi_harian,
    rekalkulasi_log,
    terapkan_retensi,
    terima_event,
    verifikasi_arsip,
)
from pipeline.skema import EventDitolak

from .conftest import muat_fixture


def waktu(tgl: str, jam: str) -> str:
    return f"{tgl}T{jam}+07:00"


def trx(n: int, qty: float, harga: int, occ: str, rec: str, kom="cmd_telur_ayam", batch=None):
    e = muat_fixture("transaksi.dibuat")
    e["event_id"] = f"evt_{occ[:10].replace('-', '')}_{n:06d}"
    e["occurred_at"], e["received_at"] = occ, rec
    e["batch_id"] = batch or f"batch_titipo_{occ[:10].replace('-', '')}_malam"
    e["payload"].update(
        transaksi_id=f"trx_{n}", komoditas_id=kom, qty_kg=qty, harga_satuan=harga, waktu=occ
    )
    return e


def stok(n: int, delta: float, occ: str, rec: str, kom="cmd_beras_medium"):
    e = muat_fixture("stok.berubah")
    e["event_id"] = f"evt_{occ[:10].replace('-', '')}_{n:06d}"
    e["occurred_at"], e["received_at"] = occ, rec
    e["batch_id"] = f"batch_lumbung_{occ[:10].replace('-', '')}_rt"
    e["payload"].update(komoditas_id=kom, perubahan_kg=delta)
    return e


@pytest.fixture
def mesin(tmp_path):
    return buka_titeny(f"sqlite:///{tmp_path / 'titeny.db'}")


SEKARANG = datetime(2026, 10, 5, 9, 0, tzinfo=WIB)
H1 = date(2026, 10, 4)


def hitung(mesin, tabel):
    with mesin.connect() as c:
        return c.execute(select(func.count()).select_from(tabel)).scalar_one()


def test_event_tepat_waktu_tidak_rekalkulasi_job_harian_menghitung(mesin):
    h = terima_event(
        mesin,
        trx(1, 2.0, 28500, waktu("2026-10-04", "08:00:00"), waktu("2026-10-04", "08:00:05")),
        SEKARANG,
    )
    assert h.status == "diterima" and h.direkalkulasi is None
    assert agregat(mesin, H1) == {}
    rekalkulasi_harian(mesin, H1, SEKARANG)
    assert agregat(mesin, H1)["cmd_telur_ayam"]["omzet_idr"] == 57000


def test_event_terlambat_di_bawah_24_jam_memicu_rekalkulasi_h_min_1_tanpa_duplikasi(mesin):
    terima_event(
        mesin,
        trx(1, 2.0, 28500, waktu("2026-10-04", "08:00:00"), waktu("2026-10-04", "08:00:05")),
        SEKARANG,
    )
    terima_event(
        mesin,
        stok(2, -10.5, waktu("2026-10-04", "09:00:00"), waktu("2026-10-04", "09:00:05")),
        SEKARANG,
    )
    rekalkulasi_harian(mesin, H1, SEKARANG)  # penutupan hari
    sebelum = agregat(mesin, H1)
    assert sebelum["cmd_telur_ayam"]["jumlah_transaksi"] == 1
    assert sebelum["cmd_beras_medium"]["perubahan_stok_kg"] == -10.5

    # transaksi 04 Okt 23:30 baru diterima 05 Okt 08:00 (8,5 jam terlambat)
    late = trx(3, 3.0, 30000, waktu("2026-10-04", "23:30:00"), waktu("2026-10-05", "08:00:00"))
    h = terima_event(mesin, late, SEKARANG)
    assert h.direkalkulasi == H1 and h.terlambat_detik == 30600 and h.flag == []
    sesudah = agregat(mesin, H1)
    assert sesudah["cmd_telur_ayam"]["jumlah_transaksi"] == 2
    assert sesudah["cmd_telur_ayam"]["total_qty_kg"] == 5.0
    assert sesudah["cmd_telur_ayam"]["omzet_idr"] == 57000 + 90000
    assert sesudah["cmd_beras_medium"] == sebelum["cmd_beras_medium"] | {
        "direkalkulasi_pada": sesudah["cmd_beras_medium"]["direkalkulasi_pada"]
    }
    # tanpa duplikasi: satu baris agregat per (tanggal, komoditas)
    assert hitung(mesin, agregat_harian) == 2


def test_event_stok_terlambat_juga_memperbarui_agregat(mesin):
    rekalkulasi_harian(mesin, H1, SEKARANG)
    terima_event(
        mesin,
        stok(5, -4.0, waktu("2026-10-04", "22:00:00"), waktu("2026-10-05", "06:00:00")),
        SEKARANG,
    )
    a = agregat(mesin, H1)["cmd_beras_medium"]
    assert (a["jumlah_mutasi_stok"], a["perubahan_stok_kg"]) == (1, -4.0)


def test_kirim_ulang_event_terlambat_duplikat_tidak_mengubah_agregat(mesin):
    late = trx(3, 3.0, 30000, waktu("2026-10-04", "23:30:00"), waktu("2026-10-05", "08:00:00"))
    terima_event(mesin, late, SEKARANG)
    snap = agregat(mesin, H1)
    log_sebelum = hitung(mesin, rekalkulasi_log)
    h2 = terima_event(mesin, json.loads(json.dumps(late)), SEKARANG)
    assert h2.status == "duplikat_diabaikan" and h2.direkalkulasi is None
    assert hitung(mesin, event_mentah) == 1 and hitung(mesin, rekalkulasi_log) == log_sebelum
    assert agregat(mesin, H1) == snap


def test_rekalkulasi_berulang_idempoten(mesin):
    terima_event(
        mesin,
        trx(1, 2.0, 28500, waktu("2026-10-04", "08:00:00"), waktu("2026-10-04", "08:00:05")),
        SEKARANG,
    )
    for _ in range(3):
        rekalkulasi_harian(mesin, H1, SEKARANG)
    assert hitung(mesin, agregat_harian) == 1


def test_terlambat_lebih_24_jam_disimpan_diflag_tanpa_rekalkulasi_otomatis(mesin):
    e = trx(7, 1.0, 10000, waktu("2026-10-02", "08:00:00"), waktu("2026-10-04", "09:00:00"))
    h = terima_event(mesin, e, SEKARANG)
    assert h.status == "diterima" and h.flag == ["terlambat_lebih_24j"] and h.direkalkulasi is None
    assert hitung(mesin, event_mentah) == 1 and hitung(mesin, agregat_harian) == 0


def test_tepat_24_jam_masih_direkalkulasi(mesin):
    e = trx(8, 1.0, 10000, waktu("2026-10-03", "10:00:00"), waktu("2026-10-04", "10:00:00"))
    assert terima_event(mesin, e, SEKARANG).direkalkulasi == date(2026, 10, 3)


def test_event_tidak_sah_tidak_disimpan(mesin):
    e = trx(9, 99.0, 10000, waktu("2026-10-04", "08:00:00"), waktu("2026-10-04", "08:00:05"))
    with pytest.raises(EventDitolak):
        terima_event(mesin, e, SEKARANG)
    assert hitung(mesin, event_mentah) == 0


# ------------------------------------------------------------------ retensi + arsip dingin

NOW = datetime(2026, 10, 21, 3, 0, tzinfo=WIB)


def _isi_batch(mesin, batch, tanggal, jumlah, mulai=1):
    for i in range(jumlah):
        n = mulai + i
        terima_event(
            mesin,
            trx(
                n,
                1.0 + i,
                1000,
                waktu(tanggal, "08:00:00"),
                waktu(tanggal, "08:00:05"),
                batch=batch,
            ),
            NOW,
        )


def test_retensi_mentah_365_hari_arsip_jsonl_gzip_checksum_manifest(mesin, tmp_path):
    arsip = tmp_path / "arsip"
    batas = (NOW.date() - timedelta(days=365)).isoformat()  # 2025-10-21
    tua = (NOW.date() - timedelta(days=366)).isoformat()
    _isi_batch(mesin, "batch_titipo_tua_malam", tua, 3, mulai=1)
    _isi_batch(mesin, "batch_titipo_batas_malam", batas, 2, mulai=10)  # tepat 365 hari: tetap panas
    _isi_batch(mesin, "batch_titipo_baru_malam", "2026-10-20", 2, mulai=20)

    h = terapkan_retensi(mesin, NOW, arsip)
    assert h.batch_diarsipkan == ["batch_titipo_tua_malam"]
    assert h.baris_mentah_dihapus == 3
    assert hitung(mesin, event_mentah) == 4  # batas + baru tetap panas

    berkas = arsip / "batch_titipo_tua_malam.jsonl.gz"
    data = berkas.read_bytes()
    with gzip.open(berkas, "rt", encoding="utf-8") as f:
        baris = [json.loads(x) for x in f]
    assert len(baris) == 3 and {b["event_type"] for b in baris} == {"transaksi.dibuat"}
    assert baris[0]["payload"]["komoditas_id"] == "cmd_telur_ayam"

    with (arsip / "manifest.csv").open(encoding="utf-8", newline="") as f:
        m = list(csv.DictReader(f))
    assert list(m[0]) == ["batch_id", "berkas", "jumlah_baris", "sha256", "diarsipkan_pada"]
    assert m[0]["batch_id"] == "batch_titipo_tua_malam" and m[0]["jumlah_baris"] == "3"
    assert m[0]["sha256"] == hashlib.sha256(data).hexdigest()
    assert verifikasi_arsip(arsip) == []


def test_arsip_rusak_terdeteksi_verifikasi(mesin, tmp_path):
    arsip = tmp_path / "arsip"
    tua = (NOW.date() - timedelta(days=400)).isoformat()
    _isi_batch(mesin, "batch_titipo_tua_malam", tua, 2)
    terapkan_retensi(mesin, NOW, arsip)
    (arsip / "batch_titipo_tua_malam.jsonl.gz").write_bytes(b"rusak")
    assert any("checksum tidak cocok" in x for x in verifikasi_arsip(arsip))


def test_batch_campuran_tidak_diarsipkan_sebelum_semua_event_kedaluwarsa(mesin, tmp_path):
    arsip = tmp_path / "arsip"
    tua = (NOW.date() - timedelta(days=400)).isoformat()
    _isi_batch(mesin, "batch_campur", tua, 1, mulai=1)
    _isi_batch(mesin, "batch_campur", "2026-10-20", 1, mulai=2)
    h = terapkan_retensi(mesin, NOW, arsip)
    assert h.batch_diarsipkan == [] and hitung(mesin, event_mentah) == 2
    assert not list(arsip.glob("*.gz"))


def test_retensi_idempoten_dan_nama_batch_tak_aman_dilewati(mesin, tmp_path):
    arsip = tmp_path / "arsip"
    tua = (NOW.date() - timedelta(days=400)).isoformat()
    _isi_batch(mesin, "batch_ok", tua, 1, mulai=1)
    _isi_batch(mesin, "../../etc/passwd", tua, 1, mulai=5)
    h1 = terapkan_retensi(mesin, NOW, arsip)
    assert h1.batch_diarsipkan == ["batch_ok"] and h1.batch_dilewati == ["../../etc/passwd"]
    assert not (tmp_path / "etc").exists() and hitung(mesin, event_mentah) == 1
    h2 = terapkan_retensi(mesin, NOW, arsip)
    assert h2.batch_diarsipkan == []
    with (arsip / "manifest.csv").open(encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 1


def test_retensi_agregat_3_tahun(mesin, tmp_path):
    # sisipkan agregat langsung lewat rekalkulasi atas event lama
    for tgl in ("2023-10-20", "2023-10-21", "2025-01-01"):
        terima_event(
            mesin,
            trx(30, 1.0, 1000, waktu(tgl, "08:00:00"), waktu(tgl, "08:00:05"), batch=f"b_{tgl}"),
            NOW,
        )
        rekalkulasi_harian(mesin, date.fromisoformat(tgl), NOW)
    with mesin.begin() as c:  # lepaskan mentah agar uji fokus pada agregat
        c.execute(event_mentah.delete())
    h = terapkan_retensi(mesin, NOW, tmp_path / "arsip")
    assert h.baris_agregat_dihapus == 1  # hanya 2023-10-20 (< 2023-10-21)
    with mesin.connect() as c:
        sisa = sorted(r.tanggal for r in c.execute(select(agregat_harian.c.tanggal)))
    assert sisa == ["2023-10-21", "2025-01-01"]


def test_data_arsip_manifest_repo_berisi_header():
    from pathlib import Path

    isi = (Path(__file__).parent.parent / "data" / "arsip" / "manifest.csv").read_text()
    assert isi.splitlines()[0] == "batch_id,berkas,jumlah_baris,sha256,diarsipkan_pada"
