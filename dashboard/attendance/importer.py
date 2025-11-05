from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, date
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .queries import create_school_class as _create_school_class
    from .queries import create_student as _create_student

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
    birth_place: Optional[str]
    birth_date: Optional[date]
    religion: Optional[str]
    address_line: Optional[str]
    rt: Optional[str]
    rw: Optional[str]
    kelurahan: Optional[str]
    kecamatan: Optional[str]
    father_name: Optional[str]
    mother_name: Optional[str]
    nik: Optional[str]
    kk_number: Optional[str]


def _load_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings: List[str] = []
    for si in root.findall(f"{{{NS_MAIN}}}si"):
        text = "".join(node.text or "" for node in si.findall(f".//{{{NS_MAIN}}}t"))
        strings.append(text)
    return strings


def _resolve_sheets(zf: zipfile.ZipFile) -> List[Tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels_tree = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rels: Dict[str, str] = {}
    for rel in rels_tree.findall(f"{{{NS_PACKAGE_REL}}}Relationship"):
        rels[rel.attrib["Id"]] = rel.attrib["Target"]

    sheets: List[Tuple[str, str]] = []
    for sheet in workbook.find(f"{{{NS_MAIN}}}sheets"):
        rel_id = sheet.attrib.get(f"{{{NS_REL}}}id")
        target = rels.get(rel_id or "")
        if target:
            sheets.append((sheet.attrib.get("name", "").strip(), target))
    return sheets


def _extract_rows(zf: zipfile.ZipFile, target: str, shared: List[str]) -> List[List[str]]:
    sheet_path = "xl/" + target
    root = ET.fromstring(zf.read(sheet_path))
    data = root.find(f"{{{NS_MAIN}}}sheetData")
    if data is None:
        return []
    rows: List[List[str]] = []
    for row in data.findall(f"{{{NS_MAIN}}}row"):
        values: List[str] = []
        for cell in row.findall(f"{{{NS_MAIN}}}c"):
            cell_type = cell.attrib.get("t")
            v = cell.find(f"{{{NS_MAIN}}}v")
            if v is None or v.text is None:
                values.append("")
                continue
            text = v.text
            if cell_type == "s":
                idx = int(text)
                values.append(shared[idx] if idx < len(shared) else "")
            else:
                values.append(text)
        rows.append(values)
    return rows


COL_MAP = {
    2: "sequence",
    3: "class_label",
    4: "student_number",
    5: "nisn",
    6: "full_name",
    7: "gender",
    8: "birth_place",
    9: "birth_date",
    10: "religion",
    11: "address_line",
    12: "rt",
    13: "rw",
    14: "kelurahan",
    15: "kecamatan",
    16: "father_name",
    17: "mother_name",
    18: "nik",
    19: "kk_number",
}


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_birth_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_class_sheet(sheet_name: str, rows: List[List[str]]) -> Iterable[StudentRow]:
    header_found = False
    for row in rows:
        if not header_found:
            search = [cell.strip().upper() for cell in row]
            if any(cell == "NO" for cell in search):
                header_found = True
            continue
        if not any(cell.strip() for cell in row):
            continue
        record: Dict[str, Optional[str]] = {}
        for idx, key in COL_MAP.items():
            value = row[idx] if idx < len(row) else ""
            record[key] = value
        full_name = _clean(record.get("full_name"))
        if not full_name:
            continue
        yield StudentRow(
            class_name=sheet_name,
            sequence=int(record["sequence"]) if record.get("sequence", "").isdigit() else None,
            student_number=_clean(record.get("student_number")),
            nisn=_clean(record.get("nisn")),
            full_name=full_name,
            gender=_clean(record.get("gender")),
            birth_place=_clean(record.get("birth_place")),
            birth_date=_parse_birth_date(record.get("birth_date")),
            religion=_clean(record.get("religion")),
            address_line=_clean(record.get("address_line")),
            rt=_clean(record.get("rt")),
            rw=_clean(record.get("rw")),
            kelurahan=_clean(record.get("kelurahan")),
            kecamatan=_clean(record.get("kecamatan")),
            father_name=_clean(record.get("father_name")),
            mother_name=_clean(record.get("mother_name")),
            nik=_clean(record.get("nik")),
            kk_number=_clean(record.get("kk_number")),
        )


def _guess_academic_year(rows: List[List[str]]) -> Optional[str]:
    pattern = re.compile(r"(20\\d{2}/20\\d{2})")
    for row in rows[:10]:
        for cell in row:
            match = pattern.search(cell)
            if match:
                return match.group(1)
    return None


def load_students_from_workbook(path: str) -> Tuple[Optional[str], Dict[str, List[StudentRow]]]:
    with zipfile.ZipFile(path) as zf:
        shared = _load_shared_strings(zf)
        sheets = _resolve_sheets(zf)
        academic_year: Optional[str] = None
        classes: Dict[str, List[StudentRow]] = {}
        for sheet_name, target in sheets:
            if not sheet_name or sheet_name.upper() in {"REKAP", "SISWA"}:
                rows = _extract_rows(zf, target, shared)
                year = _guess_academic_year(rows)
                if year and not academic_year:
                    academic_year = year
                continue
            rows = _extract_rows(zf, target, shared)
            if not rows:
                continue
            class_rows = list(_parse_class_sheet(sheet_name, rows))
            if class_rows:
                classes[sheet_name] = class_rows
        return academic_year, classes


def import_attendance_from_excel(path: str, *, academic_year: Optional[str] = None) -> None:
    from .queries import create_school_class, create_student  # Lazy import to avoid DB init during parsing

    detected_year, classes = load_students_from_workbook(path)
    active_year = academic_year or detected_year
    total_students = 0
    for class_name, students in classes.items():
        class_id = create_school_class(name=class_name, academic_year=active_year)
        for student in students:
            create_student(
                class_id,
                student.full_name,
                sequence=student.sequence,
                student_number=student.student_number,
                nisn=student.nisn,
                gender=student.gender,
                birth_place=student.birth_place,
                birth_date=student.birth_date,
                religion=student.religion,
                address_line=student.address_line,
                rt=student.rt,
                rw=student.rw,
                kelurahan=student.kelurahan,
                kecamatan=student.kecamatan,
                father_name=student.father_name,
                mother_name=student.mother_name,
                nik=student.nik,
                kk_number=student.kk_number,
            )
            total_students += 1
    print(f"Imported {total_students} students across {len(classes)} classes.")
