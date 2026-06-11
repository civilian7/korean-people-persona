"""
합성 설문 데모 — korean-people-persona MCP 서버 활용 사례 1 구현.

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
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_QUESTION = "월 9,900원에 광고 없이 국내 OTT 3사를 묶어 보는 통합 구독제가 나온다면 가입하시겠습니까?"
DEFAULT_MODEL = "claude-sonnet-4-6"

SYSTEM_TEMPLATE = """당신은 아래 인물입니다. 이 인물의 가치관·생활환경·말투에서 벗어나지 마세요.

{profile}

설문 질문에 이 인물로서 답하세요. 반드시 아래 JSON 형식으로만 답합니다.
{{"score": <1~5 정수, 1=전혀 아니다 5=매우 그렇다>, "reason": "<한 줄 이유>"}}"""

# 시스템 프롬프트에 넣을 페르소나 컬럼 (서술문 + 인구통계)
PROFILE_FIELDS = [
    "persona", "professional_persona", "family_persona", "culinary_persona",
    "hobbies_and_interests", "career_goals_and_ambitions",
    "sex", "age", "marital_status", "family_type", "housing_type",
    "education_level", "occupation", "district", "province",
]


def parse_tool_result(result: Any) -> dict[str, Any]:
    """MCP CallToolResult → dict. structuredContent 우선, 없으면 텍스트를 JSON 파싱."""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    return json.loads(result.content[0].text)


def allocate_quota(groups: list[dict[str, Any]], n: int) -> list[tuple[dict[str, Any], int]]:
    """최대 잔여법(largest remainder)으로 셀별 표본 수 배분."""
    total = sum(g["cnt"] for g in groups)
    raw = [(g, n * g["cnt"] / total) for g in groups]
    quotas = [(g, int(q)) for g, q in raw]
    remainder = n - sum(q for _, q in quotas)
    # 소수부가 큰 셀부터 1씩 추가 배분
    by_frac = sorted(range(len(raw)), key=lambda i: raw[i][1] - int(raw[i][1]), reverse=True)
    result = [[g, q] for g, q in quotas]
    for i in by_frac[:remainder]:
        result[i][1] += 1
    return [(g, q) for g, q in result if q > 0]


def build_profile(p: dict[str, Any]) -> str:
    """페르소나 dict → 시스템 프롬프트용 프로필 텍스트."""
    lines = []
    for f in PROFILE_FIELDS:
        if f in p and p[f] is not None:
            lines.append(f"- {f}: {p[f]}")
    return "\n".join(lines)


def ask_persona(client: Any, model: str, persona: dict[str, Any], question: str) -> dict[str, Any]:
    """페르소나 1명에게 설문 질문 → {"score": int, "reason": str}."""
    msg = client.messages.create(
        model=model,
        max_tokens=300,
        system=SYSTEM_TEMPLATE.format(profile=build_profile(persona)),
        messages=[{"role": "user", "content": question}],
    )
    text = msg.content[0].text
    # JSON 블록 추출 (모델이 부가 설명을 붙여도 견디도록)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"score": None, "reason": text.strip()[:100]}
    try:
        parsed = json.loads(m.group())
        score = int(parsed.get("score"))
        if not 1 <= score <= 5:
            score = None
        return {"score": score, "reason": str(parsed.get("reason", ""))[:200]}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"score": None, "reason": text.strip()[:100]}


def age_band(age: int) -> str:
    return f"{(age // 10) * 10}대" if age < 80 else "80대+"


def summarize(responses: list[dict[str, Any]]) -> dict[str, Any]:
    """축별(전체/성별/연령대/시도) 평균 점수 집계."""
    valid = [r for r in responses if r["score"] is not None]

    def mean_by(key_fn) -> dict[str, dict[str, Any]]:
        buckets: dict[str, list[int]] = defaultdict(list)
        for r in valid:
            buckets[key_fn(r)].append(r["score"])
        return {
            k: {"n": len(v), "mean": round(sum(v) / len(v), 2)}
            for k, v in sorted(buckets.items())
        }

    return {
        "total": {"n": len(valid), "invalid": len(responses) - len(valid),
                  "mean": round(sum(r["score"] for r in valid) / len(valid), 2) if valid else None},
        "by_sex": mean_by(lambda r: r["persona"]["sex"]),
        "by_age_band": mean_by(lambda r: age_band(r["persona"]["age"])),
        "by_province": mean_by(lambda r: r["persona"]["province"]),
    }


async def run(args: argparse.Namespace) -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server"],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        cwd=str(ROOT),
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1) 전체 통계
            stats = parse_tool_result(await session.call_tool("stats", {}))
            print(f"[1/4] 모집단: {stats['total']:,}명 "
                  f"(평균 {stats['age']['avg']:.1f}세, 성비 {stats['sex']})")

            # 2) 시도×성별 분포 → 층화 배분
            agg = parse_tool_result(await session.call_tool(
                "aggregate", {"group_by": ["province", "sex"], "limit": 500}
            ))
            quotas = allocate_quota(agg["groups"], args.n)
            print(f"[2/4] 층화 샘플링: {len(agg['groups'])}개 셀 → {len(quotas)}개 셀에 {args.n}명 배분")

            # 3) 셀별 무작위 샘플
            personas: list[dict[str, Any]] = []
            for g, q in quotas:
                res = parse_tool_result(await session.call_tool(
                    "sample_persona",
                    {"filters": {"province": g["province"], "sex": g["sex"]},
                     "n": q, "full": True},
                ))
                personas.extend(res["results"])
            print(f"[3/4] 표본 확보: {len(personas)}명")
            for p in personas[:5]:
                print(f"      - {p['province']} {p['sex']} {p['age']}세 {p['occupation']}")
            if len(personas) > 5:
                print(f"      ... 외 {len(personas) - 5}명")

    if args.dry_run:
        print("[DRY-RUN] MCP 파이프라인 검증 완료 (LLM 호출 생략)")
        return 0

    # 4) 페르소나별 롤플레이 설문 (MCP 세션 종료 후 — 표본은 이미 메모리에 있음)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[ERROR] ANTHROPIC_API_KEY가 없습니다. --dry-run으로 파이프라인만 검증할 수 있습니다.",
              file=sys.stderr)
        return 1

    import anthropic
    client = anthropic.Anthropic()

    print(f"[4/4] 설문 시작: \"{args.question}\" (model={args.model})")
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
