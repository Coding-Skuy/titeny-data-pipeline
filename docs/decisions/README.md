# Keputusan arsitektur (ADR)

Aturan menambah ADR:

1. **Berurutan**: nomor naik satu per ADR (`ADR-0002-...`, `ADR-0003-...`), tanpa lompat dan tanpa nomor ganda.
2. **Immutable**: ADR yang sudah `Diterima` tidak diedit. Bila keputusan berubah, tulis ADR baru yang menyatakan `Menggantikan: ADR-NNNN` dan ubah hanya baris Status ADR lama menjadi `Digantikan oleh ADR-MMMM`.
3. **Satu keputusan per berkas**: nama `ADR-NNNN-judul-singkat.md`.
4. **Format**: Status, Tanggal (YYYY-MM-DD), Konteks, Keputusan, Konsekuensi.
5. Perubahan kontrak API/event wajib disertai ADR baru + bump versi (tambah field opsional = minor; ubah tipe/makna = mayor + dual-read 30 hari).
6. Requirement bisnis tidak ditulis di sini; requirement berubah = PR di Titeny-TownHall lebih dulu.

| ADR | Judul | Status |
|---|---|---|
| [ADR-0001](./ADR-0001-fondasi-teknis.md) | Fondasi teknis | Diterima |
