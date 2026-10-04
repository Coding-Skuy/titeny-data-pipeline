"""Definisi 11 event baku Titeny."""
EVENT_BAKU = [
    "lumbung.stok.masuk",
    "lumbung.stok.keluar",
    "lumbung.panen.catat",
    "lumbung.harga.perbarui",
    "titipo.pesanan.buat",
    "titipo.pesanan.antar",
    "titipo.pesanan.batal",
    "pasaree.lapak.buka",
    "pasaree.transaksi.bayar",
    "pasaree.ulasan.kirim",
    "titeny.insight.minta",
]

SUMBER_EVENT = {
    "lumbung.stok.masuk": "Lumbung",
    "lumbung.stok.keluar": "Lumbung",
    "lumbung.panen.catat": "Lumbung",
    "lumbung.harga.perbarui": "Lumbung",
    "titipo.pesanan.buat": "TitipO",
    "titipo.pesanan.antar": "TitipO",
    "titipo.pesanan.batal": "TitipO",
    "pasaree.lapak.buka": "Pasaree",
    "pasaree.transaksi.bayar": "Pasaree",
    "pasaree.ulasan.kirim": "Pasaree",
    "titeny.insight.minta": "Titeny",
}
