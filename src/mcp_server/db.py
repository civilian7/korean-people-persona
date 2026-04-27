"""SQLite 접근 유틸리티 (read-only)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "database" / "persona.db"

# 검색/필터 가능 인구통계 컬럼
DEMO_COLUMNS = {
    "sex", "age", "marital_status", "military_status", "family_type",
    "housing_type", "education_level", "bachelors_field", "occupation",
    "district", "province", "country",
}

# FTS5 인덱싱된 컬럼
FTS_COLUMNS = (
    "professional_persona", "sports_persona", "arts_persona", "travel_persona",
    "culinary_persona", "family_persona", "cultural_background",
    "skills_and_expertise", "hobbies_and_interests", "career_goals_and_ambitions",
)

# 요약 응답용 컬럼 (페이로드 절감)
SUMMARY_COLUMNS = (
    "uuid", "persona", "sex", "age", "occupation",
    "province", "district", "education_level", "family_type",
)


def open_ro(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """읽기 전용 SQLite 연결 (URI mode)."""
    if not db_path.exists():
        raise FileNotFoundError(
            f"DB not found: {db_path}. Run `python -m convert --download` first."
        )
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Row → dict, JSON 컬럼 자동 파싱."""
    d = dict(row)
    for k in ("skills_and_expertise_list", "hobbies_and_interests_list"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


def build_filter_clause(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """
    인구통계 필터 dict → (WHERE 절, 파라미터 리스트).

    지원:
      - 정확 일치: {"sex": "여자"}
      - 다중 값:   {"province": ["서울", "경기"]}
      - 나이 범위: {"age_min": 60, "age_max": 79}
      - LIKE:      {"occupation_like": "%농업%"}
    """
    clauses: list[str] = []
    params: list[Any] = []

    for key, val in filters.items():
        if val is None:
            continue
        if key == "age_min":
            clauses.append("age >= ?")
            params.append(int(val))
        elif key == "age_max":
            clauses.append("age <= ?")
            params.append(int(val))
        elif key.endswith("_like"):
            col = key[:-5]
            if col not in DEMO_COLUMNS:
                raise ValueError(f"unknown filter column: {col}")
            clauses.append(f"{col} LIKE ?")
            params.append(str(val))
        elif key in DEMO_COLUMNS:
            if isinstance(val, (list, tuple)):
                placeholders = ", ".join("?" * len(val))
                clauses.append(f"{key} IN ({placeholders})")
                params.extend(val)
            else:
                clauses.append(f"{key} = ?")
                params.append(val)
        else:
            raise ValueError(f"unknown filter key: {key}")

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params
