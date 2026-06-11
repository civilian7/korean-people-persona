"""examples 공용 헬퍼 — MCP 접속, 층화 샘플링, LLM 호출, 집계 유틸.

모든 데모 스크립트가 공유하는 보일러플레이트. 시나리오 로직은 각 스크립트에 둔다.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "claude-sonnet-4-6"

# 시스템 프롬프트에 넣을 페르소나 컬럼 (서술문 + 인구통계)
PROFILE_FIELDS = [
    "persona", "professional_persona", "family_persona", "culinary_persona",
    "hobbies_and_interests", "career_goals_and_ambitions",
    "sex", "age", "marital_status", "family_type", "housing_type",
    "education_level", "occupation", "district", "province",
]


# ---------- MCP ----------

@asynccontextmanager
async def mcp_session():
    """`python -m mcp_server` stdio 접속 세션 (PYTHONPATH=src, cwd=프로젝트 루트)."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server"],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        cwd=str(ROOT),
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def parse_tool_result(result: Any) -> dict[str, Any]:
    """MCP CallToolResult → dict. structuredContent 우선, 없으면 텍스트를 JSON 파싱."""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    return json.loads(result.content[0].text)


async def call_tool(session: Any, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """도구 호출 + 결과 파싱."""
    return parse_tool_result(await session.call_tool(name, args or {}))


# ---------- 층화 샘플링 ----------

def allocate_quota(groups: list[dict[str, Any]], n: int) -> list[tuple[dict[str, Any], int]]:
    """최대 잔여법(largest remainder)으로 셀별 표본 수 배분. 0표본 셀은 제외."""
    total = sum(g["cnt"] for g in groups)
    raw = [(g, n * g["cnt"] / total) for g in groups]
    quotas = [(g, int(q)) for g, q in raw]
    remainder = n - sum(q for _, q in quotas)
    by_frac = sorted(range(len(raw)), key=lambda i: raw[i][1] - int(raw[i][1]), reverse=True)
    result = [[g, q] for g, q in quotas]
    for i in by_frac[:remainder]:
        result[i][1] += 1
    return [(g, q) for g, q in result if q > 0]


async def stratified_sample(session: Any, n: int,
                            filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """시도×성별 분포 비례 층화 샘플링 (full=True 전체 프로필)."""
    agg = await call_tool(session, "aggregate",
                          {"group_by": ["province", "sex"], "filters": filters, "limit": 500})
    personas: list[dict[str, Any]] = []
    for g, q in allocate_quota(agg["groups"], n):
        cell = {**(filters or {}), "province": g["province"], "sex": g["sex"]}
        res = await call_tool(session, "sample_persona", {"filters": cell, "n": q, "full": True})
        personas.extend(res["results"])
    return personas


# ---------- 프로필 / LLM ----------

def build_profile(p: dict[str, Any], fields: list[str] | None = None) -> str:
    """페르소나 dict → 시스템 프롬프트용 프로필 텍스트."""
    lines = []
    for f in fields or PROFILE_FIELDS:
        if p.get(f) is not None:
            lines.append(f"- {f}: {p[f]}")
    return "\n".join(lines)


def extract_json(text: str) -> dict[str, Any] | None:
    """텍스트에서 첫 JSON 오브젝트 추출 (모델이 부가 설명을 붙여도 견디도록)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def require_api_key() -> None:
    """ANTHROPIC_API_KEY 없으면 안내 후 종료."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[ERROR] ANTHROPIC_API_KEY가 없습니다. --dry-run으로 파이프라인만 검증할 수 있습니다.",
              file=sys.stderr)
        raise SystemExit(1)


def make_llm_client() -> Any:
    import anthropic
    return anthropic.Anthropic()


def llm_text(client: Any, model: str, system: str,
             messages: list[dict[str, str]], max_tokens: int = 300) -> str:
    """멀티턴 메시지 → 텍스트 응답."""
    msg = client.messages.create(model=model, max_tokens=max_tokens,
                                 system=system, messages=messages)
    return msg.content[0].text


def llm_json(client: Any, model: str, system: str, user: str,
             max_tokens: int = 300) -> dict[str, Any] | None:
    """단일 user 메시지 → JSON 응답 (파싱 실패 시 None)."""
    return extract_json(llm_text(client, model, system,
                                 [{"role": "user", "content": user}], max_tokens))


# ---------- 집계 ----------

def age_band(age: int) -> str:
    return f"{(age // 10) * 10}대" if age < 80 else "80대+"


def mean_by(items: list[Any], key_fn, value_fn) -> dict[str, dict[str, Any]]:
    """key_fn 으로 그룹핑해 value_fn 값의 {n, mean} 집계."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for it in items:
        buckets[key_fn(it)].append(value_fn(it))
    return {k: {"n": len(v), "mean": round(sum(v) / len(v), 2)}
            for k, v in sorted(buckets.items())}


def ngram_overlap(a: str, b: str, n: int = 4) -> int:
    """어절 n-gram 교집합 크기 (페르소나 서술문 표현 복사 검출용)."""
    def grams(s: str) -> set[tuple[str, ...]]:
        toks = s.split()
        return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}
    return len(grams(a) & grams(b))
