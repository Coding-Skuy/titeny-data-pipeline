"""Pengiriman andal event ke `POST /api/v1/event/masuk` (data/20-kontrak-event.md §4).

- Header `X-Idempotency-Key: <event_id>`, timeout 10 detik.
- Retry maks 3x dengan jeda 5, 30, 300 detik (jadi total 4 percobaan) untuk galat
  jaringan/timeout, 429, dan 5xx. Setelah itu event masuk DLQ dan pager berbunyi.
- 422 (`ditolak`) TIDAK di-retry: sumber memperbaiki dan mengirim ulang dengan `event_id` baru.
- 4xx lain (400/401/403/409/413) bukan galat sementara: langsung DLQ + pager, tanpa retry buta.
- DLQ milik pipeline (berkas JSONL lokal), bukan backend.
- Token layanan tidak pernah dicatat/ditampilkan.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

from .skema import EventDitolak, validasi_event

log = logging.getLogger("pipeline.pengirim")

PATH_EVENT = "/api/v1/event/masuk"
TIMEOUT_DETIK = 10.0
JEDA_RETRY_DETIK: tuple[float, ...] = (5.0, 30.0, 300.0)

StatusKirim = Literal["diterima", "duplikat_diabaikan", "ditolak", "dlq"]


@dataclass(frozen=True)
class KonfigPengirim:
    base_url: str
    token: str = field(repr=False)
    timeout: float = TIMEOUT_DETIK
    jeda_retry: tuple[float, ...] = JEDA_RETRY_DETIK

    @classmethod
    def dari_lingkungan(cls) -> KonfigPengirim:
        """Baca `TITENY_BASE_URL` dan `TITENY_SERVICE_TOKEN` (token layanan, peran `layanan`)."""
        return cls(
            base_url=os.environ["TITENY_BASE_URL"].rstrip("/"),
            token=os.environ["TITENY_SERVICE_TOKEN"],
        )


@dataclass(frozen=True)
class HasilKirim:
    event_id: str
    status: StatusKirim
    percobaan: int
    alasan: str = ""
    field: str = ""


class DLQ(Protocol):
    def tambah(self, event: dict[str, Any], alasan: str, percobaan: int) -> None: ...


class DLQBerkas:
    """DLQ sederhana: satu baris JSON per event gagal di `<folder>/dlq.jsonl`."""

    def __init__(self, folder: str | Path):
        self.berkas = Path(folder) / "dlq.jsonl"
        self.berkas.parent.mkdir(parents=True, exist_ok=True)

    def tambah(self, event: dict[str, Any], alasan: str, percobaan: int) -> None:
        baris = {
            "masuk_dlq_pada": datetime.now(UTC).isoformat(),
            "alasan": alasan,
            "percobaan": percobaan,
            "event": event,
        }
        with self.berkas.open("a", encoding="utf-8") as f:
            f.write(json.dumps(baris, ensure_ascii=False) + "\n")

    def isi(self) -> list[dict[str, Any]]:
        if not self.berkas.exists():
            return []
        return [json.loads(b) for b in self.berkas.read_text(encoding="utf-8").splitlines() if b]


Pager = Callable[[str], None]


def pager_log(pesan: str) -> None:
    """Pager bawaan: log level CRITICAL. Sambungan ke pager nyata disuntik oleh infra-devops."""
    log.critical("PAGER: %s", pesan)


def _bisa_diulang(status: int) -> bool:
    return status == 429 or status >= 500


class PengirimEvent:
    def __init__(
        self,
        konfig: KonfigPengirim,
        dlq: DLQ,
        pager: Pager = pager_log,
        klien: httpx.Client | None = None,
        tidur: Callable[[float], None] = time.sleep,
        perbarui_token: Callable[[], str] | None = None,
    ):
        self.konfig = konfig
        self.dlq = dlq
        self.pager = pager
        self.klien = klien or httpx.Client(base_url=konfig.base_url)
        self.tidur = tidur
        self.perbarui_token = perbarui_token
        self.ditolak: list[HasilKirim] = []

    def _tembak(self, event: dict[str, Any], token: str) -> httpx.Response:
        return self.klien.post(
            PATH_EVENT,
            json=event,
            headers={"X-Idempotency-Key": event["event_id"], "Authorization": f"Bearer {token}"},
            timeout=self.konfig.timeout,
        )

    def kirim(self, event: dict[str, Any]) -> HasilKirim:
        eid = str(event.get("event_id", ""))
        try:
            validasi_event(event)  # tolak lebih awal; tidak menghabiskan percobaan jaringan
        except EventDitolak as e:
            return self._ditolak(eid, e.alasan, e.field, 0)

        token = self.konfig.token
        sudah_segarkan = False
        percobaan = 0
        alasan_akhir = ""
        jeda = list(self.konfig.jeda_retry)
        while True:
            percobaan += 1
            try:
                resp = self._tembak(event, token)
            except httpx.TransportError as exc:  # termasuk timeout
                alasan_akhir = f"galat_jaringan:{type(exc).__name__}"
            else:
                kode = resp.status_code
                if kode == 200:
                    status = self._status_200(resp)
                    return HasilKirim(eid, status, percobaan)
                if kode == 422:
                    bodi = _json_aman(resp)
                    return self._ditolak(
                        eid, bodi.get("alasan", "validasi_gagal"), bodi.get("field", ""), percobaan
                    )
                if kode == 401 and self.perbarui_token and not sudah_segarkan:
                    # JWT akses berumur 15 menit: segarkan sekali tanpa menghitung retry.
                    sudah_segarkan = True
                    token = self.perbarui_token()
                    percobaan -= 1
                    continue
                if not _bisa_diulang(kode):
                    return self._ke_dlq(event, eid, f"http_{kode}_tidak_diulang", percobaan)
                alasan_akhir = f"http_{kode}"

            if not jeda:
                return self._ke_dlq(event, eid, alasan_akhir, percobaan)
            self.tidur(jeda.pop(0))

    @staticmethod
    def _status_200(resp: httpx.Response) -> StatusKirim:
        s = _json_aman(resp).get("status")
        return "duplikat_diabaikan" if s == "duplikat_diabaikan" else "diterima"

    def _ditolak(self, eid: str, alasan: str, field_: str, percobaan: int) -> HasilKirim:
        hasil = HasilKirim(eid, "ditolak", percobaan, alasan, field_)
        self.ditolak.append(hasil)
        log.warning(
            "event %s ditolak (%s, %s); perbaiki dan kirim ulang dengan event_id baru",
            eid,
            alasan,
            field_,
        )
        return hasil

    def _ke_dlq(self, event: dict[str, Any], eid: str, alasan: str, percobaan: int) -> HasilKirim:
        self.dlq.tambah(event, alasan, percobaan)
        self.pager(f"event {eid} masuk DLQ setelah {percobaan} percobaan: {alasan}")
        return HasilKirim(eid, "dlq", percobaan, alasan)


def _json_aman(resp: httpx.Response) -> dict[str, Any]:
    try:
        d = resp.json()
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}
