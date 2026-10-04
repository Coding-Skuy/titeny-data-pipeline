> Versi: v1.0.0 | Status: disetujui | Menggantikan: -

# 60-BLAST-RADIUS — titeny-data-pipeline

Mengacu: Titeny-TownHall v1.0.0 (https://github.com/Coding-Skuy/Titeny-TownHall/tree/main/versions/v1.0.0).

## Pernyataan read-only

Repo ini tidak menulis ke DB sumber. Pipeline hanya menarik dari sumber via event dan menulis ke DB `titeny`; tidak pernah menjalankan INSERT/UPDATE/DELETE ke DB Lumbung, TitipO, atau Pasaree.

## Radius Dampak per Perubahan

| Perubahan | Dampak | Batas penahan |
|---|---|---|
| Skema 11 event | Validasi dan DLQ ikut berubah | 11 fixture wajib lolos sebelum rilis |
| Retry/DLQ | Risiko ganda atau hilang | Uji kirim ulang duplikat wajib lolos |
| Batch harian | Flag selisih > 5 persen ikut berubah | Pantau rerata 7 hari tiap batch |
| Kredensial layanan | Salah token menghentikan kirim | Secret per lingkungan, rotasi terjadwal |

## Larangan Eksplisit

- Dilarang menambah string koneksi ke DB sumber.
- Dilarang mengirim `event_type` di luar 11 terkunci.
- Dilarang membawa data pribadi (nama, alamat, telepon) ke Titeny.

## Rollback

Setiap rilis menyimpan pemetaan skema sebelumnya. Rollback berarti mengembalikan pemetaan dan memverifikasi satu event per tipe lolos validasi plus satu duplikat tetap duplikat.

## Batasan

Batasan dokumen ini: hanya radius repo pipeline. Dampak hitung ada di `titeny-ai-models`, dampak simpan ada di `titeny-backend-service`. Insiden DB sumber diteruskan ke pemilik sumber.
