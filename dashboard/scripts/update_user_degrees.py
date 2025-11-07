"""Update dashboard_users degree prefix/suffix from DUK spreadsheet."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional
from zipfile import ZipFile
import xml.etree.ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

DB_ACCESS_PATH = PROJECT_ROOT / "dashboard" / "db_access.py"
spec = importlib.util.spec_from_file_location("dashboard_db_access", DB_ACCESS_PATH)
if spec is None or spec.loader is None:  # pragma: no cover - defensive
    raise RuntimeError("Tidak dapat memuat modul db_access.")
db_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db_module)
get_cursor = db_module.get_cursor

NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@dataclass
class DukRecord:
    name: str
    degree_prefix: Optional[str]
    degree_suffix: Optional[str]


def load_shared_strings(zf: ZipFile) -> list[str]:
    try:
        data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(data)
    strings: list[str] = []
    for si in root.findall("main:si", NS):
        parts: list[str] = []
        for node in si.iter():
            if node.tag.endswith("}t"):
                parts.append(node.text or "")
        strings.append("".join(parts))
    return strings


def column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return 0
    letters = match.group(1)
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def iter_sheet_rows(path: Path, sheet_name: str | None = None) -> Iterable[list[str]]:
    with ZipFile(path) as zf:
        shared = load_shared_strings(zf)
        sheet_path = "xl/worksheets/sheet1.xml" if not sheet_name else f"xl/worksheets/{sheet_name}.xml"
        sheet_data = zf.read(sheet_path)
    root = ET.fromstring(sheet_data)
    for row in root.findall(".//main:row", NS):
        current: list[str] = []
        for cell in row.findall("main:c", NS):
            idx = column_index(cell.get("r", "A"))
            value = ""
            value_node = cell.find("main:v", NS)
            if value_node is not None:
                value = value_node.text or ""
                if cell.get("t") == "s" and value:
                    try:
                        value = shared[int(value)]
                    except (ValueError, IndexError):
                        pass
            while len(current) <= idx:
                current.append("")
            current[idx] = value
        yield current


def normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def extract_records(path: Path) -> Dict[str, DukRecord]:
    rows = list(iter_sheet_rows(path))
    header_idx = None
    for idx, row in enumerate(rows):
        if "NAMA TANPA GELAR" in row:
            header_idx = idx
            break
    if header_idx is None:
        raise RuntimeError("Kolom 'NAMA TANPA GELAR' tidak ditemukan pada file DUK.")
    headers = rows[header_idx]
    try:
        name_idx = headers.index("NAMA TANPA GELAR")
    except ValueError as exc:
        raise RuntimeError("Kolom 'NAMA TANPA GELAR' tidak ditemukan.") from exc
    prefix_idx = headers.index("GELAR DEPAN") if "GELAR DEPAN" in headers else None
    suffix_idx = headers.index("GELAR BELAKANG") if "GELAR BELAKANG" in headers else None

    result: Dict[str, DukRecord] = {}
    for row in rows[header_idx + 1 :]:
        if name_idx >= len(row):
            continue
        name = (row[name_idx] or "").strip()
        if not name:
            continue
        prefix = row[prefix_idx].strip() if prefix_idx is not None and prefix_idx < len(row) else ""
        suffix = row[suffix_idx].strip() if suffix_idx is not None and suffix_idx < len(row) else ""
        def clean(value: str) -> Optional[str]:
            trimmed = (value or "").strip()
            if not trimmed or trimmed == "-":
                return None
            return trimmed
        record = DukRecord(
            name=name,
            degree_prefix=clean(prefix),
            degree_suffix=clean(suffix),
        )
        result[normalize_name(name)] = record
    return result


def update_dashboard_users(records: Dict[str, DukRecord], dry_run: bool = False) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, full_name
            FROM dashboard_users
            """
        )
        users = cur.fetchall()
    updates = []
    missing: list[str] = []
    for row in users:
        normalized = normalize_name(row["full_name"])
        record = records.get(normalized)
        if not record:
            missing.append(row["full_name"])
            continue
        updates.append(
            (record.degree_prefix, record.degree_suffix, row["id"], record.name)
        )

    if dry_run:
        print(f"[DRY-RUN] Akan memperbarui {len(updates)} akun. {len(missing)} akun tidak ditemukan di DUK.")
        if missing:
            print("Nama tidak ditemukan:", ", ".join(sorted(missing)))
        return

    with get_cursor(commit=True) as cur:
        for prefix, suffix, user_id, name_source in updates:
            cur.execute(
                """
                UPDATE dashboard_users
                SET degree_prefix = %s,
                    degree_suffix = %s
                WHERE id = %s
                """,
                (prefix, suffix, user_id),
            )
    print(f"Berhasil memperbarui gelar untuk {len(updates)} akun.")
    if missing:
        print("Perhatian: berikut nama tidak ditemukan pada DUK dan tidak diperbarui:")
        for name in sorted(missing):
            print(f" - {name}")


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Perbarui gelar dashboard_users dari file DUK.")
    parser.add_argument("duk_path", type=Path, help="Path ke file DUK (XLSX).")
    parser.add_argument("--dry-run", action="store_true", help="Tampilkan rencana update tanpa menulis ke database.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.duk_path.exists():
        print(f"File {args.duk_path} tidak ditemukan.", file=sys.stderr)
        return 1

    try:
        records = extract_records(args.duk_path)
    except Exception as exc:  # pragma: no cover
        print(f"Gagal membaca file DUK: {exc}", file=sys.stderr)
        return 1

    update_dashboard_users(records, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
