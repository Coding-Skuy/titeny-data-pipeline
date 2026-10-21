# CHANGELOG — titeny-data-pipeline

Format: satu seksi per rilis, terbaru di atas. Wajib diperbarui pada setiap commit `feat:` / `fix:` / `docs:`.

## [Belum dirilis]

### Ditambahkan
- TTN-DATA-003: pengirim andal (`pengirim.py`): `X-Idempotency-Key`, timeout 10 dtk, retry 5/30/300 dtk, DLQ berkas + pager, 422 tanpa retry; pelacakan batch harian dengan flag selisih > 5% vs rerata 7 hari (`batch.py`).
- TTN-DATA-002: registry 11 event terkunci (`events.py`), skema pydantic amplop + 11 payload (`skema.py`), gerbang uji idempoten (`gerbang.py`), 11 fixture di `tests/fixtures/events/`, uji pytest; `event_type` ke-12 ditolak `event_type_tidak_dikenal`.
- Konfigurasi pytest (`pythonpath`) dan ruff di `pyproject.toml`.
- Fondasi AI-dev v1.0.0: `AGENTS.md`, `CLAUDE.md`, `docs/decisions/ADR-0001-fondasi-teknis.md`, `versions/v1.0.0/docs/40-TECHSTACK.md` dan `60-BLAST-RADIUS.md` (versi lengkap, menggantikan ringkasan awal).
