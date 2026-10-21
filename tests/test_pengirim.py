"""TTN-DATA-003: header idempoten, timeout 10 dtk, retry 5/30/300, DLQ + pager, 422 tanpa retry."""

import httpx
import pytest

from pipeline.batch import kirim_batch, periksa_selisih
from pipeline.pengirim import DLQBerkas, KonfigPengirim, PengirimEvent

from .conftest import muat_fixture

TOKEN_RAHASIA = "tok_uji_jangan_bocor"


def bangun(handler, tmp_path, **kw):
    permintaan: list[httpx.Request] = []

    def bungkus(req: httpx.Request) -> httpx.Response:
        permintaan.append(req)
        return handler(req, len(permintaan))

    klien = httpx.Client(base_url="https://titeny.test", transport=httpx.MockTransport(bungkus))
    jeda: list[float] = []
    pager: list[str] = []
    dlq = DLQBerkas(tmp_path / "dlq")
    p = PengirimEvent(
        KonfigPengirim("https://titeny.test", TOKEN_RAHASIA),
        dlq,
        pager=pager.append,
        klien=klien,
        tidur=jeda.append,
        **kw,
    )
    return p, permintaan, jeda, pager, dlq


def test_kirim_sukses_header_idempoten_path_dan_timeout(tmp_path, event_stok):
    p, req, jeda, pager, dlq = bangun(
        lambda r, n: httpx.Response(200, json={"status": "diterima"}), tmp_path
    )
    h = p.kirim(event_stok)
    assert (h.status, h.percobaan) == ("diterima", 1)
    r = req[0]
    assert r.method == "POST" and r.url.path == "/api/v1/event/masuk"
    assert r.headers["X-Idempotency-Key"] == event_stok["event_id"]
    assert r.headers["Authorization"] == f"Bearer {TOKEN_RAHASIA}"
    assert r.extensions["timeout"]["read"] == 10.0 and r.extensions["timeout"]["connect"] == 10.0
    assert jeda == [] and pager == [] and dlq.isi() == []


def test_duplikat_200_dianggap_sukses(tmp_path, event_stok):
    p, *_ = bangun(
        lambda r, n: httpx.Response(200, json={"status": "duplikat_diabaikan"}), tmp_path
    )
    assert p.kirim(event_stok).status == "duplikat_diabaikan"


def test_retry_5_30_300_lalu_sukses_di_percobaan_ke_3(tmp_path, event_stok):
    def h(r, n):
        return httpx.Response(503) if n < 3 else httpx.Response(200, json={"status": "diterima"})

    p, req, jeda, pager, dlq = bangun(h, tmp_path)
    hasil = p.kirim(event_stok)
    assert (hasil.status, hasil.percobaan) == ("diterima", 3)
    assert jeda == [5.0, 30.0]
    assert pager == [] and dlq.isi() == []


def test_gagal_terus_masuk_dlq_dengan_jeda_penuh_dan_pager(tmp_path, event_stok):
    p, req, jeda, pager, dlq = bangun(lambda r, n: httpx.Response(500), tmp_path)
    hasil = p.kirim(event_stok)
    assert hasil.status == "dlq" and hasil.percobaan == 4  # 1 awal + 3 retry
    assert len(req) == 4
    assert jeda == [5.0, 30.0, 300.0]
    assert len(pager) == 1 and event_stok["event_id"] in pager[0]
    baris = dlq.isi()
    assert len(baris) == 1 and baris[0]["event"]["event_id"] == event_stok["event_id"]
    assert baris[0]["alasan"] == "http_500"


def test_timeout_jaringan_diulang_lalu_dlq(tmp_path, event_stok):
    def h(r, n):
        raise httpx.ReadTimeout("lambat", request=r)

    p, req, jeda, pager, dlq = bangun(h, tmp_path)
    hasil = p.kirim(event_stok)
    assert hasil.status == "dlq" and len(req) == 4 and jeda == [5.0, 30.0, 300.0]
    assert dlq.isi()[0]["alasan"].startswith("galat_jaringan:ReadTimeout")


def test_429_diulang(tmp_path, event_stok):
    def h(r, n):
        return httpx.Response(429) if n == 1 else httpx.Response(200, json={"status": "diterima"})

    p, req, jeda, *_ = bangun(h, tmp_path)
    assert p.kirim(event_stok).status == "diterima" and jeda == [5.0]


def test_422_tidak_diretry_dan_tidak_dlq(tmp_path, event_stok):
    bodi = {"status": "ditolak", "alasan": "validasi_gagal", "field": "payload.qty_kg"}
    p, req, jeda, pager, dlq = bangun(lambda r, n: httpx.Response(422, json=bodi), tmp_path)
    hasil = p.kirim(event_stok)
    assert hasil.status == "ditolak" and hasil.field == "payload.qty_kg"
    assert len(req) == 1 and jeda == [] and pager == [] and dlq.isi() == []
    assert p.ditolak == [hasil]


@pytest.mark.parametrize("kode", [400, 401, 403, 409, 413])
def test_4xx_lain_langsung_dlq_tanpa_retry(tmp_path, event_stok, kode):
    p, req, jeda, pager, dlq = bangun(lambda r, n: httpx.Response(kode), tmp_path)
    hasil = p.kirim(event_stok)
    assert hasil.status == "dlq" and len(req) == 1 and jeda == []
    assert len(pager) == 1 and len(dlq.isi()) == 1


def test_401_segarkan_token_sekali_tanpa_menghitung_retry(tmp_path, event_stok):
    def h(r, n):
        if r.headers["Authorization"] == f"Bearer {TOKEN_RAHASIA}":
            return httpx.Response(401)
        return httpx.Response(200, json={"status": "diterima"})

    p, req, jeda, pager, dlq = bangun(h, tmp_path, perbarui_token=lambda: "tok_baru")
    hasil = p.kirim(event_stok)
    assert (hasil.status, hasil.percobaan) == ("diterima", 1)
    assert jeda == []


def test_event_tidak_sah_ditolak_lokal_tanpa_jaringan(tmp_path, event_stok):
    event_stok["event_type"] = "pedaree.stok.v1"
    p, req, jeda, pager, dlq = bangun(lambda r, n: httpx.Response(200), tmp_path)
    hasil = p.kirim(event_stok)
    assert hasil.status == "ditolak" and hasil.alasan == "event_type_tidak_dikenal"
    assert req == []


def test_token_tidak_bocor_ke_repr_dlq_maupun_log(tmp_path, event_stok, caplog):
    p, req, jeda, pager, dlq = bangun(lambda r, n: httpx.Response(500), tmp_path)
    p.kirim(event_stok)
    assert TOKEN_RAHASIA not in repr(p.konfig)
    assert TOKEN_RAHASIA not in dlq.berkas.read_text(encoding="utf-8")
    assert TOKEN_RAHASIA not in caplog.text and TOKEN_RAHASIA not in " ".join(pager)


def test_bawaan_sesuai_kontrak():
    from pipeline.pengirim import JEDA_RETRY_DETIK, TIMEOUT_DETIK

    assert JEDA_RETRY_DETIK == (5.0, 30.0, 300.0) and TIMEOUT_DETIK == 10.0


# --- batch harian ---


@pytest.mark.parametrize(
    "jumlah,riwayat,flag",
    [
        (105, [100] * 7, False),  # tepat 5% -> tidak flag
        (106, [100] * 7, True),  # 6%
        (94, [100] * 7, True),
        (95, [100] * 7, False),
        (50, [], False),  # tanpa pembanding
        (1, [0] * 7, True),
        (0, [0] * 7, False),
        (200, [1000, 1000, *[200] * 7], False),  # hanya 7 terakhir
    ],
)
def test_selisih_batch_ambang_5_persen(jumlah, riwayat, flag):
    assert (periksa_selisih(jumlah, riwayat) is not None) is flag


def _stok(n: int, batch: str) -> dict:
    e = muat_fixture("stok.berubah")
    e["event_id"] = f"evt_20261004_{900 + n:06d}"
    e["batch_id"] = batch
    return e


def test_kirim_batch_membawa_batch_id_dan_menandai_selisih(tmp_path):
    p, req, jeda, pager, dlq = bangun(
        lambda r, n: httpx.Response(200, json={"status": "diterima"}), tmp_path
    )
    evs = [_stok(i, "batch_lumbung_20261004_malam") for i in range(3)]
    r = kirim_batch(p, "batch_lumbung_20261004_malam", 3, evs, riwayat_jumlah_baris=[10] * 7)
    assert r.per_status == {"diterima": 3}
    assert [f.kode for f in r.flag] == ["selisih_jumlah_baris"]
    assert all(q.read().decode().count("batch_lumbung_20261004_malam") for q in req)


def test_kirim_batch_jumlah_baris_tak_cocok_dan_batch_id_beda(tmp_path):
    p, req, *_ = bangun(lambda r, n: httpx.Response(200, json={"status": "diterima"}), tmp_path)
    evs = [_stok(1, "batch_a"), _stok(2, "batch_lain")]
    r = kirim_batch(p, "batch_a", 5, evs)
    assert {f.kode for f in r.flag} == {"jumlah_baris_tidak_cocok", "batch_id_beda"}
    assert len(req) == 1
