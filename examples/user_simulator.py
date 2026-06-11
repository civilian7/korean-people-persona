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
