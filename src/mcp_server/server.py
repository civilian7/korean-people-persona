"""
korean-people-persona MCP 서버.

데이터: NVIDIA Nemotron-Personas-Korea (1M행) → SQLite + FTS5
실행:   python -m mcp_server   (stdio transport)
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import tools

mcp = FastMCP("korean-people-persona")


@mcp.tool()
def search_persona(
    query: str | None = None,
    fields: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 20,
    full: bool = False,
) -> dict[str, Any]:
    """한국 페르소나 검색. FTS5 자유 텍스트 + 인구통계 필터 결합.

    검색어 팁:
      - 한국어는 조사 때문에 prefix 매칭 권장: '등산*', '트로트*'
      - 불린: 'AND', 'OR', 'NOT' 사용 가능 (예: '등산* AND 트로트*')
      - 큰따옴표로 구절 검색: '"농촌 출신"'

    필터 키:
      sex, marital_status, military_status, family_type, housing_type,
      education_level, bachelors_field, occupation, district, province, country
      (단일값 또는 리스트), age_min, age_max, *_like (LIKE 패턴)

    fields: 검색 대상 컬럼 제한 가능. 가능 값:
      professional_persona, sports_persona, arts_persona, travel_persona,
      culinary_persona, family_persona, cultural_background,
      skills_and_expertise, hobbies_and_interests, career_goals_and_ambitions
    """
    return tools.search_persona(
        query=query, fields=fields, filters=filters, limit=limit, full=full
    )


@mcp.tool()
def get_persona(uuid: str) -> dict[str, Any]:
    """uuid로 단일 페르소나 전체 정보 조회."""
    return tools.get_persona(uuid)


@mcp.tool()
def sample_persona(
    filters: dict[str, Any] | None = None,
    n: int = 5,
    full: bool = False,
) -> dict[str, Any]:
    """필터 조건을 만족하는 페르소나를 무작위 샘플링."""
    return tools.sample_persona(filters=filters, n=n, full=full)


@mcp.tool()
def aggregate(
    group_by: list[str],
    filters: dict[str, Any] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """인구통계 컬럼별 COUNT 집계 (시도×성별 분포 등)."""
    return tools.aggregate(group_by=group_by, filters=filters, limit=limit)


@mcp.tool()
def stats() -> dict[str, Any]:
    """전체 데이터셋 기본 통계 및 사용 가능 컬럼 안내."""
    return tools.stats()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
