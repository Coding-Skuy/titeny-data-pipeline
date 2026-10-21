"""Gerbang penerima lokal: meniru kontrak `POST /api/v1/event/masuk` untuk uji.

Bukan pengganti backend-service. Dipakai uji agar validasi + idempotensi (`event_id`
duplikat -> `duplikat_diabaikan`, tanpa baris ganda) dapat dibuktikan tanpa jaringan.
"""

from __future__ import annotations

from typing import Any

from .skema import EventDitolak, EventTerverifikasi, validasi_event


class GerbangEvent:
    def __init__(self) -> None:
        self._baris: dict[str, EventTerverifikasi] = {}

    @property
    def jumlah_baris(self) -> int:
        return len(self._baris)

    def terima(self, mentah: dict[str, Any]) -> dict[str, str]:
        """Kembalikan bodi 200; lempar `EventDitolak` (setara 422) bila tidak sah."""
        event = validasi_event(mentah)
        if event.amplop.event_id in self._baris:
            return {"status": "duplikat_diabaikan"}
        self._baris[event.amplop.event_id] = event
        return {"status": "diterima"}

    def semua(self) -> list[EventTerverifikasi]:
        return list(self._baris.values())


__all__ = ["EventDitolak", "GerbangEvent"]
