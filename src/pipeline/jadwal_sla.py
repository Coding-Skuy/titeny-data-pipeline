"""Frekuensi baca S1-S10 dan SLA keterlambatan (data/10-sumber-data.md). Waktu: Asia/Jakarta.

ASUMSI (dokumen tidak menyebut jam): S4 snapshot harian dijadwalkan 23.00 (sama dengan snapshot
stok S2); S3 memakai agregat harian 23.30 dari `40-TECHSTACK.md` (Jadwal).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")


@dataclass(frozen=True)
class Jadwal:
    realtime: bool = False
    titik: tuple[time, ...] = ()  # waktu tetap harian
    jendela: tuple[tuple[time, time], ...] = ()  # rentang harian [mulai, selesai]
    bulanan_tahunan: str = ""  # keterangan bebas untuk sumber non-harian

    def jatuh_tempo(self, t: datetime) -> bool:
        """Apakah `t` (WIB) berada pada titik/jendela jadwal. Realtime selalu True."""
        if self.realtime:
            return True
        w = t.astimezone(WIB)
        jam = time(w.hour, w.minute)
        return jam in self.titik or any(a <= jam <= b for a, b in self.jendela)


@dataclass(frozen=True)
class SLA:
    maks_terlambat: timedelta
    maks_kekosongan: float | None = None  # pecahan 0..1


JADWAL: dict[str, Jadwal] = {
    # S1 harian 06.00-08.00 + koreksi maks 1x pukul 14.00
    "S1": Jadwal(titik=(time(14, 0),), jendela=((time(6, 0), time(8, 0)),)),
    # S2 mutasi real-time + snapshot 23.00
    "S2": Jadwal(realtime=True, titik=(time(23, 0),)),
    # S3 real-time + agregat harian 23.30
    "S3": Jadwal(realtime=True, titik=(time(23, 30),)),
    # S4 perubahan status real-time + snapshot 1x/hari (jam = asumsi 23.00)
    "S4": Jadwal(realtime=True, titik=(time(23, 0),)),
    # S5 per kejadian panen
    "S5": Jadwal(realtime=True),
    # S6 episodik (biaya diperbarui bila BBM berubah > 5%)
    "S6": Jadwal(realtime=True, bulanan_tahunan="episodik"),
    # S7 perubahan status real-time
    "S7": Jadwal(realtime=True),
    # S8 BMKG harian 05.00
    "S8": Jadwal(titik=(time(5, 0),)),
    # S9 kalender tahunan, dikunci 1 Desember
    "S9": Jadwal(bulanan_tahunan="tahunan, dikunci 1 Desember"),
    # S10 harian 23.45
    "S10": Jadwal(titik=(time(23, 45),)),
}

SLA_SUMBER: dict[str, SLA] = {
    "S1": SLA(timedelta(hours=3), maks_kekosongan=0.02),
    "S2": SLA(timedelta(minutes=5)),  # event masuk < 5 menit dari transaksi gudang
}

S1_TITIK_HARAPAN = 960  # ~120 komoditas x 8 pasar (S1 "Volume")


@dataclass(frozen=True)
class FlagSLA:
    sumber: str
    kode: str
    pesan: str


def periksa_sla(
    sid: str,
    dijadwalkan: datetime,
    tiba: datetime,
    diharapkan: int | None = None,
    diterima: int | None = None,
) -> list[FlagSLA]:
    """Catat pelanggaran SLA keterlambatan/kekosongan; daftar kosong = patuh."""
    sla = SLA_SUMBER.get(sid)
    flag: list[FlagSLA] = []
    if sla is None:
        return flag
    telat = tiba - dijadwalkan
    if telat > sla.maks_terlambat:
        flag.append(
            FlagSLA(
                sid,
                "sla_terlambat",
                f"{sid} terlambat {telat} dari jadwal (maks {sla.maks_terlambat}).",
            )
        )
    if sla.maks_kekosongan is not None and diharapkan:
        kosong = round(max(0.0, 1 - (diterima or 0) / diharapkan), 9)
        if kosong > sla.maks_kekosongan:
            flag.append(
                FlagSLA(
                    sid,
                    "sla_kekosongan",
                    f"{sid} kekosongan {kosong:.1%} dari {diharapkan} titik "
                    f"(maks {sla.maks_kekosongan:.0%}).",
                )
            )
    return flag
