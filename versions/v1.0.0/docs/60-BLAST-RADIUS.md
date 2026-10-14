> Versi: v1.0.0 | Status: disetujui | Menggantikan: -

# 60-BLAST-RADIUS — titeny-data-pipeline

Mengacu: Titeny-TownHall v1.0.0 (`https://github.com/Coding-Skuy/Titeny-TownHall/tree/main/platform/versions/v1.0.0`), [`townhall-roadmap.md` bagian 2](https://github.com/Coding-Skuy/ChefGenie-TownHall/blob/main/townhall-roadmap.md) (baris Titeny: point of concern "11 event; MAPE H+1 <= 8%"; batas context "12 komoditas x 8 pasar; read-only ke DB sumber") dan [`KONTEKS-LINTAS-DIVISI.md` bagian 8-9](https://github.com/Coding-Skuy/ChefGenie-TownHall/blob/main/KONTEKS-LINTAS-DIVISI.md).

## Pernyataan read-only

Repo ini tidak menulis ke DB sumber. Titeny hanya membaca dari Lumbung, TitipO, dan Pasaree (lewat event/konektor SELECT); satu-satunya basis tulis adalah DB `titeny`.

## Yang BOLEH disentuh repo ini

Kode validasi, konektor read-only S1-S10, pengirim httpx, DLQ, rekalkulasi H-1, arsip dingin, fixture event; menulis ke DB `titeny` lewat API/agregat.

## Yang DILARANG

- Menambah string koneksi dengan hak tulis ke DB Lumbung, TitipO, atau Pasaree (konektor hanya SELECT).
- Mengirim `event_type` di luar 11 terkunci; membawa data pribadi ke Titeny.
- Mengubah skema payload tanpa bump `schema_version` + ADR baru.
- Mengirim ulang dengan `event_id` sama setelah 422 (sumber wajib memakai `event_id` baru).

## Kontrak

- **Dikonsumsi**: Data S1-S10 dari Lumbung, TitipO, Pasaree, BMKG, kalender internal (read-only); kontrak `data/20-kontrak-event.md`.
- **Diproduksi**: 11 event terkunci ke `POST /api/v1/event/masuk` (`titeny-backend-service`); arsip dingin + manifest; jejak batch (`batch_id`, `jumlah_baris`).
- Modul bersama `:shared:pantry-resep` adalah milik Pawonee dan tidak dipakai atau diubah oleh Titeny. `pedaree.stok.v1` adalah kontrak bilateral Pedaree-TitipO dan bukan bagian registry Titeny (11 event terkunci).

## Radius Dampak per Perubahan

| Perubahan | Dampak | Batas penahan |
|---|---|---|
| Skema 11 event | Validasi dan DLQ ikut berubah | 11 fixture wajib lolos sebelum rilis |
| Retry/DLQ | Risiko ganda atau hilang | Uji kirim ulang duplikat wajib lolos |
| Batch harian | Flag selisih > 5 persen ikut berubah | Pantau rerata 7 hari tiap batch |
| Kredensial layanan | Salah token menghentikan kirim | Secret per lingkungan, rotasi terjadwal |

## Rollback

Setiap rilis menyimpan pemetaan skema sebelumnya. Rollback berarti mengembalikan pemetaan dan memverifikasi satu event per tipe lolos validasi plus satu duplikat tetap duplikat.

## Batasan

Dokumen ini hanya mengatur radius repo `titeny-data-pipeline`. Dampak repo lain ada di dokumen blast-radius repo tersebut. Insiden DB sumber diteruskan ke pemilik sumber.
