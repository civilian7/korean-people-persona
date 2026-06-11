# Changelog

이 프로젝트의 주요 변경 사항을 기록한다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따른다.

## 2026-06-11 — 활용 데모 샘플 확장

### Added

- **`examples/common.py`** — 데모 공용 헬퍼 모듈. MCP stdio 접속(`mcp_session`),
  도구 호출 파싱(`call_tool`), 시도×성별 분포 비례 층화 샘플링(`stratified_sample`,
  최대 잔여법), 프로필 빌더(`build_profile`), LLM 호출 + JSON 추출(`llm_text`/`llm_json`),
  집계 유틸(`age_band`/`mean_by`/`ngram_overlap`)
- **`examples/test_demos.py`** — 공용 헬퍼 순수 함수 + 더미봇 규칙 단위 테스트 16개 (pytest)
- **`examples/user_simulator.py`** — 활용 사례 2 데모. 가상 고객 페르소나(LLM)가
  격식 어휘만 인식하는 결함 내장 규칙 기반 상담봇과 멀티턴 대화 → LLM judge 채점 →
  연령대별 성공률 비교 (`simulator_result.json`)
- **`examples/synthetic_reviews.py`** — 활용 사례 3 데모. 캠핑 관심사 페르소나 시드로
  상품 리뷰 생성 + 인구통계 라벨 + 어절 4-gram 표현 복사 검출 (`synthetic_reviews.jsonl`)
- **`examples/copy_ab_test.py`** — 활용 사례 4A 데모. trigram 검색 세그먼트에
  카피 2종을 무작위 순서로 제시(순서 편향 통제) → 선호율 집계 (`ab_test_result.json`)
- **`examples/npc_casting.py`** — 활용 사례 4B 데모. 배역 요구(brief)를 검색 조건으로
  변환해 후보 추출 → 후보별 캐릭터 시트 마크다운 생성 (`npc_candidates.md`)
- **`docs/use-cases.md`** — 사례 2~4 데모 링크, 사례별 "Claude Code에서 바로 해보기"
  프롬프트 레시피 5종, trigram 2글자 검색어 우회법·필터 값 정확 일치 주의 문단
- `.gitignore` — 데모 실행 산출물 5종 제외

### Changed

- **`examples/synthetic_survey.py`** — `common.py` 헬퍼 사용으로 리팩토링 (-133/+32줄,
  CLI·출력 형식은 동일)

### Fixed

- **JSON 추출 견고성**: LLM 응답에 JSON 오브젝트가 2개 이상이거나 설명이 섞이면
  조용히 `None`을 반환하던 탐욕적 정규식을 중괄호 균형 스캐너로 교체 (`common.py`)
- **trigram 2글자 검색어 함정**: `캠핑`(2글자)은 trigram 토크나이저에 매칭되지 않아
  시드 검색이 항상 0건이던 문제 → `'"캠핑 " OR 캠핑장 OR 캠핑카'` 조합으로 교체
  (`synthetic_reviews.py`, `docs/use-cases.md`)
- **문서의 필터 값 오류 4건** (`docs/use-cases.md`): 실제 DB 표기와 불일치해 0건을
  반환하던 예시 수정 — `경기도`→`경기`, `부산광역시`→`부산`, `영도%`→`%영도%`
  (district는 `부산-영도구` 형식), `%자영업%`→`%경영%` (occupation에 '자영업' 문자열 없음)
- **A/B 응답 코어션**: LLM이 `"1"`(문자열)로 답하면 무효 처리되던 choice 필드에
  int 코어션 추가 (`copy_ab_test.py`)

### 설계 문서

- 스펙: `docs/superpowers/specs/2026-06-11-persona-demo-samples-design.md`
- 구현 계획: `docs/superpowers/plans/2026-06-11-persona-demo-samples.md`

## 2026-06-11 — 초기 구축

- parquet → SQLite 변환기 (`src/convert`): `persona` 테이블(STRICT, id PK + uuid 유니크)
  + FTS5 trigram 인덱스, 빌드 약 24분 / DB 약 10.7GB
- MCP 서버 (`src/mcp_server`): `search_persona` / `get_persona` / `sample_persona` /
  `aggregate` / `stats` 5개 도구 (stdio)
- LLM 에이전트 활용 사례 문서 (`docs/use-cases.md`) + 합성 설문 데모
  (`examples/synthetic_survey.py`)
