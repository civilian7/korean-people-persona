"""마케팅 카피 A/B 테스트 데모 — korean-people-persona MCP 서버 활용 사례 4A 구현.

trigram 검색으로 관심사 세그먼트("등산과 AND 트로트" × 50세 이상 여성)를 정의하고,
각 페르소나에게 카피 두 개를 무작위 순서로 제시(순서 편향 통제)해 선호율을 집계한다.

사용법:
    python examples/copy_ab_test.py --dry-run          # 세그먼트 추출만 검증 (키 불필요)
    python examples/copy_ab_test.py --n 10             # 실제 평가 (ANTHROPIC_API_KEY 필요)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from typing import Any

from common import (DEFAULT_MODEL, ROOT, build_profile, call_tool, llm_json,
                    make_llm_client, mcp_session, require_api_key)

SEGMENT_QUERY = "등산과 AND 트로트"
SEGMENT_FILTERS = {"age_min": 50, "sex": "여자"}

COPY_A = "흔들리지 않는 착화감, 정상까지 함께 — 경량 방수 등산화 30% 할인"
COPY_B = "산에서도 무대처럼 당당하게 — 4050 여성을 위한 컬러 등산화 신상품"

AB_TEMPLATE = """당신은 아래 인물입니다. 이 인물의 취향·가치관에서 벗어나지 마세요.

{profile}

광고 카피 두 개 중 더 끌리는 쪽을 고르세요. 반드시 아래 JSON 형식으로만 답합니다.
{{"choice": <1 또는 2>, "reason": "<한 줄 이유>"}}"""


def ask_preference(client: Any, model: str, persona: dict[str, Any],
                   rng: random.Random, copy_a: str, copy_b: str) -> dict[str, Any]:
    """카피 A/B를 무작위 순서로 제시하고 선호를 수집. {"prefer": "A"|"B"|None, "reason": str}."""
    a_first = rng.random() < 0.5
    first, second = (copy_a, copy_b) if a_first else (copy_b, copy_a)
    user = f"카피 1: {first}\n카피 2: {second}"
    parsed = llm_json(client, model, AB_TEMPLATE.format(profile=build_profile(persona)), user)
    choice = (parsed or {}).get("choice")
    if choice not in (1, 2):
        return {"prefer": None, "reason": ""}
    picked_first = choice == 1
    prefer = "A" if picked_first == a_first else "B"
    return {"prefer": prefer, "reason": str((parsed or {}).get("reason", ""))[:200]}


async def run(args: argparse.Namespace) -> int:
    async with mcp_session() as session:
        res = await call_tool(session, "search_persona",
                              {"query": args.query, "filters": SEGMENT_FILTERS,
                               "limit": args.n, "full": True})
    personas = res["results"]
    print(f"[1/2] 세그먼트 확보: \"{args.query}\" × {SEGMENT_FILTERS} → {len(personas)}명")
    for p in personas[:5]:
        print(f"      - {p['province']} {p['sex']} {p['age']}세 {p['occupation']}")
    if len(personas) > 5:
        print(f"      ... 외 {len(personas) - 5}명")

    if not personas:
        print("[WARN] 세그먼트 매칭 0명 — 검색어를 넓혀 보세요 (예: --query 트로트)")
        return 1

    if args.dry_run:
        print("[DRY-RUN] MCP 파이프라인 검증 완료 (LLM 호출 생략)")
        return 0

    require_api_key()
    client = make_llm_client()
    rng = random.Random(args.seed)

    print(f"[2/2] 평가 시작 (model={args.model})")
    print(f"      A: {args.copy_a}\n      B: {args.copy_b}")
    responses = []
    for i, p in enumerate(personas, 1):
        r = ask_preference(client, args.model, p, rng, args.copy_a, args.copy_b)
        r["persona"] = {k: p[k] for k in ("uuid", "sex", "age", "province", "occupation")}
        responses.append(r)
        print(f"      [{i}/{len(personas)}] {p['province']} {p['age']}세 "
              f"→ {r['prefer']}: {r['reason'][:60]}")

    valid = [r for r in responses if r["prefer"] is not None]
    a_count = sum(1 for r in valid if r["prefer"] == "A")
    summary = {
        "n": len(valid), "invalid": len(responses) - len(valid),
        "prefer_a": a_count, "prefer_b": len(valid) - a_count,
        "prefer_a_rate": round(a_count / len(valid), 2) if valid else None,
        "reasons_a": [r["reason"] for r in valid if r["prefer"] == "A"][:5],
        "reasons_b": [r["reason"] for r in valid if r["prefer"] == "B"][:5],
    }
    out = {"query": args.query, "filters": SEGMENT_FILTERS,
           "copy_a": args.copy_a, "copy_b": args.copy_b,
           "model": args.model, "summary": summary, "responses": responses}
    out_path = ROOT / "ab_test_result.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 집계 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[DONE] 결과 저장: {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=SEGMENT_QUERY, help="세그먼트 FTS 검색어")
    parser.add_argument("--copy-a", default=COPY_A, help="카피 A")
    parser.add_argument("--copy-b", default=COPY_B, help="카피 B")
    parser.add_argument("--n", type=int, default=10, help="최대 표본 수 (기본 10)")
    parser.add_argument("--seed", type=int, default=42, help="제시 순서 셔플 시드 (기본 42)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"모델 (기본 {DEFAULT_MODEL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="LLM 호출 없이 세그먼트 추출만 검증")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
