"""TTN-DATA-002: 11 fixture lolos, aturan payload, duplikat, event ke-12 ditolak."""

import copy
import json
from pathlib import Path

import pytest

from pipeline.events import EVENT_BAKU
from pipeline.gerbang import GerbangEvent
from pipeline.skema import EventDitolak, validasi_event

DIR = Path(__file__).parent / "fixtures" / "events"
BERKAS = sorted(DIR.glob("*.json"))


def muat(tipe: str) -> dict:
    for b in BERKAS:
        d = json.loads(b.read_text(encoding="utf-8"))
        if d["event_type"] == tipe:
            return copy.deepcopy(d)
    raise AssertionError(tipe)


def test_tepat_11_fixture_satu_per_tipe():
    assert len(BERKAS) == 11
    tipe = sorted(json.loads(b.read_text())["event_type"] for b in BERKAS)
    assert tipe == sorted(EVENT_BAKU)


@pytest.mark.parametrize("berkas", BERKAS, ids=lambda b: b.stem)
def test_fixture_lolos(berkas):
    hasil = validasi_event(json.loads(berkas.read_text(encoding="utf-8")))
    assert hasil.amplop.event_type in EVENT_BAKU
    assert hasil.perlu_verifikasi is False


def test_registry_tepat_11_dan_tanpa_nama_lama():
    assert len(EVENT_BAKU) == 11 == len(set(EVENT_BAKU))
    assert not any(n.startswith(("lumbung.", "titipo.", "pasaree.", "titeny.")) for n in EVENT_BAKU)


def test_duplikat_event_id_tanpa_baris_ganda():
    g = GerbangEvent()
    e = muat("stok.berubah")
    assert g.terima(e) == {"status": "diterima"}
    assert g.terima(copy.deepcopy(e)) == {"status": "duplikat_diabaikan"}
    assert g.jumlah_baris == 1


@pytest.mark.parametrize("tipe", ["pedaree.stok.v1", "stok.berubah.v2", "titeny.insight.minta", ""])
def test_event_ke_12_ditolak(tipe):
    e = muat("stok.berubah")
    e["event_type"] = tipe
    with pytest.raises(EventDitolak) as ex:
        validasi_event(e)
    assert ex.value.alasan == "event_type_tidak_dikenal"
    assert ex.value.ke_bodi()["status"] == "ditolak"


def test_harga_sampel_kurang_tanpa_flag_ditolak_dengan_pesan_indonesia():
    e = muat("harga.diperbarui")
    e["payload"]["jumlah_sampel_lapak"] = 2
    with pytest.raises(EventDitolak) as ex:
        validasi_event(e)
    assert ex.value.field == "payload"
    assert "flag wajib perlu_verifikasi" in ex.value.pesan


def test_harga_sampel_kurang_dengan_flag_diterima_bertanda():
    e = muat("harga.diperbarui")
    e["payload"].update(jumlah_sampel_lapak=2, flag="perlu_verifikasi")
    assert validasi_event(e).perlu_verifikasi is True


def test_harga_tepat_3_sampel_lolos():
    e = muat("harga.diperbarui")
    e["payload"]["jumlah_sampel_lapak"] = 3
    assert validasi_event(e).perlu_verifikasi is False


def test_qty_50_lolos_51_ditolak():
    e = muat("transaksi.dibuat")
    e["payload"]["qty_kg"] = 50
    validasi_event(e)
    e["payload"]["qty_kg"] = 50.01
    with pytest.raises(EventDitolak) as ex:
        validasi_event(e)
    assert ex.value.field == "payload.qty_kg"
    assert "maksimum" in ex.value.pesan


@pytest.mark.parametrize("hasil,lolos", [(500, True), (15000, True), (499, False), (15001, False)])
def test_hasil_per_ha_batas_tanpa_keterangan(hasil, lolos):
    e = muat("panen.dicatat")
    e["payload"].update(lahan_ha=1, hasil_kg=hasil, keterangan="")
    if lolos:
        assert validasi_event(e).perlu_verifikasi is False
    else:
        with pytest.raises(EventDitolak) as ex:
            validasi_event(e)
        assert "keterangan wajib diisi" in ex.value.pesan


def test_hasil_per_ha_di_luar_rentang_dengan_keterangan_diterima_bertanda():
    e = muat("panen.dicatat")
    e["payload"].update(lahan_ha=1, hasil_kg=20000, keterangan="lahan intensif, sudah dicek")
    assert validasi_event(e).perlu_verifikasi is True


def test_data_pribadi_ditolak():
    e = muat("transaksi.dibuat")
    e["payload"]["nama_pembeli"] = "Budi"
    with pytest.raises(EventDitolak) as ex:
        validasi_event(e)
    assert ex.value.field == "payload.nama_pembeli"
    assert "data pribadi" in ex.value.pesan


def test_source_tidak_sah_ditolak():
    e = muat("harga.diperbarui")
    e["source"] = "lumbung"
    with pytest.raises(EventDitolak) as ex:
        validasi_event(e)
    assert ex.value.field == "source"
    e["source"] = "bmkg"
    with pytest.raises(EventDitolak):
        validasi_event(e)


def test_format_event_id_dan_field_wajib():
    e = muat("cuaca.diperbarui")
    e["event_id"] = "evt_2026_1"
    with pytest.raises(EventDitolak) as ex:
        validasi_event(e)
    assert ex.value.field == "event_id"
    e = muat("cuaca.diperbarui")
    del e["batch_id"]
    with pytest.raises(EventDitolak) as ex:
        validasi_event(e)
    assert ex.value.field == "batch_id"
    assert ex.value.pesan == "field wajib ada"


def test_jumlah_baris_snapshot_dan_kalender_harus_cocok():
    for tipe in ("stok.snapshot_harian", "kalender.dikunci"):
        e = muat(tipe)
        e["payload"]["jumlah_baris"] = 99
        with pytest.raises(EventDitolak):
            validasi_event(e)


def test_stok_negatif_ditolak():
    e = muat("stok.berubah")
    e["payload"]["stok_akhir_kg"] = -1
    with pytest.raises(EventDitolak):
        validasi_event(e)


def test_harga_pecahan_idr_ditolak():
    e = muat("harga.diperbarui")
    e["payload"]["harga_per_kg"] = 42000.5
    with pytest.raises(EventDitolak):
        validasi_event(e)


def test_ingest_validasi_berkas_menyaring_per_sumber(tmp_path):
    from pipeline import ingest_lumbung, ingest_pasaree, ingest_titipo

    semua = [json.loads(b.read_text(encoding="utf-8")) for b in BERKAS]
    jalur = tmp_path / "semua.json"
    jalur.write_text(json.dumps(semua), encoding="utf-8")
    assert ingest_lumbung.validasi_berkas(str(jalur)) == 4
    assert ingest_pasaree.validasi_berkas(str(jalur)) == 2
    assert ingest_titipo.validasi_berkas(str(jalur)) == 3
