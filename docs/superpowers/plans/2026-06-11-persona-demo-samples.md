# 페르소나 데모 샘플 확장 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** use-cases.md 사례 2~4의 동작하는 데모 스크립트 4개 + 공유 헬퍼 + 세션용 프롬프트 레시피를 추가한다.

**Architecture:** `examples/common.py`에 MCP 접속·층화 샘플링·LLM 호출 보일러플레이트를 모으고, 사례별 스크립트 4개는 시나리오 로직만 담는다. 기존 `synthetic_survey.py`도 헬퍼 사용으로 리팩토링. 모든 스크립트는 `--dry-run`(MCP만, API 키 불필요)을 지원한다.

**Tech Stack:** Python 3.14, mcp(stdio client), anthropic SDK(지연 import), pytest(순수 함수 단위 테스트)

**스펙:** `docs/superpowers/specs/2026-06-11-persona-demo-samples-design.md`

**실행 위치:** 프로젝트 루트(`C:\works\projects\korean-people-persona`)에서 `python examples/<script>.py` 형태로 실행. 스크립트를 직접 실행하면 `examples/`가 `sys.path[0]`이 되므로 `import common`이 동작한다.

**검증된 DB 필터 값 (2026-06-11 라이브 확인):** province는 `경기`/`부산`/`경상남` 등 짧은 표기 (`경기도`·`부산광역시`는 0건). district는 `부산-영도구` 형식이라 `district_like`는 `%영도%` 패턴. occupation에 `자영업` 문자열은 없음 (`%경영%`은 매칭됨). education_level은 `4년제 대학교` 등 7종.

---

### Task 1: 공유 헬퍼 `common.py` (TDD)

**Files:**
- Create: `examples/test_demos.py`
- Create: `examples/common.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`examples/test_demos.py` 생성:

```python
"""examples 데모 공용 로직 단위 테스트 (pytest).

MCP/LLM 호출이 없는 순수 함수만 검증한다. 통합 경로는 각 스크립트의 --dry-run으로 검증.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import age_band, allocate_quota, extract_json, mean_by, ngram_overlap


def test_allocate_quota_총합은_n과_일치():
    groups = [{"cnt": 70}, {"cnt": 20}, {"cnt": 10}]
    quotas = allocate_quota(groups, 10)
    assert sum(q for _, q in quotas) == 10


def test_allocate_quota_비례_배분():
    groups = [{"cnt": 70}, {"cnt": 20}, {"cnt": 10}]
    quotas = {id(g): q for g, q in allocate_quota(groups, 10)}
    assert quotas[id(groups[0])] == 7
    assert quotas[id(groups[1])] == 2
    assert quotas[id(groups[2])] == 1


def test_allocate_quota_0표본_셀은_제외():
    groups = [{"cnt": 999}, {"cnt": 1}]
    quotas = allocate_quota(groups, 2)
    assert len(quotas) == 1
    assert quotas[0][1] == 2


def test_extract_json_부가설명_섞여도_추출():
    parsed = extract_json('답변입니다: {"score": 4, "reason": "좋다"} 감사합니다')
    assert parsed == {"score": 4, "reason": "좋다"}


def test_extract_json_없으면_None():
    assert extract_json("JSON이 전혀 없는 텍스트") is None


def test_age_band_경계():
    assert age_band(19) == "10대"
    assert age_band(35) == "30대"
    assert age_band(79) == "70대"
    assert age_band(85) == "80대+"


def test_mean_by_그룹별_평균():
    items = [{"k": "a", "v": 1}, {"k": "a", "v": 3}, {"k": "b", "v": 5}]
    out = mean_by(items, lambda i: i["k"], lambda i: i["v"])
    assert out["a"] == {"n": 2, "mean": 2.0}
    assert out["b"] == {"n": 1, "mean": 5.0}


def test_ngram_overlap_표현_복사_검출():
    a = "주말이면 부모님을 모시고 수목원을 거닐며 산책한다"
    b = "그는 주말이면 부모님을 모시고 수목원을 다닌다"
    assert ngram_overlap(a, b) == 1  # "주말이면 부모님을 모시고 수목원을"


def test_ngram_overlap_무관한_문장은_0():
    assert ngram_overlap("완전히 다른 문장 하나입니다", "전혀 상관없는 별개의 글귀") == 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest examples/test_demos.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'common'`
(pytest가 없으면 먼저 `pip install pytest`)

- [ ] **Step 3: `common.py` 구현**

`examples/common.py` 생성 (mcp/anthropic은 함수 내부에서 지연 import — 순수 함수 테스트가 의존성 없이 돌도록):

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest examples/test_demos.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: 커밋**

```bash
git add examples/test_demos.py examples/common.py
git commit -m "feat: examples 공유 헬퍼 common.py 추가 (MCP·층화샘플링·LLM·집계 유틸)"
```

---

### Task 2: `synthetic_survey.py` 리팩토링

**Files:**
- Modify: `examples/synthetic_survey.py` (전체 교체)

- [ ] **Step 1: common.py 사용으로 전체 교체**

`examples/synthetic_survey.py` 를 아래 내용으로 교체 (CLI 인터페이스·출력 형식은 기존과 동일):

```python
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
```

- [ ] **Step 2: dry-run 실행 검증**

Run: `python examples/synthetic_survey.py --dry-run --n 10`
Expected: `[1/3] 모집단: 1,000,000명 ...`, `[2/3] ... 10명 확보`, `[DRY-RUN] MCP 파이프라인 검증 완료` 출력, exit 0

- [ ] **Step 3: 커밋**

```bash
git add examples/synthetic_survey.py
git commit -m "refactor: synthetic_survey.py를 common.py 헬퍼 사용으로 정리"
```

---

### Task 3: `user_simulator.py` — 유저 시뮬레이터 (사례 2, 더미봇 TDD)

**Files:**
- Modify: `examples/test_demos.py` (봇 테스트 추가)
- Create: `examples/user_simulator.py`

- [ ] **Step 1: 더미봇 실패 테스트 추가**

`examples/test_demos.py` 끝에 추가:

```python
def test_bot_격식어휘_해지는_단계진행():
    from user_simulator import DummyTelecomBot
    bot = DummyTelecomBot()
    reply, done = bot.reply("요금제 해지하고 싶습니다")
    assert "위약금" in reply
    assert not done
    reply, done = bot.reply("해지 진행")
    assert done


def test_bot_구어체는_동문서답():
    from user_simulator import DummyTelecomBot
    bot = DummyTelecomBot()
    reply, done = bot.reply("인터넷 그만 쓰고 싶은데예")
    assert "이해하지 못했습니다" in reply
    assert not done


def test_bot_정확한_문구_아니면_미완료():
    from user_simulator import DummyTelecomBot
    bot = DummyTelecomBot()
    bot.reply("해지요")
    reply, done = bot.reply("네 해주세요")
    assert not done
    assert "해지 진행" in reply
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest examples/test_demos.py -v -k bot`
Expected: FAIL — `ModuleNotFoundError: No module named 'user_simulator'`

- [ ] **Step 3: `user_simulator.py` 구현**

```python
"""유저 시뮬레이터 데모 — korean-people-persona MCP 서버 활용 사례 2 구현.

가상 고객 페르소나(LLM)가 결함을 내장한 규칙 기반 상담봇과 멀티턴 대화하고,
LLM judge가 해결 여부·만족도·실패 지점을 채점한다. 연령대별 성공률을 비교한다.

더미 챗봇의 의도된 결함: 격식 어휘("해지", "위약금")와 정확한 문구("해지 진행")만
인식한다 → 구어체·우회 표현을 쓰는 고객층에서 실패가 발생하는지가 관찰 포인트.

사용법:
    python examples/user_simulator.py --dry-run        # 패널 샘플링 + 봇 규칙 점검 (키 불필요)
    python examples/user_simulator.py --per-group 5    # 실제 시뮬레이션 (ANTHROPIC_API_KEY 필요)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from common import (DEFAULT_MODEL, ROOT, build_profile, call_tool, llm_json,
                    llm_text, make_llm_client, mcp_session, mean_by, require_api_key)

GREETING = "안녕하세요, 데모텔레콤 상담봇입니다. 무엇을 도와드릴까요? (해지/위약금/요금제 문의)"
MAX_TURNS = 6

CUSTOMER_TEMPLATE = """당신은 아래 인물입니다. 이 인물의 말투·어휘·성격에서 벗어나지 마세요.

{profile}

상황: 통신사 요금제를 해지하고 싶어 상담봇과 채팅 중입니다. 위약금이 크면 망설입니다.
규칙:
- 이 인물이 실제로 칠 법한 채팅 한 줄만 출력합니다 (설명·따옴표 금지).
- 해지가 접수되었거나, 답답해서 포기하고 싶어지면 발화 끝에 [종료] 를 붙입니다."""

JUDGE_SYSTEM = """당신은 챗봇 품질 평가자입니다. 아래 상담 대화를 보고 JSON으로만 답하세요.
{"resolved": <true|false, 고객 과제(요금제 해지) 해결 여부>,
 "satisfaction": <1~5 정수, 고객 만족도 추정>,
 "failure_point": "<실패했다면 챗봇의 문제 지점 한 줄, 성공이면 null>"}"""

# dry-run 봇 단독 점검용 고정 발화 (구어체 실패 → 격식어 성공 경로)
SMOKE_UTTERANCES = [
    "인터넷 그만 쓰고 싶은데예",
    "돈 물어내는 거 있어요?",
    "해지하고 싶어요",
    "네 해주세요",
    "해지 진행",
]


class DummyTelecomBot:
    """격식 어휘만 인식하는 결함 내장 해지 상담봇 (stage 0→1→완료)."""

    def __init__(self) -> None:
        self.stage = 0

    def reply(self, text: str) -> tuple[str, bool]:
        """고객 발화 → (봇 응답, 해지 접수 완료 여부)."""
        if self.stage == 1:
            if "해지 진행" in text:
                return "해지가 접수되었습니다. 처리까지 영업일 기준 1~2일 소요됩니다.", True
            if "위약금" in text:
                return ("위약금은 잔여 약정 개월수 × 3,000원입니다. "
                        "해지를 원하시면 '해지 진행'이라고 정확히 입력해 주세요."), False
            return "해지를 원하시면 '해지 진행'이라고 정확히 입력해 주세요.", False
        if "해지" in text:
            self.stage = 1
            return ("해지 시 위약금이 발생할 수 있습니다. "
                    "계속하시려면 '해지 진행'이라고 정확히 입력해 주세요."), False
        if "위약금" in text:
            return "위약금은 잔여 약정 개월수 × 3,000원입니다.", False
        if "요금제" in text:
            return "요금제 변경은 홈페이지 > 요금제 메뉴에서 가능합니다. 다른 문의가 있으신가요?", False
        return "문의를 이해하지 못했습니다. '해지', '위약금', '요금제' 중 정확한 단어로 다시 말씀해 주세요.", False


def simulate_dialog(client: Any, model: str, persona: dict[str, Any]) -> dict[str, Any]:
    """페르소나 고객(LLM) ↔ 더미봇 멀티턴 대화 1건."""
    bot = DummyTelecomBot()
    system = CUSTOMER_TEMPLATE.format(profile=build_profile(persona))
    transcript = [{"speaker": "봇", "text": GREETING}]
    messages = [{"role": "user", "content": GREETING}]
    resolved = False
    for _ in range(MAX_TURNS):
        utter = llm_text(client, model, system, messages, max_tokens=200).strip()
        gave_up = "[종료]" in utter
        utter = utter.replace("[종료]", "").strip()
        transcript.append({"speaker": "고객", "text": utter})
        messages.append({"role": "assistant", "content": utter})
        if gave_up:
            break
        reply, resolved = bot.reply(utter)
        transcript.append({"speaker": "봇", "text": reply})
        messages.append({"role": "user", "content": reply})
        if resolved:
            break
    return {"transcript": transcript, "bot_resolved": resolved}


def judge_dialog(client: Any, model: str, transcript: list[dict[str, str]]) -> dict[str, Any]:
    """대화 전문만 보고 채점 (페르소나 원문은 주지 않는다)."""
    text = "\n".join(f"{t['speaker']}: {t['text']}" for t in transcript)
    parsed = llm_json(client, model, JUDGE_SYSTEM, text, max_tokens=300) or {}
    try:
        satisfaction = int(parsed.get("satisfaction"))
    except (TypeError, ValueError):
        satisfaction = None
    return {
        "resolved": bool(parsed.get("resolved", False)),
        "satisfaction": satisfaction if satisfaction and 1 <= satisfaction <= 5 else None,
        "failure_point": parsed.get("failure_point"),
    }


async def run(args: argparse.Namespace) -> int:
    async with mcp_session() as session:
        elders = (await call_tool(session, "sample_persona",
                                  {"filters": {"age_min": 60}, "n": args.per_group, "full": True}))["results"]
        youths = (await call_tool(session, "sample_persona",
                                  {"filters": {"age_max": 29}, "n": args.per_group, "full": True}))["results"]
    panel = [("60세 이상", p) for p in elders] + [("29세 이하", p) for p in youths]
    print(f"[1/3] 패널 확보: 60세 이상 {len(elders)}명 + 29세 이하 {len(youths)}명")
    for group, p in panel:
        print(f"      - [{group}] {p['province']} {p['sex']} {p['age']}세 {p['occupation']}")

    if args.dry_run:
        print("\n[2/3] 더미봇 단독 점검 (고정 발화):")
        bot = DummyTelecomBot()
        for u in SMOKE_UTTERANCES:
            reply, done = bot.reply(u)
            print(f"      고객: {u}\n      봇  : {reply}" + ("  ← 해지 완료" if done else ""))
        print("[DRY-RUN] MCP 파이프라인 + 봇 규칙 검증 완료 (LLM 호출 생략)")
        return 0

    require_api_key()
    client = make_llm_client()

    print(f"[2/3] 시뮬레이션 시작 (model={args.model}, 최대 {MAX_TURNS}턴)")
    results = []
    for i, (group, p) in enumerate(panel, 1):
        dialog = simulate_dialog(client, args.model, p)
        verdict = judge_dialog(client, args.model, dialog["transcript"])
        results.append({
            "group": group,
            "persona": {k: p[k] for k in ("uuid", "sex", "age", "province", "occupation")},
            **dialog, **verdict,
        })
        status = "성공" if verdict["resolved"] else "실패"
        print(f"      [{i}/{len(panel)}] [{group}] {p['age']}세 → {status} "
              f"(만족도 {verdict['satisfaction']})")

    by_group = mean_by(results, lambda r: r["group"], lambda r: 1.0 if r["resolved"] else 0.0)
    summary = {
        "success_rate_by_group": by_group,
        "failure_points": [r["failure_point"] for r in results if r["failure_point"]],
    }
    out_path = ROOT / "simulator_result.json"
    out_path.write_text(json.dumps({"summary": summary, "results": results},
                                   ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[3/3] === 연령대별 성공률 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[DONE] 결과 저장: {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-group", type=int, default=5, help="그룹당 표본 수 (기본 5)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"모델 (기본 {DEFAULT_MODEL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="LLM 호출 없이 패널 샘플링 + 봇 규칙만 검증")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 테스트·dry-run 검증**

Run: `python -m pytest examples/test_demos.py -v`
Expected: PASS (13 passed)

Run: `python examples/user_simulator.py --dry-run --per-group 3`
Expected: 패널 6명 출력 + 봇 단독 점검에서 구어체 발화에 "이해하지 못했습니다", 마지막 "해지 진행"에 "← 해지 완료" 표시, exit 0

- [ ] **Step 5: 커밋**

```bash
git add examples/test_demos.py examples/user_simulator.py
git commit -m "feat: 유저 시뮬레이터 데모 추가 (사례 2 — 결함 내장 더미봇 + LLM judge)"
```

---

### Task 4: `synthetic_reviews.py` — 합성 데이터 생성 (사례 3)

**Files:**
- Create: `examples/synthetic_reviews.py`

- [ ] **Step 1: 구현**

```python
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

SEED_QUERY = "캠핑"
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
```

- [ ] **Step 2: dry-run 검증**

Run: `python examples/synthetic_reviews.py --dry-run --n 5`
Expected: `[1/2] 시드 확보: 5명 (검색 매칭 5명 + 무작위 보충 0명)` (캠핑 매칭이 5명 이상일 때), `[DRY-RUN] ...` 출력, exit 0

- [ ] **Step 3: 커밋**

```bash
git add examples/synthetic_reviews.py
git commit -m "feat: 합성 리뷰 생성 데모 추가 (사례 3 — 시드 검색 + n-gram 복사 검출)"
```

---

### Task 5: `copy_ab_test.py` — 카피 A/B 테스트 (사례 4A)

**Files:**
- Create: `examples/copy_ab_test.py`

- [ ] **Step 1: 구현**

```python
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
```

- [ ] **Step 2: dry-run 검증**

Run: `python examples/copy_ab_test.py --dry-run`
Expected: 세그먼트 1명 이상 출력 (오늘 라이브 검증에서 "트로트 AND 등산과" 유사 조건 1명 매칭 확인 — 0명이면 WARN 경로도 정상 동작), `[DRY-RUN] ...` 또는 `[WARN] ...` 출력

- [ ] **Step 3: 커밋**

```bash
git add examples/copy_ab_test.py
git commit -m "feat: 카피 A/B 테스트 데모 추가 (사례 4A — 세그먼트 검색 + 순서 편향 통제)"
```

---

### Task 6: `npc_casting.py` — NPC/캐릭터 캐스팅 (사례 4B)

**Files:**
- Create: `examples/npc_casting.py`

- [ ] **Step 1: 구현**

```python
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
```

- [ ] **Step 2: dry-run 검증**

Run: `python examples/npc_casting.py --dry-run`
Expected: `[1/3] 기본 조건 사용: ...`, 후보 1명 이상 (2026-06-11 라이브 확인: 해당 조건 2명 이상 매칭), `npc_candidates.md` 생성 (프로필만, 시트 없음), exit 0

- [ ] **Step 3: 커밋**

```bash
git add examples/npc_casting.py
git commit -m "feat: NPC 캐스팅 데모 추가 (사례 4B — brief→조건 변환 + 캐릭터 시트)"
```

---

### Task 7: use-cases.md 수정 (필터 값 버그 + 데모 링크 + 프롬프트 레시피)

**Files:**
- Modify: `docs/use-cases.md`

- [ ] **Step 1: 필터 값 버그 수정**

Edit 1 — 사례 1의 jsonc (기존 51행 부근):

```
old: sample_persona({"filters": {"province": "경기도", "sex": "여자"}, "n": 3, "full": true})
new: sample_persona({"filters": {"province": "경기", "sex": "여자"}, "n": 3, "full": true})
```

Edit 2 — 사례 4B의 jsonc (기존 158~163행 부근):

```
old:
// "부산 영도구 50대 자영업자" 후보 5명
sample_persona({
  "filters": {"province": "부산광역시", "district_like": "영도%",
              "age_min": 50, "age_max": 59, "occupation_like": "%자영업%"},
  "n": 5, "full": true
})
new:
// "부산 영도구 50대 자영업자" 후보 5명
sample_persona({
  "filters": {"province": "부산", "district_like": "%영도%",
              "age_min": 50, "age_max": 59, "occupation_like": "%경영%"},
  "n": 5, "full": true
})
```

Edit 3 — 공통 파이프라인 섹션의 trigram 팁 문단("검색어는 trigram 특성상...") 바로 뒤에 추가:

```markdown

필터 값은 **DB의 실제 표기와 정확히 일치**해야 한다. `province`는 `서울`/`부산`/`경기`/`경상남`처럼
짧은 표기(`부산광역시`는 0건), `district`는 `부산-영도구` 형식, `education_level`은
`4년제 대학교` 등 7종이다. 확신이 없으면 필터를 걸기 전에 `aggregate`로 실제 값을 먼저 확인할 것.
```

- [ ] **Step 2: 사례 2~4에 데모 링크 추가**

사례 2 제목(`## 사례 2 — 챗봇/에이전트 평가용 유저 시뮬레이터`) 바로 아래에:

```markdown

> 동작하는 데모: [`examples/user_simulator.py`](../examples/user_simulator.py)
```

사례 3 제목 바로 아래에:

```markdown

> 동작하는 데모: [`examples/synthetic_reviews.py`](../examples/synthetic_reviews.py)
```

사례 4 제목 바로 아래에:

```markdown

> 동작하는 데모: [`examples/copy_ab_test.py`](../examples/copy_ab_test.py) (시나리오 A) ·
> [`examples/npc_casting.py`](../examples/npc_casting.py) (시나리오 B)
```

- [ ] **Step 3: 사례별 "Claude Code에서 바로 해보기" 블록 추가**

각 사례의 "한계 / 주의점" 소절 **앞**에 아래 블록을 삽입 (사례 4는 시나리오 B 뒤, "한계 / 주의점" 앞에 A·B 두 개 연속 배치). 형식은 5개 모두 동일:

사례 1 (`### 한계 / 주의점` 앞):

````markdown
### ▶ Claude Code에서 바로 해보기

MCP 서버가 등록된 Claude Code 세션에 아래를 붙여넣으면 코드 없이 같은 시나리오가 재현된다.

```text
korean-people-persona MCP로 시도×성별 분포에 비례해 페르소나 10명을 층화 샘플링한 뒤(full=true),
각 인물에게 "월 9,900원에 광고 없이 국내 OTT 3사를 묶어 보는 통합 구독제가 나온다면
가입하시겠습니까?"를 1~5점 + 한 줄 이유로 답하게 해줘. 각 인물의 프로필(소비 성향·미디어
습관·경제 상황)에 충실할 것. 전체/성별/연령대/시도별 평균을 표로 집계해줘.
```
````

사례 2:

````markdown
### ▶ Claude Code에서 바로 해보기

```text
korean-people-persona MCP로 60세 이상 3명과 29세 이하 3명을 뽑아줘(full=true).
각 인물이 통신사 상담봇에게 요금제 해지를 요청하는 채팅을 시뮬레이션해줘 —
네가 고객(인물 말투 유지)과 격식 어휘만 알아듣는 깐깐한 상담봇을 모두 연기해.
대화마다 4~6턴, 끝나면 연령대별로 봇이 실패한 지점을 표로 정리해줘.
```
````

사례 3:

````markdown
### ▶ Claude Code에서 바로 해보기

```text
korean-people-persona MCP에서 hobbies_and_interests에 '캠핑'이 들어간 페르소나 5명을
검색해줘(full=true). 각자가 쓸 법한 캠핑용품 구매 리뷰를 2건씩 생성해줘 —
품목/평점(1~5)/본문 2~4문장. 페르소나 소개 문장의 표현은 재사용하지 말 것.
결과를 인구통계 라벨(성별/나이/지역/직업)과 함께 JSONL 코드블록으로 정리해줘.
```
````

사례 4 (시나리오 B 뒤, "한계 / 주의점" 앞):

````markdown
### ▶ Claude Code에서 바로 해보기

시나리오 A (카피 A/B):

```text
korean-people-persona MCP에서 '등산과 AND 트로트'로 50세 이상 여성을 검색해줘(full=true, 최대 10명).
각 인물에게 등산화 광고 카피 A "흔들리지 않는 착화감, 정상까지 함께"와
B "산에서도 무대처럼 당당하게"를 무작위 순서로 보여주고 선호와 이유를 수집한 뒤,
선호율과 대표 이유를 집계해줘.
```

시나리오 B (캐스팅):

```text
korean-people-persona MCP에서 부산 영도구(district_like '%영도%') 50대 경영자
(occupation_like '%경영%') 페르소나 5명을 뽑아줘(full=true).
각 후보의 말투와 어휘 / 말버릇 / 갈등 요소 / 관계 훅을 정리한
창작용 캐릭터 시트(마크다운)를 만들어줘. 프로필 문장은 복사하지 말고 파생할 것.
```
````

- [ ] **Step 4: 사례 1 데모 링크 형식 확인**

기존 사례 1의 `> 동작하는 데모:` 줄과 새로 추가한 링크들의 형식이 일치하는지 눈으로 확인.

- [ ] **Step 5: 커밋**

```bash
git add docs/use-cases.md
git commit -m "docs: use-cases.md 필터 값 버그 수정 + 데모 링크 + 세션용 프롬프트 레시피 추가"
```

---

### Task 8: 종합 검증

**Files:** 없음 (검증만)

- [ ] **Step 1: 문법·단위 테스트 일괄 확인**

Run: `python -m py_compile examples/common.py examples/synthetic_survey.py examples/user_simulator.py examples/synthetic_reviews.py examples/copy_ab_test.py examples/npc_casting.py`
Expected: 출력 없음, exit 0

Run: `python -m pytest examples/test_demos.py -v`
Expected: PASS (13 passed)

- [ ] **Step 2: 전체 dry-run 재실행**

```bash
python examples/synthetic_survey.py --dry-run --n 10
python examples/user_simulator.py --dry-run --per-group 3
python examples/synthetic_reviews.py --dry-run --n 5
python examples/copy_ab_test.py --dry-run
python examples/npc_casting.py --dry-run
```

Expected: 5개 전부 exit 0, 각각 `[DRY-RUN]` 메시지 출력 (copy_ab_test는 매칭 0명이면 `[WARN]` + exit 1도 허용 — 세그먼트 데이터 의존)

- [ ] **Step 3: 산출물 정리 확인**

`npc_candidates.md`(dry-run 산출물)는 데모 실행 결과물이므로 커밋하지 않는다.
`git status`로 추적 외 파일에 데모 산출물(`npc_candidates.md`)만 남는지 확인.

- [ ] **Step 4: 메인 세션 검증 (주의: 서브에이전트 위임 불가)**

메인 세션(MCP 연결 보유)에서 use-cases.md의 NPC 캐스팅 레시피 프롬프트를 실제 수행해
세션용 레시피가 동작하는지 확인한다. 이 단계는 구현 에이전트가 아닌 메인 세션이 수행.
