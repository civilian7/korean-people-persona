"""한국어 합성 데이터 생성 데모 — korean-people-persona MCP 서버 활용 사례 3 구현.

'캠핑' 관심사 페르소나를 시드로 캠핑용품 구매 리뷰를 생성하고, 인구통계 라벨과 함께
JSONL로 저장한다. 페르소나 서술문 표현 복사는 어절 4-gram 중복 검사로 검출해 표시한다.

사용법:
    python examples/synthetic_reviews.py --dry-run     # 시드 풀 구성만 검증 (키 불필요)
    python examples/synthetic_reviews.py --n 10        # 실제 생성 (ANTHROPIC_API_KEY 필요)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from common import (DEFAULT_MODEL, PROFILE_FIELDS, ROOT, build_profile, call_tool,
                    llm_json, make_llm_client, mcp_session, ngram_overlap, require_api_key)

# '캠핑'(2글자)은 trigram 토크나이저에 매칭되지 않는다 → 공백 포함 구절 + 합성어 OR 조합 사용
SEED_QUERY = '"캠핑 " OR 캠핑장 OR 캠핑카'
REVIEWS_PER_PERSONA = 2

REVIEW_TEMPLATE = """당신은 아래 인물입니다. 이 인물의 어휘·생활환경에서 벗어나지 마세요.

{profile}

캠핑용품 쇼핑몰에서 실제 구매 후 리뷰를 쓰는 상황입니다.
주의: 위 인물 소개 문장의 표현을 그대로 옮기지 말고, 이 인물이 쓸 법한 생활 어휘로 새로 쓰세요.
반드시 아래 JSON 형식으로만 답합니다.
{{"reviews": [{{"product": "<구체적 캠핑용품명>", "rating": <1~5 정수>, "text": "<리뷰 본문 2~4문장>"}},
              {{"product": "<다른 용품명>", "rating": <1~5 정수>, "text": "<리뷰 본문>"}}]}}"""


async def build_seed_pool(session: Any, n: int) -> tuple[list[dict[str, Any]], int]:
    """검색 시드 + 부족분 무작위 보충. (시드 풀, 검색 매칭 수) 반환."""
    res = await call_tool(session, "search_persona",
                          {"query": SEED_QUERY, "fields": ["hobbies_and_interests"],
                           "limit": n, "full": True})
    personas = list(res["results"])
    matched = len(personas)
    if matched < n:
        extra = await call_tool(session, "sample_persona", {"n": n - matched, "full": True})
        personas.extend(extra["results"])
    return personas, matched


def generate_reviews(client: Any, model: str, persona: dict[str, Any]) -> list[dict[str, Any]]:
    """페르소나 1명 → 리뷰 행 목록 (인구통계 라벨 + 중복 검사 결과 포함)."""
    parsed = llm_json(client, model,
                      REVIEW_TEMPLATE.format(profile=build_profile(persona)),
                      f"캠핑용품 리뷰를 {REVIEWS_PER_PERSONA}건 작성해 주세요.", max_tokens=800)
    reviews = (parsed or {}).get("reviews", [])
    profile_text = " ".join(str(persona.get(f, "")) for f in PROFILE_FIELDS)
    rows = []
    for r in reviews[:REVIEWS_PER_PERSONA]:
        text = str(r.get("text", ""))
        overlap = ngram_overlap(profile_text, text)
        rows.append({
            "uuid": persona["uuid"], "sex": persona["sex"], "age": persona["age"],
            "province": persona["province"], "occupation": persona["occupation"],
            "product": str(r.get("product", "")), "rating": r.get("rating"),
            "text": text, "profile_ngram_overlap": overlap, "flagged": overlap > 0,
        })
    return rows


async def run(args: argparse.Namespace) -> int:
    async with mcp_session() as session:
        personas, matched = await build_seed_pool(session, args.n)
    print(f"[1/2] 시드 확보: {len(personas)}명 (검색 매칭 {matched}명 + 무작위 보충 {len(personas) - matched}명)")
    for p in personas[:5]:
        print(f"      - {p['province']} {p['sex']} {p['age']}세 {p['occupation']}")
    if len(personas) > 5:
        print(f"      ... 외 {len(personas) - 5}명")

    if args.dry_run:
        print("[DRY-RUN] MCP 파이프라인 검증 완료 (LLM 호출 생략)")
        return 0

    require_api_key()
    client = make_llm_client()

    print(f"[2/2] 리뷰 생성 시작 (model={args.model}, 인당 {REVIEWS_PER_PERSONA}건)")
    rows: list[dict[str, Any]] = []
    for i, p in enumerate(personas, 1):
        new_rows = generate_reviews(client, args.model, p)
        rows.extend(new_rows)
        flags = sum(1 for r in new_rows if r["flagged"])
        print(f"      [{i}/{len(personas)}] {p['province']} {p['age']}세 → {len(new_rows)}건"
              + (f" (표현 복사 의심 {flags}건)" if flags else ""))

    out_path = ROOT / "synthetic_reviews.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    flagged = sum(1 for r in rows if r["flagged"])
    print(f"\n[DONE] {len(rows)}건 생성 (표현 복사 의심 {flagged}건) → {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10, help="시드 페르소나 수 (기본 10)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"모델 (기본 {DEFAULT_MODEL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="LLM 호출 없이 시드 풀 구성만 검증")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
