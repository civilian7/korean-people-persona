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
