from __future__ import annotations

import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass
class TeacherRow:
    number: int
    full_name: str
    email: str
    nip: Optional[str]
    nrk: Optional[str]
    jabatan: Optional[str]
    status_ptk: Optional[str]
    degree_prefix: Optional[str]
    degree_suffix: Optional[str]


def _load_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings: List[str] = []
    for si in root.findall(f"{{{NS_MAIN}}}si"):
        text = "".join(node.text or "" for node in si.findall(f".//{{{NS_MAIN}}}t"))
        strings.append(text)
    return strings


def _resolve_sheets(zf: zipfile.ZipFile) -> Sequence[Tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels_tree = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rels = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels_tree.findall(f"{{{NS_PACKAGE_REL}}}Relationship")
    }
    sheets: List[Tuple[str, str]] = []
    for sheet in workbook.find(f"{{{NS_MAIN}}}sheets"):
        rel_id = sheet.attrib.get(f"{{{NS_REL}}}id")
        target = rels.get(rel_id or "")
        if target:
            sheets.append((sheet.attrib.get("name", "").strip(), target))
    return sheets


def _extract_rows(zf: zipfile.ZipFile, target: str, shared: Sequence[str]) -> List[List[str]]:
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
            content = v.text
            if cell_type == "s":
                idx = int(content)
                values.append(shared[idx] if 0 <= idx < len(shared) else "")
            else:
                values.append(content)
        rows.append(values)
    return rows


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned == "-":
        return None
    return cleaned


def _clean_identifier(value: Optional[str]) -> Optional[str]:
    cleaned = _clean_text(value)
    if not cleaned or cleaned == "-":
        return None
    sanitized = cleaned.replace(" ", "")
    lower_value = sanitized.lower()
    if lower_value.endswith(".0"):
        sanitized = sanitized[:-2]
    if "e" in lower_value:
        try:
            number = Decimal(sanitized)
            sanitized = format(number.normalize(), "f").rstrip(".")
        except InvalidOperation:
            return sanitized
    return sanitized


def _parse_teacher_rows(rows: List[List[str]]) -> List[TeacherRow]:
    header_index: Optional[int] = None
    for idx, row in enumerate(rows):
        normalized = [cell.strip().upper() for cell in row if cell]
        if "STATUS PTK" in normalized and "NAMA TANPA GELAR" in normalized:
            header_index = idx
            break
    if header_index is None:
        return []

    data_rows = rows[header_index + 2 :]
    teachers: List[TeacherRow] = []
    for row in data_rows:
        if not row:
            continue
        number_raw = _clean_text(row[0] if len(row) > 0 else "")
        if not number_raw:
            continue
        try:
            number = int(float(number_raw))
        except ValueError:
            continue
        full_name = _clean_text(row[3] if len(row) > 3 else "")
        email = _clean_text(row[13] if len(row) > 13 else "")
        if not full_name:
            continue
        teachers.append(
            TeacherRow(
                number=number,
                full_name=full_name,
                email=email or "",
                nip=_clean_identifier(row[27] if len(row) > 27 else ""),
                nrk=_clean_identifier(row[28] if len(row) > 28 else ""),
                jabatan=_clean_text(row[2] if len(row) > 2 else ""),
                status_ptk=_clean_text(row[1] if len(row) > 1 else ""),
                degree_prefix=_clean_text(row[4] if len(row) > 4 else ""),
                degree_suffix=_clean_text(row[5] if len(row) > 5 else ""),
            )
        )
    return teachers


def load_teacher_rows(path: str) -> List[TeacherRow]:
    with zipfile.ZipFile(path) as zf:
        shared = _load_shared_strings(zf)
        for _, target in _resolve_sheets(zf):
            rows = _extract_rows(zf, target, shared)
            teachers = _parse_teacher_rows(rows)
            if teachers:
                return teachers
    return []
