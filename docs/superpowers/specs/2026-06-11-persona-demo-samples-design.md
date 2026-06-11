# 페르소나 활용 데모 샘플 확장 — 설계서

- 날짜: 2026-06-11
- 상태: 사용자 승인됨
- 선행 작업: `2026-06-11-llm-agent-use-cases-design.md` (use-cases.md 4사례 문서 + synthetic_survey.py)

## 목적

use-cases.md에 문서화된 사례 2~4의 **동작하는 데모**를 추가한다. 사례 1(합성 설문)만
데모가 있는 현 상태를 보완해, 4사례 전부 "문서 + 실행 가능한 코드 + 세션용 프롬프트"
3종 세트를 갖춘다. 홍보(PROMO.md)의 근거 자료이자 사용자의 진입 경로 역할.

## 결정 사항 (브레인스토밍 결과)

| 항목 | 결정 |
|------|------|
| 대상 사례 | 4개 전부: 유저 시뮬레이터(2), 합성 데이터 생성(3), 카피 A/B(4A), NPC 캐스팅(4B) |
| 형태 | Python 스크립트 + 사례별 세션용(Claude Code) 프롬프트 레시피 병행 |
| 코드 구성 | 공유 헬퍼 `examples/common.py` + 사례별 얇은 스크립트 4개 (접근 A) |
| 시뮬레이터 대상 챗봇 | 내장 규칙 기반 더미 챗봇 (LLM 호출은 고객 역할만) |
| 프롬프트 레시피 위치 | 별도 파일 아닌 use-cases.md 각 사례 섹션에 내장 |

## 파일 구조

```
examples/
  common.py              # 공유 헬퍼 (신규)
  synthetic_survey.py    # 기존 — common.py 사용으로 리팩토링
  user_simulator.py      # 사례 2 (신규)
  synthetic_reviews.py   # 사례 3 (신규)
  copy_ab_test.py        # 사례 4A (신규)
  npc_casting.py         # 사례 4B (신규)
  requirements.txt       # 변경 없음 (mcp, anthropic)
docs/
  use-cases.md           # 필터 값 오류 수정 + 데모 링크 + 프롬프트 레시피 블록 추가
```

## 공유 헬퍼 `examples/common.py`

`synthetic_survey.py`에서 검증된 코드를 추출·일반화한다. 외부 의존성은 기존
requirements.txt 범위(mcp, anthropic) 유지.

- `mcp_session()` — `python -m mcp_server` stdio 접속 async context manager
  (PYTHONPATH=src, cwd=프로젝트 루트)
- `call_tool(session, name, args) -> dict` — 호출 + structuredContent/텍스트 JSON 파싱
- `stratified_sample(session, n, filters=None) -> list[dict]` — aggregate(province×sex)
  → 최대 잔여법 배분 → 셀별 sample_persona(full=True)
- `allocate_quota(groups, n)` — 최대 잔여법 (기존 함수 이동)
- `build_profile(persona, fields=PROFILE_FIELDS) -> str` — 시스템 프롬프트용 프로필
- `ask_llm_json(client, model, system, user, max_tokens=300) -> dict | None` —
  Anthropic 호출 + 정규식 JSON 블록 추출 (기존 ask_persona의 일반화)
- `age_band(age)`, `mean_by(items, key_fn)` — 집계 유틸
- `require_api_key()` — 키 없으면 안내 메시지 + exit 1 (각 스크립트의 중복 제거)

모든 스크립트 공통 CLI 규약: `--dry-run`(MCP 파이프라인만 실행, 키 불필요),
`--model`(기본 claude-sonnet-4-6), `--n`(해당 시 표본 수). 결과는 각각 JSON/JSONL/MD
파일로 저장하고 콘솔에 요약 출력.

## 사례별 스크립트 설계

### user_simulator.py (사례 2 — 챗봇 평가용 유저 시뮬레이터)

- **더미 챗봇**: "통신사 요금제 해지 상담봇"을 규칙 기반으로 내장. 격식 어휘
  (해지, 위약금, 명의, 약정)에만 키워드 매칭으로 응답하고, 구어체·우회 표현
  ("돈 돌려주는 거", "끊고 싶은데예")에는 동문서답하는 **의도된 결함** 보유.
  결함이 결정론적이므로 "시뮬레이터가 약점을 찾아낸다"는 데모 메시지가 재현 가능.
- **패널**: 60세 이상 5명 + 29세 이하 5명 (use-cases.md 예시 그대로,
  `sample_persona(age_min/age_max)`).
- **대화 루프**: 페르소나 LLM(고객 역, 과제: "요금제를 해지하고 싶다. 위약금이
  있으면 망설인다") ↔ 더미 챗봇, 최대 6턴. 고객 발화만 LLM 호출.
- **채점**: LLM-as-judge가 대화 전문 + 루브릭으로 해결 여부/만족도(1~5)/실패 지점을
  JSON 채점. judge에게 페르소나 원문은 주지 않는다 (use-cases.md 원칙).
- **출력**: `simulator_result.json` + 콘솔에 연령대별 성공률 비교. 기대 결과:
  고령층 성공률 하락이 수치로 드러남.

### synthetic_reviews.py (사례 3 — 한국어 합성 데이터 생성)

- **시드 풀**: `search_persona(query="캠핑", fields=["hobbies_and_interests"])`로
  구성, 목표 수 미달 시 `sample_persona` 무작위로 보충.
- **생성**: 페르소나당 캠핑용품 상품 리뷰 2건 (품목·평점·본문). 프롬프트에
  "페르소나 서술문 표현을 재사용하지 말 것" 명시.
- **중복 검사**: 생성된 리뷰와 페르소나 서술문 간 **4-gram(어절) 중복 검사**를
  구현해 임계치 초과 시 경고 라벨 부착 (use-cases.md 주의점의 코드화).
- **출력**: `synthetic_reviews.jsonl` — 행마다 리뷰 + 인구통계 라벨
  (uuid, sex, age, province, occupation) + 중복 검사 결과.

### copy_ab_test.py (사례 4A — 마케팅 카피 A/B 테스트)

- **세그먼트**: 기본값 `search_persona(query="등산과 AND 트로트",
  filters={age_min: 50, sex: "여자"})` (use-cases.md 예시). `--query`/`--filters`로 교체 가능.
- **카피**: 등산복 광고 카피 2종 기본 내장, `--copy-a`/`--copy-b`로 교체.
- **평가**: 페르소나마다 A/B를 무작위 순서로 제시(순서 편향 통제), 선호(A/B) +
  한 줄 이유를 JSON 수집.
- **출력**: `ab_test_result.json` + 콘솔에 선호율, 대표 이유 상위 N개.

### npc_casting.py (사례 4B — NPC/캐릭터 캐스팅)

- **입력**: `--brief "부산 50대 자영업자, 무뚝뚝하지만 정 많은 조연"` 형태.
  brief를 LLM 1회 호출로 필터/검색어 JSON으로 변환 후 후보 5명 추출
  (`--no-llm-parse` 시 `--filters` JSON 직접 입력으로 우회 가능 — dry-run 경로).
- **생성**: 후보별로 LLM이 대사 톤·말버릇·갈등 요소·관계 훅을 파생한 캐릭터 시트 생성.
- **출력**: `npc_candidates.md` — 마크다운 캐릭터 시트 (유일하게 문서형 출력).

## use-cases.md 수정

1. **필터 값 버그 수정**: jsonc 예시의 `"경기도"` → `"경기"`, `"부산광역시"` → `"부산"`.
   실제 DB 값과 불일치해 0건 반환되는 함정 (2026-06-11 라이브 검증에서 발견).
   카테고리 값 주의 안내(education_level 7종 등 — 필터 전 aggregate로 확인) 추가.
2. **데모 링크**: 사례 2~4에 각 스크립트 링크 추가 (사례 1과 동일 형식).
3. **프롬프트 레시피**: 각 사례 섹션 끝에 "▶ Claude Code에서 바로 해보기" 블록 —
   MCP 서버가 등록된 Claude Code 세션에 복붙하면 코드 없이 같은 시나리오가
   재현되는 프롬프트 1개씩 (총 5개, 사례 1 포함).

## 검증 전략

- 스크립트 4개 + 리팩토링된 synthetic_survey.py 전부 `--dry-run` 라이브 실행
  (API 키 불필요 — 현 세션에서 검증 가능).
- 프롬프트 레시피 중 1개(NPC 캐스팅)를 현 세션에서 실제 수행해 동작 확인.
- LLM 호출 경로는 코드 리뷰 수준 (환경에 API 키 없음 — 기존과 동일한 한계,
  ask_llm_json 로직 자체는 synthetic_survey.py에서 검증된 패턴의 이동).
- 파이썬 문법 검증: `python -m py_compile` 전 파일.

## 한계 / 비범위

- LLM 호출 실거래 검증은 키 부재로 비범위 (사용자가 추후 직접 실행).
- 더미 챗봇은 데모용 결함 내장이 목적 — 실제 챗봇 품질 평가 도구가 아님.
- 외부 HTTP 챗봇 연동, 멀티턴 judge 고도화 등은 비범위.
