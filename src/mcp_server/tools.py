"""MCP 도구 구현체. FastMCP에서 import해서 등록."""

from __future__ import annotations

from typing import Any

from .db import (
    DEMO_COLUMNS,
    FTS_COLUMNS,
    SUMMARY_COLUMNS,
    build_filter_clause,
    open_ro,
    row_to_dict,
)

MAX_LIMIT = 100


def search_persona(
    query: str | None = None,
    fields: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 20,
    full: bool = False,
) -> dict[str, Any]:
    """
    페르소나 검색. FTS5(trigram 토크나이저) 자유 텍스트 + 인구통계 필터 결합.

    Args:
        query: FTS5 MATCH 표현식. trigram이라 3글자 이상이면 조사가 붙은 형태도
               부분 문자열로 그대로 매칭됨 (`등산과`, `트로트`) — prefix `*` 불필요.
               단 2글자 이하 검색어는 매칭 불가 → 3글자 이상으로 늘리거나
               filters의 `*_like` 사용. None이면 텍스트 검색 없이 필터만 적용.
        fields: 검색 대상 FTS 컬럼 제한. 미지정 시 전체.
        filters: 인구통계 필터 dict (db.build_filter_clause 참조).
        limit: 최대 반환 개수 (1..100, 기본 20).
        full: True면 전체 컬럼, False면 요약 컬럼만.

    Returns:
        {"count": N, "results": [...]}
    """
    limit = max(1, min(int(limit), MAX_LIMIT))
    filters = filters or {}

    if fields:
        invalid = [f for f in fields if f not in FTS_COLUMNS]
        if invalid:
            raise ValueError(f"invalid FTS fields: {invalid}")

    cols = ", ".join(f"p.{c}" for c in (("*",) if full else SUMMARY_COLUMNS)) \
        .replace("p.*", "p.*")

    where_demo, demo_params = build_filter_clause(filters)

    with open_ro() as conn:
        if query:
            # FTS 컬럼 제한이 있으면 {col1 col2}: prefix
            if fields:
                match_expr = "{" + " ".join(fields) + "} : (" + query + ")"
            else:
                match_expr = query

            sql = f"""
                SELECT {cols}, bm25(persona_fts) AS rank
                FROM persona_fts f
                JOIN persona p ON p.rowid = f.rowid
                WHERE persona_fts MATCH ?
                {where_demo.replace(' WHERE ', ' AND ') if where_demo else ''}
                ORDER BY rank
                LIMIT ?
            """
            params = [match_expr, *demo_params, limit]
        else:
            sql = f"""
                SELECT {cols}
                FROM persona p
                {where_demo}
                LIMIT ?
            """
            params = [*demo_params, limit]

        rows = conn.execute(sql, params).fetchall()

    results = [row_to_dict(r) for r in rows]
    return {"count": len(results), "results": results}


def get_persona(uuid: str) -> dict[str, Any]:
    """uuid로 단일 페르소나 전체 조회."""
    with open_ro() as conn:
        row = conn.execute("SELECT * FROM persona WHERE uuid = ?", (uuid,)).fetchone()
    if row is None:
        return {"found": False, "uuid": uuid}
    return {"found": True, "persona": row_to_dict(row)}


def sample_persona(
    filters: dict[str, Any] | None = None,
    n: int = 5,
    full: bool = False,
) -> dict[str, Any]:
    """조건부 무작위 샘플."""
    n = max(1, min(int(n), MAX_LIMIT))
    where, params = build_filter_clause(filters or {})
    cols = "*" if full else ", ".join(SUMMARY_COLUMNS)

    sql = f"SELECT {cols} FROM persona{where} ORDER BY random() LIMIT ?"
    with open_ro() as conn:
        rows = conn.execute(sql, [*params, n]).fetchall()
    return {"count": len(rows), "results": [row_to_dict(r) for r in rows]}


def aggregate(
    group_by: list[str],
    filters: dict[str, Any] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    인구통계 컬럼들로 GROUP BY COUNT.

    예: aggregate(["province", "sex"], filters={"age_min": 60}) →
        시도×성별 60대 이상 분포.
    """
    if not group_by:
        raise ValueError("group_by must not be empty")
    invalid = [c for c in group_by if c not in DEMO_COLUMNS]
    if invalid:
        raise ValueError(f"invalid group_by columns: {invalid}")

    limit = max(1, min(int(limit), 500))
    where, params = build_filter_clause(filters or {})
    cols = ", ".join(group_by)
    sql = (
        f"SELECT {cols}, COUNT(*) AS cnt FROM persona{where} "
        f"GROUP BY {cols} ORDER BY cnt DESC LIMIT ?"
    )
    with open_ro() as conn:
        rows = conn.execute(sql, [*params, limit]).fetchall()
    return {"count": len(rows), "groups": [dict(r) for r in rows]}


def stats() -> dict[str, Any]:
    """전체 데이터셋 기본 통계."""
    with open_ro() as conn:
        total = conn.execute("SELECT COUNT(*) FROM persona").fetchone()[0]
        sex_dist = {
            r["sex"]: r["cnt"]
            for r in conn.execute(
                "SELECT sex, COUNT(*) cnt FROM persona GROUP BY sex"
            )
        }
        age_stats = dict(
            conn.execute(
                "SELECT MIN(age) AS min, MAX(age) AS max, AVG(age) AS avg FROM persona"
            ).fetchone()
        )
        province_top = [
            dict(r)
            for r in conn.execute(
                "SELECT province, COUNT(*) cnt FROM persona "
                "GROUP BY province ORDER BY cnt DESC LIMIT 5"
            )
        ]

    return {
        "total": total,
        "sex": sex_dist,
        "age": age_stats,
        "top_provinces": province_top,
        "fts_columns": list(FTS_COLUMNS),
        "demographic_columns": sorted(DEMO_COLUMNS),
    }
