"""TTN-DATA-004: konektor S1-S10, audit nol tulis ke DB sumber, tanpa data pribadi, SLA."""

import ast
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from pipeline import konektor, sumber_readonly
from pipeline.jadwal_sla import JADWAL, WIB, periksa_sla
from pipeline.konektor import (
    KOLOM_PRIBADI,
    KONEKTOR_SQL,
    SEMUA_SQL,
    GeneratorEventId,
    Konteks,
    baca_cuaca,
    baca_kalender,
    baca_snapshot_stok,
)
from pipeline.sumber_readonly import (
    KoneksiTidakReadOnly,
    TulisDitolak,
    audit_string_koneksi,
    baca,
    buka_readonly,
    pastikan_select,
)

SEKARANG = datetime(2026, 10, 4, 8, 0, 41, tzinfo=WIB)
SEJAK, SAMPAI = "2026-10-04T00:00:00", "2026-10-05T00:00:00"
SRC = Path(__file__).parent.parent / "src" / "pipeline"


def ctx() -> Konteks:
    return Konteks(GeneratorEventId(), lambda: SEKARANG)


@pytest.fixture
def db_sumber(tmp_path):
    """DB sumber palsu (SQLite) dibuat via koneksi tulis HANYA di fixture; kode produk ro."""
    jalur = tmp_path / "sumber.db"
    c = sqlite3.connect(jalur)
    c.executescript(
        """
        CREATE TABLE harga_lapak(pasar_id, komoditas_id, lapak_id, harga_per_kg, satuan, waktu_catat);
        CREATE TABLE mutasi_stok(gudang_id, komoditas_id, perubahan_kg, stok_akhir_kg, alasan, waktu_mutasi);
        CREATE TABLE stok_gudang(gudang_id, komoditas_id, stok_kg);
        CREATE TABLE transaksi(transaksi_id, komoditas_id, qty_kg, harga_satuan, vendor_id, zona_rute, waktu, nama_pembeli, alamat, telepon);
        CREATE TABLE lapak(lapak_id, status, komoditas_utama, diubah_pada);
        CREATE TABLE panen(panen_id, komoditas_id, lahan_ha, hasil_kg, tanggal_panen, mutu, kabupaten_id, keterangan, dicatat_pada, petani_id, nama_petani);
        CREATE TABLE rute_biaya(rute_id, jarak_km, biaya_per_kg, moda, berlaku_mulai, sebab, diubah_pada);
        CREATE TABLE vendor(vendor_id, jenis, status_aktif, zona_operasi, kapasitas_harian_kg, diubah_pada, nama, telepon);
        CREATE TABLE ringkasan_keuangan(tanggal, omzet_idr, margin_kotor_idr, biaya_operasional_idr, piutang_idr, final);
        """
    )
    for i in range(3):
        c.execute(
            "INSERT INTO harga_lapak VALUES('psr_jakarta_timur_01','cmd_cabai_merah',?,?,?,?)",
            (f"lpk_{i}", 40000 + i * 1000, "kg", f"2026-10-04T07:0{i}:00+07:00"),
        )
    c.execute(
        "INSERT INTO harga_lapak VALUES('psr_bekasi_01','cmd_bawang_merah','lpk_9',30000,'kg','2026-10-04T07:30:00+07:00')"
    )
    c.execute(
        "INSERT INTO mutasi_stok VALUES('gdg_bekasi_01','cmd_beras_medium',-150.5,4850,'keluar_penjualan','2026-10-04T08:00:00+07:00')"
    )
    c.execute("INSERT INTO stok_gudang VALUES('gdg_bekasi_01','cmd_beras_medium',4850)")
    c.execute(
        "INSERT INTO transaksi VALUES('trx_1','cmd_telur_ayam',2.0,28500,'vnd_keliling_014','bekasi_utara','2026-10-04T08:12:00+07:00','Budi Rahasia','Jl. Mawar 1','0812')"
    )
    c.execute(
        "INSERT INTO lapak VALUES('lpk_042','aktif','cmd_cabai_merah','2026-10-04T06:00:00+07:00')"
    )
    c.execute(
        "INSERT INTO panen VALUES('pn_1','cmd_padi',1.25,6875,'2026-10-01','A','kab_karawang',NULL,'2026-10-04T05:00:00+07:00','ptn_1','Pak Tani')"
    )
    c.execute(
        "INSERT INTO rute_biaya VALUES('rte_1',18.5,900,'mobil_pickup','2026-10-05','penyesuaian_bbm','2026-10-04T04:00:00+07:00')"
    )
    c.execute(
        "INSERT INTO vendor VALUES('vnd_1','keliling',1,'bekasi_utara',120,'2026-10-04T03:00:00+07:00','Pak Vendor','0813')"
    )
    c.execute(
        "INSERT INTO ringkasan_keuangan VALUES('2026-10-04',48250000,7210000,4350000,1200000,1)"
    )
    c.commit()
    c.close()
    return jalur


@pytest.fixture
def mesin(db_sumber):
    return buka_readonly(f"sqlite:///file:{db_sumber}?mode=ro&uri=true")


# ---------- audit read-only ----------


def test_audit_string_koneksi():
    assert audit_string_koneksi("sqlite:///file:/x.db?mode=ro&uri=true") == []
    assert audit_string_koneksi("sqlite:////x.db")  # tanpa mode=ro
    ok = "postgresql://lumbung_ro:pw@h/lumbung?options=-c%20default_transaction_read_only%3Don"
    assert audit_string_koneksi(ok) == []
    assert audit_string_koneksi("postgresql://lumbung_app:pw@h/lumbung")  # tulis
    assert audit_string_koneksi("postgresql://lumbung_ro:pw@h/lumbung")  # tanpa opsi
    assert audit_string_koneksi("mysql://a@h/db")


def test_buka_readonly_menolak_koneksi_tulis():
    with pytest.raises(KoneksiTidakReadOnly):
        buka_readonly("postgresql://lumbung_app:pw@h/lumbung")
    with pytest.raises(KoneksiTidakReadOnly):
        buka_readonly("sqlite:////tmp/x.db")


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO harga_lapak VALUES (1)",
        "UPDATE harga_lapak SET harga_per_kg=1",
        "DELETE FROM harga_lapak",
        "DROP TABLE harga_lapak",
        "SELECT 1; DELETE FROM harga_lapak",
        "WITH x AS (SELECT 1) DELETE FROM harga_lapak",
        "  /* siasat */ update harga_lapak set a=1",
        "PRAGMA query_only = OFF",
        "SELECT 1 FROM t FOR UPDATE",
        "COPY t TO '/tmp/x'",
        "",
    ],
)
def test_penjaga_menolak_semua_pernyataan_tulis(sql):
    with pytest.raises(TulisDitolak):
        pastikan_select(sql)


def test_penjaga_menerima_select_dan_with_dan_abaikan_literal():
    pastikan_select("SELECT a FROM t WHERE alasan = 'update data'")
    pastikan_select("WITH x AS (SELECT 1 AS a) SELECT a FROM x;")


def test_tulis_lewat_engine_ditolak_penjaga_dan_data_tak_berubah(mesin, db_sumber):
    with pytest.raises(Exception) as ex, mesin.begin() as conn:
        conn.execute(text("DELETE FROM harga_lapak"))
    # SQLAlchemy membungkus galat event handler; penyebab akar harus TulisDitolak
    akar = ex.value
    while akar.__cause__ or akar.__context__:
        akar = akar.__cause__ or akar.__context__
    assert isinstance(ex.value, TulisDitolak) or isinstance(akar, TulisDitolak)
    n = sqlite3.connect(db_sumber).execute("SELECT count(*) FROM harga_lapak").fetchone()[0]
    assert n == 4


def test_lapis_db_menolak_tulis_walau_penjaga_dilewati(mesin, db_sumber):
    """Bukti lapis ke-2: bahkan lewat DBAPI mentah, SQLite mode=ro menolak penulisan."""
    raw = mesin.raw_connection()
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            raw.driver_connection.execute("INSERT INTO harga_lapak VALUES (1,2,3,4,5,6)")
    finally:
        raw.close()
    n = sqlite3.connect(db_sumber).execute("SELECT count(*) FROM harga_lapak").fetchone()[0]
    assert n == 4


def test_baca_menolak_executemany_dan_non_select(mesin):
    with pytest.raises(TulisDitolak):
        baca(mesin, "DELETE FROM harga_lapak")


# ---------- audit statis kode: nol INSERT/UPDATE/DELETE ke sumber ----------


def test_semua_sql_konektor_select_murni_tanpa_kata_tulis():
    assert len(SEMUA_SQL) == 9
    for sql in SEMUA_SQL.values():
        pastikan_select(sql)


def test_audit_statis_kode_konektor_tanpa_sql_tulis_dan_tanpa_engine_liar():
    pola = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b", re.IGNORECASE)
    for nama in ("konektor.py", "jadwal_sla.py"):
        pohon = ast.parse((SRC / nama).read_text(encoding="utf-8"))
        for node in ast.walk(pohon):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if len(node.value) > 40:  # abaikan docstring pendek; periksa SQL
                    if node.value.lstrip().upper().startswith(("SELECT", "WITH", "INSERT")):
                        assert not pola.search(node.value), node.value
    # satu-satunya create_engine ke sumber ada di sumber_readonly
    for p in SRC.glob("*.py"):
        if p.name in ("sumber_readonly.py", "penyimpanan.py"):
            continue
        assert "create_engine" not in p.read_text(encoding="utf-8"), p.name
        assert "sqlalchemy" not in p.read_text(encoding="utf-8") or p.name == "konektor.py"


def test_konektor_hanya_memanggil_baca_readonly():
    isi = (SRC / "konektor.py").read_text(encoding="utf-8")
    assert "from .sumber_readonly import baca" in isi
    assert ".execute(" not in isi and "exec_driver_sql" not in isi and ".connect(" not in isi


# ---------- data pribadi ----------


def test_sql_tidak_memilih_kolom_pribadi_atau_bintang():
    for nama, sql in SEMUA_SQL.items():
        daftar = re.search(r"SELECT (.*?) FROM", sql, re.IGNORECASE | re.DOTALL).group(1)
        kolom = {k.strip().lower() for k in daftar.split(",")}
        assert "*" not in kolom, nama
        assert not (kolom & KOLOM_PRIBADI), (nama, kolom & KOLOM_PRIBADI)


def test_event_dari_sumber_berisi_pii_tidak_membawa_pii(mesin):
    h = KONEKTOR_SQL["S3"].baca(mesin, ctx(), sejak=SEJAK, sampai=SAMPAI)
    assert len(h.events) == 1 and not h.ditolak
    s = str(h.events[0])
    for rahasia in ("Budi Rahasia", "Jl. Mawar", "0812", "nama_pembeli", "alamat", "telepon"):
        assert rahasia not in s
    assert h.events[0]["payload"]["zona_rute"] == "bekasi_utara"
    for sid in ("S5", "S7"):
        h = KONEKTOR_SQL[sid].baca(mesin, ctx(), sejak=SEJAK, sampai=SAMPAI)
        assert "Pak Tani" not in str(h.events) and "Pak Vendor" not in str(h.events)
        assert "ptn_1" not in str(h.events)


# ---------- konektor S1-S10 menghasilkan event sah ----------


def test_s1_agregasi_harga_median_sampel_dan_flag(mesin):
    h = KONEKTOR_SQL["S1"].baca(mesin, ctx(), sejak=SEJAK, sampai=SAMPAI)
    per = {e["payload"]["komoditas_id"]: e["payload"] for e in h.events}
    assert per["cmd_cabai_merah"]["harga_per_kg"] == 41000
    assert per["cmd_cabai_merah"]["jumlah_sampel_lapak"] == 3
    assert per["cmd_cabai_merah"]["flag"] == "ok"
    assert per["cmd_bawang_merah"]["jumlah_sampel_lapak"] == 1
    assert per["cmd_bawang_merah"]["flag"] == "perlu_verifikasi"
    assert not h.ditolak


def test_s1_harga_di_luar_rentang_wajar_ditandai(mesin, db_sumber):
    c = sqlite3.connect(db_sumber)
    c.execute("UPDATE harga_lapak SET harga_per_kg = 500000 WHERE komoditas_id='cmd_cabai_merah'")
    c.commit()
    c.close()
    h = KONEKTOR_SQL["S1"].baca(mesin, ctx(), sejak=SEJAK, sampai=SAMPAI)
    cabai = next(e for e in h.events if e["payload"]["komoditas_id"] == "cmd_cabai_merah")
    assert cabai["payload"]["flag"] == "perlu_verifikasi"


@pytest.mark.parametrize(
    "sid,tipe",
    [
        ("S2", "stok.berubah"),
        ("S3", "transaksi.dibuat"),
        ("S4", "lapak.status_berubah"),
        ("S5", "panen.dicatat"),
        ("S6", "logistik.biaya_diperbarui"),
        ("S7", "vendor.status_berubah"),
    ],
)
def test_konektor_sql_menghasilkan_event_sah(mesin, sid, tipe):
    h = KONEKTOR_SQL[sid].baca(mesin, ctx(), sejak=SEJAK, sampai=SAMPAI)
    assert [e["event_type"] for e in h.events] == [tipe]
    assert not h.ditolak and h.jumlah_baris_sumber == 1
    assert h.events[0]["event_id"].startswith("evt_20261004_")


def test_s2_snapshot_s10_keuangan(mesin):
    h = baca_snapshot_stok(mesin, ctx(), date(2026, 10, 4))
    assert h.events[0]["event_type"] == "stok.snapshot_harian"
    assert h.events[0]["payload"]["jumlah_baris"] == 1
    h = KONEKTOR_SQL["S10"].baca(mesin, ctx(), tanggal="2026-10-04")
    assert h.events[0]["payload"]["omzet_idr"] == 48250000 and h.events[0]["payload"]["final"]


def test_s8_cuaca_dan_s9_kalender_lewat_fetcher_injeksi():
    h = baca_cuaca(
        lambda d: [{"kabupaten_id": "kab_karawang", "curah_hujan_mm": 12.5, "suhu_avg_c": 28.4}],
        ctx(),
        date(2026, 10, 4),
    )
    assert h.events[0]["event_type"] == "cuaca.diperbarui" and not h.ditolak
    h = baca_kalender(
        lambda th: [{"tanggal": "2027-03-20", "jenis_hari": "puasa", "musim": "peralihan"}],
        ctx(),
        2027,
    )
    assert h.events[0]["event_type"] == "kalender.dikunci"
    assert h.events[0]["payload"]["dikunci_pada"].startswith("2026-12-01")


def test_baris_sumber_buruk_ditandai_bukan_dibuang_diam_diam(mesin, db_sumber):
    c = sqlite3.connect(db_sumber)
    c.execute("UPDATE mutasi_stok SET alasan='ngawur'")
    c.commit()
    c.close()
    h = KONEKTOR_SQL["S2"].baca(mesin, ctx(), sejak=SEJAK, sampai=SAMPAI)
    assert h.events == [] and len(h.ditolak) == 1


def test_generator_event_id_berurutan_per_tanggal():
    g = GeneratorEventId()
    assert g.baru(date(2026, 10, 4)) == "evt_20261004_000001"
    assert g.baru(date(2026, 10, 4)) == "evt_20261004_000002"
    assert g.baru(date(2026, 10, 5)) == "evt_20261005_000001"


# ---------- jadwal dan SLA ----------


def _t(jam, menit=0):
    return datetime(2026, 10, 4, jam, menit, tzinfo=WIB)


def test_jadwal_sesuai_dokumen():
    assert JADWAL["S1"].jatuh_tempo(_t(6)) and JADWAL["S1"].jatuh_tempo(_t(7, 30))
    assert JADWAL["S1"].jatuh_tempo(_t(8)) and not JADWAL["S1"].jatuh_tempo(_t(9))
    assert JADWAL["S1"].jatuh_tempo(_t(14)) and not JADWAL["S1"].jatuh_tempo(_t(14, 1))
    assert JADWAL["S2"].realtime and JADWAL["S2"].jatuh_tempo(_t(23))
    assert JADWAL["S8"].jatuh_tempo(_t(5)) and not JADWAL["S8"].jatuh_tempo(_t(5, 1))
    assert JADWAL["S10"].jatuh_tempo(_t(23, 45)) and not JADWAL["S10"].jatuh_tempo(_t(23, 0))
    assert set(JADWAL) == {f"S{i}" for i in range(1, 11)}


def test_sla_s1_terlambat_dan_kekosongan():
    jadwal = _t(6)
    assert periksa_sla("S1", jadwal, jadwal + timedelta(hours=3), 960, 960) == []
    f = periksa_sla("S1", jadwal, jadwal + timedelta(hours=3, minutes=1), 960, 960)
    assert [x.kode for x in f] == ["sla_terlambat"]
    # kosong 2% tepat lolos, > 2% melanggar
    assert periksa_sla("S1", jadwal, jadwal, 1000, 980) == []
    assert [x.kode for x in periksa_sla("S1", jadwal, jadwal, 1000, 979)] == ["sla_kekosongan"]
    assert {x.kode for x in periksa_sla("S1", jadwal, jadwal + timedelta(hours=4), 1000, 900)} == {
        "sla_terlambat",
        "sla_kekosongan",
    }
    assert periksa_sla("S5", jadwal, jadwal + timedelta(days=9)) == []  # tanpa SLA terdokumentasi


def test_sla_s2_event_masuk_lima_menit():
    t0 = _t(10)
    assert periksa_sla("S2", t0, t0 + timedelta(minutes=5)) == []
    assert periksa_sla("S2", t0, t0 + timedelta(minutes=6))[0].kode == "sla_terlambat"


def test_modul_konektor_tidak_impor_penyimpanan_tulis():
    assert not hasattr(konektor, "create_engine")
    assert hasattr(sumber_readonly, "buka_readonly")
