"""Pelacakan batch harian: `batch_id` + `jumlah_baris`, flag selisih > 5% vs rerata 7 hari.

Aturan Keras V1 butir 3 (data/10-sumber-data.md).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .pengirim import HasilKirim, PengirimEvent

AMBANG_SELISIH = 0.05
JENDELA_HARI = 7


@dataclass(frozen=True)
class FlagBatch:
    kode: str
    pesan: str


@dataclass
class RingkasanBatch:
    batch_id: str
    jumlah_baris: int
    jumlah_dikirim: int
    hasil: list[HasilKirim] = field(default_factory=list)
    flag: list[FlagBatch] = field(default_factory=list)

    @property
    def per_status(self) -> dict[str, int]:
        return dict(Counter(h.status for h in self.hasil))


def periksa_selisih(
    jumlah_baris: int, riwayat: Sequence[int], ambang: float = AMBANG_SELISIH
) -> FlagBatch | None:
    """Flag bila `jumlah_baris` menyimpang > `ambang` dari rerata riwayat (maks 7 hari terakhir).

    Riwayat kosong -> tidak ada pembanding, tidak ada flag (dicatat pemanggil).
    """
    jendela = list(riwayat)[-JENDELA_HARI:]
    if not jendela:
        return None
    rerata = sum(jendela) / len(jendela)
    if rerata == 0:
        menyimpang = jumlah_baris != 0
        persen = float("inf") if menyimpang else 0.0
    else:
        persen = abs(jumlah_baris - rerata) / rerata
        menyimpang = persen > ambang
    if not menyimpang:
        return None
    return FlagBatch(
        "selisih_jumlah_baris",
        f"jumlah_baris {jumlah_baris} menyimpang {persen:.1%} dari rerata "
        f"{len(jendela)} hari ({rerata:.1f}); ambang {ambang:.0%}",
    )


def kirim_batch(
    pengirim: PengirimEvent,
    batch_id: str,
    jumlah_baris: int,
    events: Sequence[dict[str, Any]],
    riwayat_jumlah_baris: Sequence[int] = (),
) -> RingkasanBatch:
    """Kirim satu batch harian; hitung flag. Event beda `batch_id` ditolak lokal."""
    ringkasan = RingkasanBatch(batch_id, jumlah_baris, len(events))

    f = periksa_selisih(jumlah_baris, riwayat_jumlah_baris)
    if f:
        ringkasan.flag.append(f)
    if len(events) != jumlah_baris:
        ringkasan.flag.append(
            FlagBatch(
                "jumlah_baris_tidak_cocok",
                f"batch {batch_id} menyatakan {jumlah_baris} baris tetapi membawa {len(events)}",
            )
        )
    for ev in events:
        if ev.get("batch_id") != batch_id:
            ringkasan.flag.append(
                FlagBatch("batch_id_beda", f"event {ev.get('event_id')} bukan milik {batch_id}")
            )
            continue
        ringkasan.hasil.append(pengirim.kirim(ev))
    return ringkasan
