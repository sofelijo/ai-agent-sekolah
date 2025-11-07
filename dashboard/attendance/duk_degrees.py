from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

from .teacher_importer import load_teacher_rows

DEFAULT_DUK_FILENAME = "DUK SEMBAR 01 (1).xlsx"
DEFAULT_DUK_PATH = Path(__file__).resolve().parent / "data_siswa" / DEFAULT_DUK_FILENAME


def _normalize_name(value: Optional[str]) -> str:
    return " ".join((value or "").strip().lower().split())


@lru_cache(maxsize=4)
def _load_degree_map(source: Path) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    if not source.exists():
        return {}
    rows = load_teacher_rows(str(source))
    mapping: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    for row in rows:
        # Skip rows with no degree information at all
        if not row.degree_prefix and not row.degree_suffix:
            continue
        mapping[_normalize_name(row.full_name)] = (row.degree_prefix, row.degree_suffix)
    return mapping


def resolve_degree_from_duk(full_name: Optional[str], *, source_path: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Fetch gelar depan/belakang dari file DUK. Returns (prefix, suffix)."""
    if not full_name:
        return None, None
    source = Path(source_path).expanduser().resolve() if source_path else DEFAULT_DUK_PATH
    mapping = _load_degree_map(source)
    return mapping.get(_normalize_name(full_name), (None, None))
