"""NPC/캐릭터 캐스팅 데모 — korean-people-persona MCP 서버 활용 사례 4B 구현.

배역 요구(brief)를 검색 조건으로 변환해 후보 페르소나를 추출하고, 후보별로
대사 톤·말버릇·갈등 요소·관계 훅을 파생한 마크다운 캐릭터 시트를 생성한다.

사용법:
    python examples/npc_casting.py --dry-run                       # 기본 필터로 후보 추출만 (키 불필요)
    python examples/npc_casting.py --brief "서울 30대 미혼 직장인 조연"   # brief를 LLM이 조건으로 변환
    python examples/npc_casting.py --filters '{"province": "부산"}'     # 조건 직접 지정 (LLM 변환 생략)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from common import (DEFAULT_MODEL, ROOT, build_profile, call_tool, llm_json,
                    llm_text, make_llm_client, mcp_session, require_api_key)

DEFAULT_BRIEF = "부산 영도구 50대 자영업자, 무뚝뚝하지만 정 많은 조연"

# 기본 필터: DEFAULT_BRIEF 에 해당하는 검증된 조건 (--filters/--brief 미지정·dry-run 시 사용)
DEFAULT_FILTERS = {"province": "부산", "district_like": "%영도%",
                   "age_min": 50, "age_max": 59, "occupation_like": "%경영%"}

PARSE_SYSTEM = """배역 요구를 korean-people-persona 검색 조건 JSON으로 변환하세요. JSON으로만 답합니다.
사용 가능 필터 키: sex, age_min, age_max, province, district_like, occupation_like, marital_status, family_type
값 주의:
- province는 '서울','부산','경기','경상남'처럼 짧은 표기 ('부산광역시' 아님)
- district는 '부산-영도구' 형식이므로 district_like는 '%영도%' 패턴
- occupation은 '소규모 상점 경영자' 같은 직업분류 명칭이므로 occupation_like는 '%경영%'처럼 넓은 패턴
형식: {"query": "<FTS 검색어(3글자 이상) 또는 null>", "filters": {...}}"""

SHEET_SYSTEM = """당신은 캐스팅 디렉터입니다. 아래 인물 프로필로 창작용 캐릭터 시트를 작성하세요.
마크다운으로, 정확히 이 4개 소제목만 사용: ### 말투와 어휘 / ### 말버릇 / ### 갈등 요소 / ### 관계 훅
각 항목 2~3문장. 프로필 문장을 복사하지 말고 새로운 표현으로 파생하세요."""


async def find_candidates(session: Any, query: str | None,
                          filters: dict[str, Any], n: int) -> list[dict[str, Any]]:
    """검색어가 있으면 FTS 검색, 없으면 필터 무작위 샘플."""
    if query:
        res = await call_tool(session, "search_persona",
                              {"query": query, "filters": filters, "limit": n, "full": True})
    else:
        res = await call_tool(session, "sample_persona",
                              {"filters": filters, "n": n, "full": True})
    return res["results"]


def render_candidate_md(index: int, p: dict[str, Any], sheet: str | None) -> str:
    """후보 1명 → 마크다운 섹션."""
    head = (f"## 후보 {index} — {p['province']} {p['sex']} {p['age']}세 · {p['occupation']}\n\n"
            f"> {p['persona']}\n\n")
    return head + (sheet.strip() + "\n\n" if sheet else "")


async def run(args: argparse.Namespace) -> int:
    query: str | None = None
    filters = DEFAULT_FILTERS
    brief = args.brief or DEFAULT_BRIEF

    if args.filters:
        filters = json.loads(args.filters)
        print(f"[1/3] 조건 직접 지정: {filters}")
    elif args.brief and not args.dry_run:
        require_api_key()
        client = make_llm_client()
        parsed = llm_json(client, args.model, PARSE_SYSTEM, brief) or {}
        query = parsed.get("query") or None
        filters = parsed.get("filters") or DEFAULT_FILTERS
        print(f"[1/3] brief 변환: \"{brief}\" → query={query!r}, filters={filters}")
    else:
        print(f"[1/3] 기본 조건 사용: {filters} (brief: \"{brief}\")")

    async with mcp_session() as session:
        candidates = await find_candidates(session, query, filters, args.n)
    print(f"[2/3] 후보 추출: {len(candidates)}명")
    for p in candidates:
        print(f"      - {p['province']} {p['sex']} {p['age']}세 {p['occupation']}")

    if not candidates:
        print("[WARN] 후보 0명 — 필터를 넓혀 보세요 (필터 값은 aggregate로 먼저 확인)")
        return 1

    sheets: list[str | None] = [None] * len(candidates)
    if args.dry_run:
        print("[DRY-RUN] MCP 파이프라인 검증 완료 (캐릭터 시트 생성 생략)")
    else:
        require_api_key()
        client = make_llm_client()
        print(f"[3/3] 캐릭터 시트 생성 (model={args.model})")
        for i, p in enumerate(candidates):
            sheets[i] = llm_text(client, args.model, SHEET_SYSTEM,
                                 [{"role": "user", "content": build_profile(p)}], max_tokens=600)
            print(f"      [{i + 1}/{len(candidates)}] 완료")

    md = f"# 캐스팅 후보 — {brief}\n\n조건: `{json.dumps(filters, ensure_ascii=False)}`"
    md += f" / 검색어: `{query}`\n\n" if query else "\n\n"
    for i, p in enumerate(candidates, 1):
        md += render_candidate_md(i, p, sheets[i - 1])
    out_path = ROOT / "npc_candidates.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"\n[DONE] 결과 저장: {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", default=None, help=f"배역 요구 (기본: {DEFAULT_BRIEF})")
    parser.add_argument("--filters", default=None,
                        help='검색 조건 JSON 직접 지정 (LLM 변환 생략, 예: \'{"province": "부산"}\')')
    parser.add_argument("--n", type=int, default=5, help="후보 수 (기본 5)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"모델 (기본 {DEFAULT_MODEL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="LLM 호출 없이 후보 추출만 검증 (기본 필터 사용)")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
