# LLM 에이전트 활용 사례 문서 + 합성 설문 데모 — 설계서

날짜: 2026-06-11
상태: 승인됨

## 목적

korean-people-persona MCP 서버(1M행 한국 페르소나, SQLite + FTS5 trigram)를
LLM 에이전트에서 활용하는 사례를 문서화하고, 대표 사례 1개를 동작하는 데모로 구현한다.

## 결과물

### 1. `docs/use-cases.md` — 활용 사례 문서 (커밋 대상)

공통 파이프라인(`aggregate` 분포 파악 → `sample`/`search` 표본 추출 →
`get_persona` 컨텍스트 로드 → LLM 롤플레이 → 결과 집계)을 소개한 뒤,
4개 사례를 동일 골격(시나리오 → 도구 호출 흐름 → 프롬프트 설계 → 한계/주의점)으로 서술:

1. **합성 설문/FGD** — 분포 비례 층화 샘플링 기반 가상 설문. 실제 여론조사 대체 불가 명시.
2. **유저 시뮬레이터** — 챗봇/에이전트 평가용 페르소나 고객 + LLM-as-judge. 인구통계 축 편향 평가 포함.
3. **합성 데이터 생성** — 페르소나 시드 기반 한국어 데이터셋(리뷰·상담 로그 등). CC BY 4.0 라이선스 언급.
4. **마케팅/창작** — trigram 검색 세그먼트 정의 + 카피 A/B 테스트, 캐릭터/NPC 캐스팅.

각 사례에 실제 MCP 도구 호출 예시(JSON 인자)를 포함한다.

### 2. `examples/synthetic_survey.py` — 합성 설문 데모

- `mcp` SDK stdio 클라이언트로 `python -m mcp_server`를 서브프로세스로 띄워 연결 (서버 코드 무수정).
- 흐름: `stats` → `aggregate(["province","sex"])` → 분포 비례 `sample_persona`(기본 N=20)
  → 페르소나 전문을 시스템 프롬프트로 Anthropic API 롤플레이(5점 척도 + 한 줄 이유, JSON 응답)
  → 인구통계 축별 집계 출력 + `survey_result.json` 저장.
- CLI: `--question`(설문 질문), `--n`(표본 수), `--model`(기본 `claude-sonnet-4-6`), `--dry-run`(API 키 없이 MCP 파이프라인만 검증).
- 의존성은 `examples/requirements.txt`(`mcp`, `anthropic`)로 분리.

## 검증

- `--dry-run`으로 MCP 연결~층화 샘플링 왕복 확인.
- 실제 API로 N=5 소규모 1회 실행, 결과 JSON 확인.

## 결정 사항

- 데모 방식: 실제 MCP 클라이언트 연결 (tools.py 직접 호출·프롬프트 레시피 방식은 기각 — MCP 서버임을 증명하는 것이 핵심 메시지).
- 데모 사례: 합성 설문 1개 (5개 도구 전부를 거치는 유일한 파이프라인).
- 나머지 3개 사례는 문서로만 구체화.
