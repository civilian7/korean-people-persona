"""examples 데모 공용 로직 단위 테스트 (pytest).

MCP/LLM 호출이 없는 순수 함수만 검증한다. 통합 경로는 각 스크립트의 --dry-run으로 검증.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import age_band, allocate_quota, build_profile, extract_json, mean_by, ngram_overlap


def test_allocate_quota_총합은_n과_일치():
    groups = [{"cnt": 70}, {"cnt": 20}, {"cnt": 10}]
    quotas = allocate_quota(groups, 10)
    assert sum(q for _, q in quotas) == 10


def test_allocate_quota_비례_배분():
    groups = [{"cnt": 70}, {"cnt": 20}, {"cnt": 10}]
    quotas = allocate_quota(groups, 10)
    assert quotas[0][1] == 7
    assert quotas[1][1] == 2
    assert quotas[2][1] == 1


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


def test_extract_json_여러_오브젝트면_첫번째():
    text = '{"first": 1} 그리고 {"second": 2}'
    assert extract_json(text) == {"first": 1}


def test_extract_json_중첩_오브젝트():
    text = '결과: {"outer": {"inner": 3}, "ok": true}'
    assert extract_json(text) == {"outer": {"inner": 3}, "ok": True}


def test_age_band_80세_경계():
    assert age_band(80) == "80대+"


def test_build_profile_None_필드_제외():
    p = {"persona": "한 줄 소개", "sex": "여자", "age": None}
    out = build_profile(p, ["persona", "sex", "age"])
    assert out == "- persona: 한 줄 소개\n- sex: 여자"


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
