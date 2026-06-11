"""합성 설문 데모 — korean-people-persona MCP 서버 활용 사례 1 구현.

흐름:
    1. MCP stdio 클라이언트로 `python -m mcp_server` 연결
    2. aggregate(["province", "sex"])로 모집단 분포 확인
    3. 분포 비례 층화 샘플링 (sample_persona)
    4. 페르소나별 Anthropic API 롤플레이 → 5점 척도 + 한 줄 이유 (JSON)
    5. 인구통계 축별 집계 출력 + survey_result.json 저장

사용법:
    python examples/synthetic_survey.py --dry-run                 # API 키 없이 파이프라인 검증
    python examples/synthetic_survey.py --question "..." --n 20   # 실제 설문 (ANTHROPIC_API_KEY 필요)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from common import (DEFAULT_MODEL, ROOT, age_band, build_profile, call_tool,
                    llm_json, make_llm_client, mcp_session, mean_by,
                    require_api_key, stratified_sample)

DEFAULT_QUESTION = "월 9,900원에 광고 없이 국내 OTT 3사를 묶어 보는 통합 구독제가 나온다면 가입하시겠습니까?"

SYSTEM_TEMPLATE = """당신은 아래 인물입니다. 이 인물의 가치관·생활환경·말투에서 벗어나지 마세요.

{profile}

설문 질문에 이 인물로서 답하세요. 반드시 아래 JSON 형식으로만 답합니다.
{{"score": <1~5 정수, 1=전혀 아니다 5=매우 그렇다>, "reason": "<한 줄 이유>"}}"""


def ask_persona(client: Any, model: str, persona: dict[str, Any], question: str) -> dict[str, Any]:
    """페르소나 1명에게 설문 질문 → {"score": int|None, "reason": str}."""
    parsed = llm_json(client, model, SYSTEM_TEMPLATE.format(profile=build_profile(persona)), question)
    if not parsed:
        return {"score": None, "reason": ""}
    try:
        score = int(parsed.get("score"))
    except (TypeError, ValueError):
        score = None
    if score is not None and not 1 <= score <= 5:
        score = None
    return {"score": score, "reason": str(parsed.get("reason", ""))[:200]}


def summarize(responses: list[dict[str, Any]]) -> dict[str, Any]:
    """축별(전체/성별/연령대/시도) 평균 점수 집계."""
    valid = [r for r in responses if r["score"] is not None]
    total_mean = round(sum(r["score"] for r in valid) / len(valid), 2) if valid else None
    return {
        "total": {"n": len(valid), "invalid": len(responses) - len(valid), "mean": total_mean},
        "by_sex": mean_by(valid, lambda r: r["persona"]["sex"], lambda r: r["score"]),
        "by_age_band": mean_by(valid, lambda r: age_band(r["persona"]["age"]), lambda r: r["score"]),
        "by_province": mean_by(valid, lambda r: r["persona"]["province"], lambda r: r["score"]),
    }


async def run(args: argparse.Namespace) -> int:
    async with mcp_session() as session:
        stats = await call_tool(session, "stats")
        print(f"[1/3] 모집단: {stats['total']:,}명 "
              f"(평균 {stats['age']['avg']:.1f}세, 성비 {stats['sex']})")

        personas = await stratified_sample(session, args.n)
        print(f"[2/3] 층화 샘플링: 시도×성별 분포 비례로 {len(personas)}명 확보")
        for p in personas[:5]:
            print(f"      - {p['province']} {p['sex']} {p['age']}세 {p['occupation']}")
        if len(personas) > 5:
            print(f"      ... 외 {len(personas) - 5}명")

    if args.dry_run:
        print("[DRY-RUN] MCP 파이프라인 검증 완료 (LLM 호출 생략)")
        return 0

    require_api_key()
    client = make_llm_client()

    print(f"[3/3] 설문 시작: \"{args.question}\" (model={args.model})")
    responses = []
    for i, p in enumerate(personas, 1):
        r = ask_persona(client, args.model, p, args.question)
        r["persona"] = {k: p[k] for k in ("uuid", "sex", "age", "province", "occupation")}
        responses.append(r)
        print(f"      [{i}/{len(personas)}] {p['province']} {p['sex']} {p['age']}세 "
              f"→ {r['score']}점: {r['reason'][:60]}")

    summary = summarize(responses)
    out = {"question": args.question, "model": args.model,
           "summary": summary, "responses": responses}
    out_path = ROOT / "survey_result.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 집계 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[DONE] 결과 저장: {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="설문 질문")
    parser.add_argument("--n", type=int, default=20, help="표본 수 (기본 20)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"모델 (기본 {DEFAULT_MODEL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="LLM 호출 없이 MCP 파이프라인만 검증")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
