from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET

from ..db_access import get_cursor

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass
class StudentRow:
    class_name: str
    sequence: Optional[int]
    student_number: Optional[str]
    nisn: Optional[str]
    full_name: str
    gender: Optional[str]
    birth_place: Optional[str] = None
    birth_date: Optional[date] = None
    religion: Optional[str] = None
    address_line: Optional[str] = None
    rt: Optional[str] = None
    rw: Optional[str] = None
    kelurahan: Optional[str] = None
    kecamatan: Optional[str] = None
    father_name: Optional[str] = None
    mother_name: Optional[str] = None
    nik: Optional[str] = None
    kk_number: Optional[str] = None


HEADER_ALIASES = {
    "sequence": {"NO", "NOMOR"},
    "class_label": {"KELAS", "ROMBEL SAAT INI", "ROMBEL"},
    "student_number": {"NIPD", "NIS", "NO INDUK", "NO. INDUK", "NOMOR INDUK"},
    "nisn": {"NISN"},
    "full_name": {"NAMA", "NAMA SISWA", "NAMA PESERTA DIDIK", "NAMA PESERTA  DIDIK"},
    "gender": {"JK", "L/P", "JENIS KELAMIN"},
    "birth_place": {"TEMPAT LAHIR"},
    "birth_date": {"TANGGAL LAHIR"},
    "religion": {"AGAMA"},
    "address_line": {"ALAMAT", "JALAN"},
    "rt": {"RT"},
    "rw": {"RW"},
    "kelurahan": {"KELURAHAN", "KELUARAHAN"},
    "kecamatan": {"KECAMATAN"},
    "father_name": {"AYAH", "NAMA AYAH"},
    "mother_name": {"IBU", "NAMA IBU"},
    "nik": {"NIK"},
    "kk_number": {"NO.KK", "NO. KK", "NOMOR KK"},
}

# Posisi kolom pada template 2025/2026. Dipakai sebagai fallback untuk header
# bertingkat yang memisahkan LAHIR, ALAMAT, dan NAMA ORANG TUA menjadi dua baris.
LEGACY_COLUMN_MAP = {
    "sequence": 2,
    "class_label": 3,
    "student_number": 4,
    "nisn": 5,
    "full_name": 6,
    "gender": 7,
    "birth_place": 8,
    "birth_date": 9,
    "religion": 10,
    "address_line": 11,
    "rt": 12,
    "rw": 13,
    "kelurahan": 14,
    "kecamatan": 15,
    "father_name": 16,
    "mother_name": 17,
    "nik": 18,
    "kk_number": 19,
}


def _load_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings: List[str] = []
    for si in root.findall(f"{{{NS_MAIN}}}si"):
        strings.append("".join(node.text or "" for node in si.findall(f".//{{{NS_MAIN}}}t")))
    return strings


def _resolve_sheets(zf: zipfile.ZipFile) -> List[Tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels_tree = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rels = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels_tree.findall(f"{{{NS_PACKAGE_REL}}}Relationship")
    }
    sheets: List[Tuple[str, str]] = []
    sheet_nodes = workbook.find(f"{{{NS_MAIN}}}sheets")
    if sheet_nodes is None:
        return sheets
    for sheet in sheet_nodes:
        rel_id = sheet.attrib.get(f"{{{NS_REL}}}id")
        target = rels.get(rel_id or "")
        if target:
            sheets.append((sheet.attrib.get("name", "").strip(), target))
    return sheets


def _column_index(cell_reference: str) -> int:
    letters = "".join(char for char in cell_reference.upper() if char.isalpha())
    result = 0
    for char in letters:
        result = result * 26 + (ord(char) - ord("A") + 1)
    return max(0, result - 1)


def _extract_rows(zf: zipfile.ZipFile, target: str, shared: List[str]) -> List[List[str]]:
    clean_target = target.lstrip("/")
    sheet_path = clean_target if clean_target.startswith("xl/") else f"xl/{clean_target}"
    root = ET.fromstring(zf.read(sheet_path))
    data = root.find(f"{{{NS_MAIN}}}sheetData")
    if data is None:
        return []
    rows: List[List[str]] = []
    for row in data.findall(f"{{{NS_MAIN}}}row"):
        values: List[str] = []
        for cell in row.findall(f"{{{NS_MAIN}}}c"):
            index = _column_index(cell.attrib.get("r", "A1"))
            while len(values) <= index:
                values.append("")
            cell_type = cell.attrib.get("t")
            value_node = cell.find(f"{{{NS_MAIN}}}v")
            if cell_type == "inlineStr":
                inline = cell.find(f"{{{NS_MAIN}}}is")
                values[index] = "" if inline is None else "".join(
                    node.text or "" for node in inline.findall(f".//{{{NS_MAIN}}}t")
                )
            elif value_node is not None and value_node.text is not None:
                raw = value_node.text
                if cell_type == "s":
                    shared_index = int(raw)
                    values[index] = shared[shared_index] if shared_index < len(shared) else ""
                else:
                    values[index] = raw
        rows.append(values)
    return rows


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def _normalise_header(value: Optional[str]) -> str:
    return (_clean(value) or "").upper().replace("_", " ")


def _normalise_class(value: Optional[str]) -> Optional[str]:
    cleaned = _normalise_header(value)
    cleaned = re.sub(r"^KELAS\s*", "", cleaned)
    match = re.fullmatch(r"(\d+)\s*([A-Z]+)", cleaned)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    return cleaned or None


def _parse_sequence(value: Optional[str]) -> Optional[int]:
    cleaned = _clean(value)
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _parse_birth_date(value: Optional[str]) -> Optional[date]:
    cleaned = _clean(value)
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    try:
        serial = float(cleaned)
        if 1 <= serial <= 100000:
            return (datetime(1899, 12, 30) + timedelta(days=serial)).date()
    except ValueError:
        pass
    return None


def _find_header(rows: List[List[str]]) -> Tuple[Optional[int], Dict[str, int]]:
    for row_index, row in enumerate(rows[:30]):
        columns: Dict[str, int] = {}
        for column_index, value in enumerate(row):
            header = _normalise_header(value)
            for field, aliases in HEADER_ALIASES.items():
                if header in aliases and field not in columns:
                    columns[field] = column_index
        if "full_name" in columns and ("student_number" in columns or "nisn" in columns):
            return row_index, columns
    return None, {}


def _value(row: List[str], columns: Dict[str, int], field: str) -> Optional[str]:
    index = columns.get(field)
    if index is None or index >= len(row):
        return None
    return _clean(row[index])


def _parse_class_sheet(sheet_name: str, rows: List[List[str]]) -> Iterable[StudentRow]:
    header_index, columns = _find_header(rows)
    if header_index is None:
        return

    if columns.get("full_name") == LEGACY_COLUMN_MAP["full_name"]:
        for field, index in LEGACY_COLUMN_MAP.items():
            columns.setdefault(field, index)

    default_class = _normalise_class(sheet_name)
    for row in rows[header_index + 1 :]:
        full_name = _value(row, columns, "full_name")
        if not full_name:
            continue
        class_name = _normalise_class(_value(row, columns, "class_label")) or default_class
        if not class_name:
            continue
        yield StudentRow(
            class_name=class_name,
            sequence=_parse_sequence(_value(row, columns, "sequence")),
            student_number=_value(row, columns, "student_number"),
            nisn=_value(row, columns, "nisn"),
            full_name=full_name,
            gender=(_value(row, columns, "gender") or "").upper() or None,
            birth_place=_value(row, columns, "birth_place"),
            birth_date=_parse_birth_date(_value(row, columns, "birth_date")),
            religion=_value(row, columns, "religion"),
            address_line=_value(row, columns, "address_line"),
            rt=_value(row, columns, "rt"),
            rw=_value(row, columns, "rw"),
            kelurahan=_value(row, columns, "kelurahan"),
            kecamatan=_value(row, columns, "kecamatan"),
            father_name=_value(row, columns, "father_name"),
            mother_name=_value(row, columns, "mother_name"),
            nik=_value(row, columns, "nik"),
            kk_number=_value(row, columns, "kk_number"),
        )


def _guess_academic_year(rows: List[List[str]]) -> Optional[str]:
    pattern = re.compile(r"(20\d{2}/20\d{2})")
    for row in rows[:15]:
        for cell in row:
            match = pattern.search(str(cell))
            if match:
                return match.group(1)
    return None


def load_students_from_workbook(path: str) -> Tuple[Optional[str], Dict[str, List[StudentRow]]]:
    with zipfile.ZipFile(path) as zf:
        shared = _load_shared_strings(zf)
        academic_year: Optional[str] = None
        classes: Dict[str, List[StudentRow]] = {}
        for sheet_name, target in _resolve_sheets(zf):
            rows = _extract_rows(zf, target, shared)
            if not academic_year:
                academic_year = _guess_academic_year(rows)
            if not sheet_name or sheet_name.upper() in {"REKAP", "SISWA"}:
                continue
            for student in _parse_class_sheet(sheet_name, rows):
                classes.setdefault(student.class_name, []).append(student)
        return academic_year, classes


def _validate_source(classes: Dict[str, List[StudentRow]]) -> None:
    seen_nisn: Dict[str, str] = {}
    seen_numbers: Dict[str, str] = {}
    for students in classes.values():
        for student in students:
            if student.nisn:
                previous = seen_nisn.get(student.nisn)
                if previous:
                    raise ValueError(f"NISN {student.nisn} muncul lebih dari sekali: {previous} dan {student.full_name}.")
                seen_nisn[student.nisn] = student.full_name
            if student.student_number:
                previous = seen_numbers.get(student.student_number)
                if previous:
                    raise ValueError(
                        f"NIPD/NIS {student.student_number} muncul lebih dari sekali: "
                        f"{previous} dan {student.full_name}."
                    )
                seen_numbers[student.student_number] = student.full_name


def _record_history(
    cur,
    student_id: int,
    academic_year: str,
    class_id: int,
    class_name: str,
    student: StudentRow,
    source: str,
) -> None:
    cur.execute(
        """
        INSERT INTO student_class_history (
            student_id, academic_year, class_id, class_name, sequence,
            student_number, nisn, full_name, gender, source
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (student_id, academic_year) DO UPDATE
        SET class_id = EXCLUDED.class_id,
            class_name = EXCLUDED.class_name,
            sequence = EXCLUDED.sequence,
            student_number = EXCLUDED.student_number,
            nisn = EXCLUDED.nisn,
            full_name = EXCLUDED.full_name,
            gender = EXCLUDED.gender,
            source = EXCLUDED.source,
            updated_at = NOW()
        """,
        (
            student_id,
            academic_year,
            class_id,
            class_name,
            student.sequence,
            student.student_number,
            student.nisn,
            student.full_name,
            student.gender,
            source,
        ),
    )


def _canonicalise_existing_class_names(cur, desired_names: Iterable[str]) -> None:
    """Reuse legacy class rows such as ``6C`` when the source says ``6 C``."""
    cur.execute("SELECT id, name FROM school_classes ORDER BY id ASC")
    existing = [dict(row) for row in cur.fetchall()]
    for desired_name in desired_names:
        candidates = [
            row for row in existing if _normalise_class(row["name"]) == desired_name
        ]
        if len(candidates) != 1:
            continue
        candidate = candidates[0]
        if candidate["name"] == desired_name:
            continue
        cur.execute(
            "UPDATE school_classes SET name = %s, updated_at = NOW() WHERE id = %s",
            (desired_name, candidate["id"]),
        )
        candidate["name"] = desired_name


def import_attendance_from_excel(path: str, *, academic_year: Optional[str] = None) -> Dict[str, int]:
    detected_year, classes = load_students_from_workbook(path)
    active_year = (academic_year or detected_year or "").strip()
    if not active_year:
        raise ValueError("Tahun ajaran tidak ditemukan. Gunakan --academic-year, misalnya 2026/2027.")
    if not re.fullmatch(r"20\d{2}/20\d{2}", active_year):
        raise ValueError("Format tahun ajaran harus YYYY/YYYY, misalnya 2026/2027.")
    if not classes:
        raise ValueError("Tidak ada data siswa yang dapat dibaca dari workbook.")
    _validate_source(classes)

    source_name = Path(path).name
    summary = {"classes": len(classes), "students": 0, "inserted": 0, "updated": 0, "inactive": 0}

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO student_class_history (
                student_id, academic_year, class_id, class_name, sequence,
                student_number, nisn, full_name, gender, source
            )
            SELECT s.id, sc.academic_year, sc.id, sc.name, s.sequence,
                   s.student_number, s.nisn, s.full_name, s.gender, 'snapshot-sebelum-import'
            FROM students s
            JOIN school_classes sc ON sc.id = s.class_id
            WHERE sc.academic_year IS NOT NULL
              AND s.active IS TRUE
              AND sc.active IS TRUE
            ON CONFLICT (student_id, academic_year) DO NOTHING
            """
        )

        _canonicalise_existing_class_names(cur, classes.keys())
        cur.execute("UPDATE school_classes SET active = FALSE, updated_at = NOW() WHERE active IS TRUE")
        class_ids: Dict[str, int] = {}
        for class_name in sorted(classes):
            cur.execute(
                """
                INSERT INTO school_classes (name, academic_year, active)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (name) DO UPDATE
                SET academic_year = EXCLUDED.academic_year,
                    active = TRUE,
                    updated_at = NOW()
                RETURNING id
                """,
                (class_name, active_year),
            )
            class_ids[class_name] = int(cur.fetchone()[0])

        cur.execute("SELECT id, student_number, nisn FROM students ORDER BY active DESC, id ASC")
        by_nisn: Dict[str, int] = {}
        by_number: Dict[str, int] = {}
        for record in cur.fetchall():
            if record["nisn"]:
                by_nisn.setdefault(str(record["nisn"]).strip(), int(record["id"]))
            if record["student_number"]:
                by_number.setdefault(str(record["student_number"]).strip(), int(record["id"]))

        cur.execute("UPDATE students SET active = FALSE, updated_at = NOW() WHERE active IS TRUE")
        imported_ids: set[int] = set()

        for class_name in sorted(classes):
            class_id = class_ids[class_name]
            for student in classes[class_name]:
                summary["students"] += 1
                student_id = by_nisn.get(student.nisn) if student.nisn else None
                if student_id is None and student.student_number:
                    student_id = by_number.get(student.student_number)

                if student_id is None:
                    cur.execute(
                        """
                        INSERT INTO students (
                            class_id, full_name, student_number, sequence, nisn, gender,
                            birth_place, birth_date, religion, address_line, rt, rw,
                            kelurahan, kecamatan, father_name, mother_name, nik, kk_number,
                            active, student_status
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, 'aktif')
                        RETURNING id
                        """,
                        (
                            class_id,
                            student.full_name,
                            student.student_number,
                            student.sequence,
                            student.nisn,
                            student.gender,
                            student.birth_place,
                            student.birth_date,
                            student.religion,
                            student.address_line,
                            student.rt,
                            student.rw,
                            student.kelurahan,
                            student.kecamatan,
                            student.father_name,
                            student.mother_name,
                            student.nik,
                            student.kk_number,
                        ),
                    )
                    student_id = int(cur.fetchone()[0])
                    summary["inserted"] += 1
                else:
                    cur.execute(
                        """
                        UPDATE students
                        SET class_id = %s,
                            full_name = %s,
                            student_number = COALESCE(%s, student_number),
                            sequence = %s,
                            nisn = COALESCE(%s, nisn),
                            gender = COALESCE(%s, gender),
                            birth_place = COALESCE(%s, birth_place),
                            birth_date = COALESCE(%s, birth_date),
                            religion = COALESCE(%s, religion),
                            address_line = COALESCE(%s, address_line),
                            rt = COALESCE(%s, rt),
                            rw = COALESCE(%s, rw),
                            kelurahan = COALESCE(%s, kelurahan),
                            kecamatan = COALESCE(%s, kecamatan),
                            father_name = COALESCE(%s, father_name),
                            mother_name = COALESCE(%s, mother_name),
                            nik = COALESCE(%s, nik),
                            kk_number = COALESCE(%s, kk_number),
                            active = TRUE,
                            student_status = 'aktif',
                            exit_date = NULL,
                            exit_reason = NULL,
                            status_updated_at = NOW(),
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (
                            class_id,
                            student.full_name,
                            student.student_number,
                            student.sequence,
                            student.nisn,
                            student.gender,
                            student.birth_place,
                            student.birth_date,
                            student.religion,
                            student.address_line,
                            student.rt,
                            student.rw,
                            student.kelurahan,
                            student.kecamatan,
                            student.father_name,
                            student.mother_name,
                            student.nik,
                            student.kk_number,
                            student_id,
                        ),
                    )
                    summary["updated"] += 1

                if student_id in imported_ids:
                    raise ValueError(f"Siswa {student.full_name} cocok ke identitas yang sama lebih dari sekali.")
                imported_ids.add(student_id)
                _record_history(cur, student_id, active_year, class_id, class_name, student, source_name)

        cur.execute(
            """
            UPDATE students
            SET student_status = 'nonaktif',
                exit_date = NULL,
                exit_reason = NULL,
                status_updated_at = NOW()
            WHERE active IS FALSE
              AND student_status <> 'lulus'
              AND student_status IS DISTINCT FROM 'nonaktif'
            """
        )

        cur.execute("SELECT COUNT(*) FROM students WHERE active IS FALSE")
        summary["inactive"] = int(cur.fetchone()[0])

    print(
        "Import siswa selesai. "
        f"Tahun ajaran: {active_year}; kelas: {summary['classes']}; siswa aktif: {summary['students']}; "
        f"baru: {summary['inserted']}; diperbarui: {summary['updated']}; nonaktif: {summary['inactive']}."
    )
    return summary
