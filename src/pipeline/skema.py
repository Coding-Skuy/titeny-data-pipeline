"""Skema pydantic 11 event terkunci + amplop (data/20-kontrak-event.md §1-§3).

Aturan payload yang ditegakkan (selaras docs/api/openapi.yaml backend-service):
- `harga.diperbarui`: `jumlah_sampel_lapak` < 3 wajib `flag = perlu_verifikasi`.
- `transaksi.dibuat`: `qty_kg` maks 50 kg (> 50 ditolak; lihat catatan asumsi di PR).
- `panen.dicatat`: hasil/ha di luar 500-15.000 kg/ha wajib `keterangan` (diterima, bertanda
  `perlu_verifikasi`); tanpa keterangan ditolak.
- Data pribadi tidak punya tempat di skema (`extra="forbid"`): kolom tak dikenal ditolak.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .events import EVENT_BAKU, SUMBER_BAKU, SUMBER_EVENT

QTY_MAKS_KG = 50
HASIL_PER_HA_MIN = 500
HASIL_PER_HA_MAKS = 15_000
SAMPEL_MIN = 3

POLA_EVENT_ID = re.compile(r"^evt_\d{8}_\d{6}$")

Kg = Annotated[float, Field(ge=0)]
IdRupiah = Annotated[int, Field(ge=0)]


class _Dasar(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)


class HargaDiperbarui(_Dasar):
    pasar_id: str = Field(min_length=1)
    komoditas_id: str = Field(min_length=1)
    tanggal: date
    harga_per_kg: int = Field(gt=0, description="IDR integer > 0")
    satuan: Literal["kg"]
    jumlah_sampel_lapak: int = Field(ge=0)
    flag: Literal["ok", "perlu_verifikasi"]

    @model_validator(mode="after")
    def _sampel_cukup_atau_ditandai(self) -> HargaDiperbarui:
        if self.jumlah_sampel_lapak < SAMPEL_MIN and self.flag != "perlu_verifikasi":
            raise ValueError(
                f"jumlah_sampel_lapak kurang dari {SAMPEL_MIN}: flag wajib perlu_verifikasi"
            )
        return self


class StokBerubah(_Dasar):
    gudang_id: str = Field(min_length=1)
    komoditas_id: str = Field(min_length=1)
    perubahan_kg: float
    stok_akhir_kg: float = Field(ge=0, description="stok tidak boleh negatif (S2)")
    alasan: Literal["masuk_panen", "masuk_beli", "keluar_penjualan", "susut", "koreksi_opname"]


class BarisStok(_Dasar):
    komoditas_id: str = Field(min_length=1)
    stok_kg: Kg


class StokSnapshotHarian(_Dasar):
    gudang_id: str = Field(min_length=1)
    tanggal: date
    baris: list[BarisStok]
    jumlah_baris: int = Field(ge=0)

    @model_validator(mode="after")
    def _jumlah_baris_cocok(self) -> StokSnapshotHarian:
        if self.jumlah_baris != len(self.baris):
            raise ValueError("jumlah_baris tidak sama dengan banyaknya baris")
        return self


class TransaksiDibuat(_Dasar):
    transaksi_id: str = Field(min_length=1)
    komoditas_id: str = Field(min_length=1)
    qty_kg: float = Field(gt=0, le=QTY_MAKS_KG)
    harga_satuan: int = Field(gt=0)
    vendor_id: str = Field(min_length=1)
    zona_rute: str = Field(min_length=1)
    waktu: datetime


class LapakStatusBerubah(_Dasar):
    lapak_id: str = Field(min_length=1)
    status: Literal["aktif", "tutup", "libur"]
    komoditas_utama: str = Field(min_length=1)


class PanenDicatat(_Dasar):
    panen_id: str = Field(min_length=1)
    komoditas_id: str = Field(min_length=1)
    lahan_ha: float = Field(gt=0)
    hasil_kg: Kg
    tanggal_panen: date
    mutu: Literal["A", "B", "C"]
    kabupaten_id: str = Field(min_length=1)
    keterangan: str = ""

    @property
    def hasil_per_ha(self) -> float:
        return self.hasil_kg / self.lahan_ha

    @property
    def perlu_verifikasi(self) -> bool:
        return not (HASIL_PER_HA_MIN <= self.hasil_per_ha <= HASIL_PER_HA_MAKS)

    @model_validator(mode="after")
    def _di_luar_rentang_wajib_keterangan(self) -> PanenDicatat:
        if self.perlu_verifikasi and not self.keterangan.strip():
            raise ValueError(
                f"hasil per hektare {self.hasil_per_ha:.0f} kg/ha di luar "
                f"{HASIL_PER_HA_MIN}-{HASIL_PER_HA_MAKS:,} kg/ha: keterangan wajib diisi".replace(
                    ",", "."
                )
            )
        return self


class LogistikBiayaDiperbarui(_Dasar):
    rute_id: str = Field(min_length=1)
    jarak_km: float = Field(gt=0)
    biaya_per_kg: int = Field(ge=0)
    moda: Literal["motor", "mobil_pickup", "truk"]
    berlaku_mulai: date
    sebab: str = Field(min_length=1)


class VendorStatusBerubah(_Dasar):
    vendor_id: str = Field(min_length=1)
    jenis: Literal["keliling", "lapak", "produsen"]
    status_aktif: bool
    zona_operasi: str = Field(min_length=1)
    kapasitas_harian_kg: Kg


class CuacaDiperbarui(_Dasar):
    kabupaten_id: str = Field(min_length=1)
    tanggal: date
    curah_hujan_mm: float = Field(ge=0)
    suhu_avg_c: float
    peringatan: Literal["tidak_ada", "banjir", "kekeringan"]


class BarisKalender(_Dasar):
    tanggal: date
    jenis_hari: Literal["biasa", "puasa", "lebaran", "natal", "tahun_baru", "panen_raya"]
    musim: Literal["hujan", "kemarau", "peralihan"]


class KalenderDikunci(_Dasar):
    tahun: int = Field(ge=2000, le=2100)
    baris: list[BarisKalender]
    jumlah_baris: int = Field(ge=0)
    dikunci_pada: datetime

    @model_validator(mode="after")
    def _jumlah_baris_cocok(self) -> KalenderDikunci:
        if self.jumlah_baris != len(self.baris):
            raise ValueError("jumlah_baris tidak sama dengan banyaknya baris")
        return self


class KeuanganRingkasanHarian(_Dasar):
    tanggal: date
    omzet_idr: IdRupiah
    margin_kotor_idr: int
    biaya_operasional_idr: IdRupiah
    piutang_idr: IdRupiah
    final: bool


SKEMA_PAYLOAD: dict[str, type[BaseModel]] = {
    "harga.diperbarui": HargaDiperbarui,
    "stok.berubah": StokBerubah,
    "stok.snapshot_harian": StokSnapshotHarian,
    "transaksi.dibuat": TransaksiDibuat,
    "lapak.status_berubah": LapakStatusBerubah,
    "panen.dicatat": PanenDicatat,
    "logistik.biaya_diperbarui": LogistikBiayaDiperbarui,
    "vendor.status_berubah": VendorStatusBerubah,
    "cuaca.diperbarui": CuacaDiperbarui,
    "kalender.dikunci": KalenderDikunci,
    "keuangan.ringkasan_harian": KeuanganRingkasanHarian,
}
assert set(SKEMA_PAYLOAD) == set(EVENT_BAKU)


class Amplop(_Dasar):
    event_id: str
    event_type: str
    schema_version: int = Field(ge=1)
    source: str
    occurred_at: datetime
    received_at: datetime
    batch_id: str = Field(min_length=1)
    payload: dict[str, Any]

    @field_validator("event_id")
    @classmethod
    def _format_event_id(cls, v: str) -> str:
        if not POLA_EVENT_ID.match(v):
            raise ValueError("event_id harus berformat evt_YYYYMMDD_NNNNNN")
        return v


class EventDitolak(Exception):
    """Event gagal validasi. `alasan`/`field` setara bodi 422 backend (`ditolak`)."""

    def __init__(self, alasan: str, field: str, pesan: str):
        super().__init__(pesan)
        self.alasan = alasan
        self.field = field
        self.pesan = pesan

    def ke_bodi(self) -> dict[str, str]:
        return {
            "status": "ditolak",
            "alasan": self.alasan,
            "field": self.field,
            "pesan": self.pesan,
        }


class EventTerverifikasi(BaseModel):
    """Hasil validasi sukses: amplop + payload bertipe + penanda verifikasi."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    amplop: Amplop
    payload: BaseModel
    perlu_verifikasi: bool = False


def _lokasi(err: dict[str, Any], awalan: str = "") -> str:
    loc = ".".join(str(p) for p in err["loc"] if p != "__root__")
    return f"{awalan}{loc}" if loc else awalan.rstrip(".")


_PESAN_TIPE = {
    "missing": "field wajib ada",
    "extra_forbidden": "field tidak dikenal atau tidak diizinkan (data pribadi dilarang)",
    "literal_error": "nilai di luar daftar yang diizinkan",
    "greater_than": "nilai harus lebih besar dari batas minimum",
    "greater_than_equal": "nilai kurang dari batas minimum",
    "less_than_equal": "nilai melebihi batas maksimum",
    "int_parsing": "harus bilangan bulat",
    "int_from_float": "harus bilangan bulat (tanpa desimal)",
    "float_parsing": "harus angka",
    "date_from_datetime_inexact": "harus tanggal (YYYY-MM-DD)",
    "date_parsing": "harus tanggal (YYYY-MM-DD)",
    "datetime_parsing": "harus waktu ISO-8601",
    "string_type": "harus teks",
    "bool_parsing": "harus true/false",
    "string_too_short": "teks tidak boleh kosong",
}


def _pesan(err: dict[str, Any]) -> str:
    if err["type"] == "value_error":
        return str(err["msg"]).removeprefix("Value error, ")
    return _PESAN_TIPE.get(err["type"], "nilai tidak valid")


def validasi_event(mentah: dict[str, Any]) -> EventTerverifikasi:
    """Validasi satu event penuh. Melempar `EventDitolak` (pesan Bahasa Indonesia)."""
    if not isinstance(mentah, dict):
        raise EventDitolak("validasi_gagal", "", "Event harus berupa objek JSON.")

    tipe = mentah.get("event_type")
    if tipe not in SKEMA_PAYLOAD:
        raise EventDitolak(
            "event_type_tidak_dikenal",
            "event_type",
            f"event_type '{tipe}' tidak termasuk 11 event terkunci.",
        )

    try:
        amplop = Amplop.model_validate(mentah)
    except ValidationError as exc:
        e = exc.errors()[0]
        raise EventDitolak("validasi_gagal", _lokasi(e), _pesan(e)) from exc

    if amplop.source not in SUMBER_BAKU:
        raise EventDitolak(
            "validasi_gagal", "source", f"source harus salah satu dari {', '.join(SUMBER_BAKU)}."
        )
    if amplop.source not in SUMBER_EVENT[tipe]:
        raise EventDitolak(
            "validasi_gagal",
            "source",
            f"event {tipe} hanya boleh dikirim oleh {' / '.join(SUMBER_EVENT[tipe])}.",
        )
    if amplop.schema_version != 1:
        raise EventDitolak(
            "validasi_gagal", "schema_version", "schema_version yang didukung hanya 1."
        )

    try:
        payload = SKEMA_PAYLOAD[tipe].model_validate(amplop.payload)
    except ValidationError as exc:
        e = exc.errors()[0]
        raise EventDitolak("validasi_gagal", _lokasi(e, "payload."), _pesan(e)) from exc

    perlu = bool(
        getattr(payload, "flag", None) == "perlu_verifikasi"
        or getattr(payload, "perlu_verifikasi", False)
    )
    return EventTerverifikasi(amplop=amplop, payload=payload, perlu_verifikasi=perlu)
