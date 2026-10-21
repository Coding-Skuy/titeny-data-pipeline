"""Akses DB sumber (Lumbung, TitipO, Pasaree) yang ketat read-only (US-006, TTN-DATA-004).

Tiga lapis pertahanan, semuanya wajib:
1. Audit string koneksi: ditolak bila tidak ada penanda read-only (Postgres:
   `default_transaction_read_only=on` + nama peran berakhiran `_ro`; SQLite: `mode=ro`).
2. Sesi read-only di sisi DB (Postgres `default_transaction_read_only`, SQLite `query_only`).
3. Penjaga pernyataan: hanya satu `SELECT`/`WITH ... SELECT`; kata kunci tulis ditolak
   (`TulisDitolak`) SEBELUM sampai ke driver.

Satu-satunya basis tulis Titeny adalah DB logis `titeny` (lihat `penyimpanan.py`).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from sqlalchemy import Engine, create_engine, event, text

KATA_KUNCI_TULIS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "MERGE",
    "REPLACE",
    "COPY",
    "CALL",
    "EXEC",
    "EXECUTE",
    "VACUUM",
    "ATTACH",
    "PRAGMA",
    "SET",
    "LOCK",
)
_POLA_TULIS = re.compile(r"\b(" + "|".join(KATA_KUNCI_TULIS) + r")\b", re.IGNORECASE)
_POLA_KOMENTAR = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_POLA_LITERAL = re.compile(r"'(?:[^']|'')*'")
_POLA_PERAN_RO = re.compile(r"(_ro|_readonly)$", re.IGNORECASE)


class TulisDitolak(Exception):
    """Pernyataan SQL bukan SELECT murni ke DB sumber."""


class KoneksiTidakReadOnly(Exception):
    """String koneksi sumber tidak membuktikan akses read-only."""


def pastikan_select(sql: str) -> str:
    """Kembalikan `sql` bila SELECT murni; lempar `TulisDitolak` bila tidak."""
    bersih = _POLA_LITERAL.sub("''", _POLA_KOMENTAR.sub(" ", sql)).strip()
    if bersih.endswith(";"):
        bersih = bersih[:-1].rstrip()
    if ";" in bersih:
        raise TulisDitolak("Beberapa pernyataan sekaligus ke DB sumber ditolak.")
    awal = bersih.split(None, 1)[0].upper() if bersih else ""
    if awal not in ("SELECT", "WITH"):
        raise TulisDitolak(f"Hanya SELECT yang boleh ke DB sumber, bukan '{awal or '(kosong)'}'.")
    m = _POLA_TULIS.search(bersih)
    if m:
        raise TulisDitolak(f"Kata kunci tulis '{m.group(1).upper()}' dilarang ke DB sumber.")
    return sql


def audit_string_koneksi(url: str) -> list[str]:
    """Daftar pelanggaran (kosong = lolos audit read-only)."""
    u = urlparse(url)
    skema = u.scheme.split("+")[0]
    q = {k: [unquote(x) for x in v] for k, v in parse_qs(u.query).items()}
    masalah: list[str] = []
    if skema == "sqlite":
        if "mode=ro" not in url:
            masalah.append("SQLite wajib `mode=ro` (uri=true).")
    elif skema in ("postgresql", "postgres"):
        if not u.username or not _POLA_PERAN_RO.search(u.username):
            masalah.append("Peran Postgres wajib berakhiran `_ro` atau `_readonly`.")
        opsi = " ".join(q.get("options", []))
        if not re.search(r"default_transaction_read_only[= ]+(on|true)", opsi, re.IGNORECASE):
            masalah.append("Wajib `options=-c default_transaction_read_only=on` di string koneksi.")
    else:
        masalah.append(f"Skema koneksi '{skema}' tidak didukung untuk DB sumber.")
    return masalah


def buka_readonly(url: str) -> Engine:
    """Buka engine read-only ke DB sumber. Gagal bila audit string koneksi tidak lolos."""
    masalah = audit_string_koneksi(url)
    if masalah:
        raise KoneksiTidakReadOnly("; ".join(masalah))
    mesin = create_engine(url)

    @event.listens_for(mesin, "before_cursor_execute")
    def _jaga(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if executemany:
            raise TulisDitolak("executemany ditolak ke DB sumber.")
        pastikan_select(statement)

    if mesin.dialect.name == "sqlite":

        @event.listens_for(mesin, "connect")
        def _sqlite_ro(dbapi_conn, _rec):  # noqa: ANN001
            dbapi_conn.execute("PRAGMA query_only = ON")

    return mesin


def baca(mesin: Engine, sql: str, **param: Any) -> list[dict[str, Any]]:
    """Jalankan SELECT dan kembalikan baris sebagai dict. Satu-satunya jalur baca sumber."""
    pastikan_select(sql)
    with mesin.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), param)]
