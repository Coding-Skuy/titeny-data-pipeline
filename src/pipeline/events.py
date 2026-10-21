"""Registry 11 event terkunci Titeny (data/20-kontrak-event.md §2).

Penambahan event ke-12 hanya lewat bump versi + dual-read 30 hari (ADR baru).
`pedaree.stok.v1` adalah kontrak bilateral Pedaree-TitipO dan BUKAN bagian registry.
"""

EVENT_BAKU: tuple[str, ...] = (
    "harga.diperbarui",
    "stok.berubah",
    "stok.snapshot_harian",
    "transaksi.dibuat",
    "lapak.status_berubah",
    "panen.dicatat",
    "logistik.biaya_diperbarui",
    "vendor.status_berubah",
    "cuaca.diperbarui",
    "kalender.dikunci",
    "keuangan.ringkasan_harian",
)

SUMBER_BAKU: tuple[str, ...] = ("lumbung", "titipo", "pasaree", "cuaca", "internal")

# Sumber yang sah per event_type (kolom "Sumber" §2).
SUMBER_EVENT: dict[str, tuple[str, ...]] = {
    "harga.diperbarui": ("pasaree",),
    "stok.berubah": ("lumbung",),
    "stok.snapshot_harian": ("lumbung",),
    "transaksi.dibuat": ("titipo",),
    "lapak.status_berubah": ("pasaree",),
    "panen.dicatat": ("lumbung",),
    "logistik.biaya_diperbarui": ("titipo", "pasaree"),
    "vendor.status_berubah": ("titipo", "pasaree"),
    "cuaca.diperbarui": ("cuaca",),
    "kalender.dikunci": ("internal",),
    "keuangan.ringkasan_harian": ("lumbung",),
}

# Kunci idempoten bisnis per event_type (§2). Header pengiriman tetap `event_id`.
KUNCI_IDEMPOTEN: dict[str, tuple[str, ...]] = {
    "harga.diperbarui": ("pasar_id", "komoditas_id", "tanggal"),
    "stok.berubah": ("event_id",),
    "stok.snapshot_harian": ("gudang_id", "tanggal"),
    "transaksi.dibuat": ("transaksi_id",),
    "lapak.status_berubah": ("lapak_id", "occurred_at"),
    "panen.dicatat": ("panen_id",),
    "logistik.biaya_diperbarui": ("rute_id", "berlaku_mulai"),
    "vendor.status_berubah": ("vendor_id", "occurred_at"),
    "cuaca.diperbarui": ("kabupaten_id", "tanggal"),
    "kalender.dikunci": ("tahun",),
    "keuangan.ringkasan_harian": ("tanggal",),
}

assert set(SUMBER_EVENT) == set(EVENT_BAKU) == set(KUNCI_IDEMPOTEN)
