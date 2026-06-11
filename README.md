# korean-people-persona

HuggingFace [`nvidia/Nemotron-Personas-Korea`](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea) 데이터셋(약 100만 행, 9개 parquet 파일)을 SQLite로 변환·검색하기 위한 도구 모음.

## 개요

- **출처**: NVIDIA, *Nemotron-Personas-Korea* — https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea
- **라이선스**: 원 데이터셋 페이지의 라이선스 조항을 따름

- **DB 파일**: `database/persona.db`
- **원본 parquet**: `data/train-*-of-*.parquet`
- **테이블**: `persona` (메인) + `persona_fts` (FTS5 외부 콘텐츠 인덱스)
- **타깃 SQLite**: 3.37+ (FTS5, STRICT 테이블, JSON1 사용)
- **Python**: 3.10 이상 (3.11+ 권장)
- **의존성**: `pyarrow >= 15.0`, `huggingface_hub >= 0.24` (`requirements.txt` 참조)
- **디스크 여유**: 약 13 GB (parquet ~2GB + DB 실측 ~10.7GB)

변경 이력은 [CHANGELOG.md](CHANGELOG.md) 참조.

## 데이터 출처

| 항목 | 값 |
|---|---|
| 저장소 | [`nvidia/Nemotron-Personas-Korea`](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea) |
| 파일 | `train-0000{0..8}-of-00009.parquet` (9개) |
| 파일당 행 수 | 약 111,112 |
| 총 행 수 | 1,000,000 |
| 결측치 | 모든 컬럼에서 0 (NOT NULL 보장) |
| `country` | 모두 `대한민국` 단일값 |
| `*_list` | 파이썬 `repr` 형식의 문자열 → JSON 배열로 정규화 |

## 폴더 구조

```
korean-people-persona/
├── data/                  # 원본 parquet (gitignore — 약 2GB)
│   └── train-*-of-*.parquet
├── database/              # 생성된 SQLite (gitignore — 약 10.7GB)
│   └── persona.db
├── src/
│   ├── convert/                # parquet → SQLite 변환기
│   └── mcp_server/             # MCP 서버 (도구 5종, stdio)
├── examples/              # 활용 데모 스크립트 (아래 '활용 데모' 참조)
│   ├── common.py               # 데모 공용 헬퍼
│   ├── synthetic_survey.py     # 사례 1 — 합성 설문
│   ├── user_simulator.py       # 사례 2 — 챗봇 평가용 유저 시뮬레이터
│   ├── synthetic_reviews.py    # 사례 3 — 합성 리뷰 데이터 생성
│   ├── copy_ab_test.py         # 사례 4A — 카피 A/B 테스트
│   ├── npc_casting.py          # 사례 4B — NPC/캐릭터 캐스팅
│   ├── test_demos.py           # 단위 테스트 (pytest)
│   └── requirements.txt        # 데모 전용 의존성 (mcp, anthropic)
├── docs/
│   └── use-cases.md            # LLM 에이전트 활용 사례 4종 + 프롬프트 레시피
├── build.sh / build.bat / build.ps1
├── requirements.txt
├── CHANGELOG.md
└── README.md
```

`data/`와 `database/`는 용량이 크므로 `.gitignore`로 폴더째 제외됩니다.

## 데이터셋 다운로드

세 가지 방법 중 하나를 선택. 결과 파일은 `data/` 폴더에 `train-*-of-*.parquet` 형태로 위치해야 함.

### 1) 변환 스크립트 옵션 (권장)

`src/convert` 패키지가 누락 시 자동으로 가져옴:

```bash
pip install huggingface_hub pyarrow
PYTHONPATH=src python -m convert --download              # 없을 때만 받음
PYTHONPATH=src python -m convert --download --force-download   # 항상 재다운로드
```

### 2) huggingface-cli 직접 사용

```bash
pip install huggingface_hub
huggingface-cli download nvidia/Nemotron-Personas-Korea \
    --repo-type dataset \
    --include "train-*-of-*.parquet" \
    --local-dir ./data
```

### 3) git lfs 클론

```bash
git lfs install
git clone https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea
mv Nemotron-Personas-Korea/train-*.parquet ./data/
```

> **인증**: 비공개 또는 게이트 모델의 경우 `huggingface-cli login` 또는 `HF_TOKEN` 환경변수 필요. 본 데이터셋(공개 시점 기준)은 비인증으로도 다운로드 가능.

> **용량**: parquet 9개 합계 약 1~2 GB.

## 메인 테이블 `persona`

```sql
CREATE TABLE persona (
  id                         INTEGER PRIMARY KEY,                                  -- rowid 별칭 (자동 증가)
  uuid                       TEXT    NOT NULL,                                     -- 원본 32자 hex 문자열 (대시 없음, 유니크 인덱스)
  -- 페르소나 서술 (긴 한국어 텍스트) ----------------------------------------------
  persona                    TEXT    NOT NULL,                                     -- 핵심 1~2문장 요약
  professional_persona       TEXT    NOT NULL,                                     -- 직업/업무 페르소나
  sports_persona             TEXT    NOT NULL,                                     -- 스포츠/운동 페르소나
  arts_persona               TEXT    NOT NULL,                                     -- 예술/문화 페르소나
  travel_persona             TEXT    NOT NULL,                                     -- 여행 페르소나
  culinary_persona           TEXT    NOT NULL,                                     -- 식문화/요리 페르소나
  family_persona             TEXT    NOT NULL,                                     -- 가족 관계 페르소나
  cultural_background        TEXT    NOT NULL,                                     -- 문화·성장 배경 서술
  skills_and_expertise       TEXT    NOT NULL,                                     -- 보유 기술/전문성 서술
  hobbies_and_interests      TEXT    NOT NULL,                                     -- 취미·관심사 서술
  career_goals_and_ambitions TEXT    NOT NULL,                                     -- 향후 목표/포부
  -- 리스트 (JSON 배열로 저장) -----------------------------------------------------
  skills_and_expertise_list  TEXT    NOT NULL CHECK(json_valid(skills_and_expertise_list)),   -- 스킬 키워드 JSON 배열
  hobbies_and_interests_list TEXT    NOT NULL CHECK(json_valid(hobbies_and_interests_list)),  -- 취미 키워드 JSON 배열
  -- 인구통계 ---------------------------------------------------------------------
  sex              TEXT    NOT NULL,                                               -- 성별: 남자 / 여자
  age              INTEGER NOT NULL CHECK(age >= 0),                               -- 나이 (정수)
  marital_status   TEXT    NOT NULL,                                               -- 결혼상태 (4종: 미혼/기혼/이혼/사별 등)
  military_status  TEXT    NOT NULL,                                               -- 병역상태 (군필/해당없음 등)
  family_type      TEXT    NOT NULL,                                               -- 가구 유형 (39종: 1인 가구, 배우자와 자녀 등)
  housing_type     TEXT    NOT NULL,                                               -- 주거 형태 (6종: 아파트, 단독주택 등)
  education_level  TEXT    NOT NULL,                                               -- 최종 학력 (7종: 초등학교 ~ 대학원)
  bachelors_field  TEXT    NOT NULL,                                               -- 학사 전공 분야
  occupation       TEXT    NOT NULL,                                               -- 직업 (자유 텍스트)
  district         TEXT    NOT NULL,                                               -- 시군구 (예: 강남-서초)
  province         TEXT    NOT NULL,                                               -- 시도 (17종)
  country          TEXT    NOT NULL DEFAULT '대한민국'                             -- 국가 (단일값: 대한민국)
) STRICT;
```

### 인덱스

| 이름 | 컬럼 | 용도 |
|---|---|---|
| `idx_persona_demo` | `(sex, age)` | 성/연령 분포 쿼리 |
| `idx_persona_region` | `(province, district)` | 지역 필터 |
| `idx_persona_edu_occ` | `(education_level, occupation)` | 학력/직업 분석 |
| `idx_persona_family` | `(family_type, marital_status)` | 가구/결혼 분석 |
| `idx_persona_prov_sex` | `(province, sex)` | 시도×성별 집계·층화 샘플링 커버링 |
| `idx_persona_uuid` | `(uuid)` UNIQUE | uuid 단건 조회 |

### 컬럼 의미

| 컬럼 | 설명 | 예시 |
|---|---|---|
| `uuid` | 32자 hex 문자열 (대시 없음). 유니크 | `03b4f36a18e6469386d0286dddd513c8` |
| `persona` | 핵심 1~2문장 요약 | `"농촌 지역에서 평생 농업 일을 해온 70대 남성으로..."` |
| `*_persona` | 영역별 상세 페르소나 (수문장 길이) | 직업/스포츠/예술/여행/식문화/가족 |
| `cultural_background` | 문화·성장 배경 서술 | |
| `skills_and_expertise` | 보유 기술 서술 | |
| `skills_and_expertise_list` | 위 항목의 키워드 리스트 (JSON 배열) | `["엑셀 활용","문서 작성"]` |
| `hobbies_and_interests` | 취미·관심사 서술 | |
| `hobbies_and_interests_list` | 위 항목의 키워드 리스트 (JSON 배열) | `["등산","낚시"]` |
| `career_goals_and_ambitions` | 향후 목표 | |
| `sex` | `남자` / `여자` | |
| `age` | 정수 | |
| `marital_status` | 4종 | `미혼` / `기혼` / `이혼` / `사별` 등 |
| `military_status` | 2종 | `군필` / `해당없음` 등 |
| `family_type` | 39종 | `배우자와 자녀`, `1인 가구` 등 |
| `housing_type` | 6종 | `아파트`, `단독주택` 등 |
| `education_level` | 7종 | `초등학교` ~ `대학원` |
| `bachelors_field` | 학사 전공 분야 | |
| `occupation` | 직업 (자유 텍스트) | |
| `district` | 시군구 | `강남-서초` |
| `province` | 시도 | `서울`, `경기` 등 17종 |
| `country` | 국가 | `대한민국` (단일값) |

## 전문 검색 — `persona_fts` (FTS5)

긴 한국어 서술 컬럼 10개를 외부 콘텐츠 방식으로 인덱싱.

```sql
CREATE VIRTUAL TABLE persona_fts USING fts5(
  professional_persona,
  sports_persona,
  arts_persona,
  travel_persona,
  culinary_persona,
  family_persona,
  cultural_background,
  skills_and_expertise,
  hobbies_and_interests,
  career_goals_and_ambitions,
  content='persona',
  content_rowid='id',
  tokenize='trigram'
);
```

**토크나이저**: `trigram` — 연속 3글자를 토큰으로 사용하므로 형태소 분석 없이 **부분 문자열 매칭**이 된다.

- **3글자 이상** 검색어는 조사가 붙은 형태도 그대로 매칭됨 (`등산과`, `트로트`) — prefix `*` 불필요
- **2글자 이하는 매칭 불가** (`캠핑` → 0건). 공백 포함 구절(`'"캠핑 "'`)이나 합성어 OR 조합(`'캠핑장 OR 캠핑카'`)으로 우회
- 불린 연산(`AND`/`OR`/`NOT`)과 큰따옴표 구절 검색 지원
- 더 정교한 한국어 처리가 필요하면 `mecab-ko` / `kiwi` 기반 커스텀 토크나이저로 교체

**FTS 동기화**: 데이터셋이 정적이므로 1회 `INSERT INTO persona_fts(rowid, ...) SELECT ...`로 빌드. 변경이 있으면 트리거를 추가.

## AI 에이전트 활용 (MCP 서버)

본 저장소는 **MCP(Model Context Protocol) 서버**를 제공하므로 Claude Desktop, Cursor, Cline 등 MCP 호환 에이전트가 데이터를 직접 검색·샘플링할 수 있습니다.

### 실행

```bash
PYTHONPATH=src python -m mcp_server          # stdio 서버 시작
```

### 에이전트별 등록 방법

> 모든 예시는 **저장소 절대경로 `/abs/path/to/korean-people-persona`** 를 본인 환경에 맞춰 바꿔야 합니다.
> 가상환경(`.venv`)을 만든 경우 `command`를 venv 안 파이썬으로 지정하면 의존성 충돌이 없습니다.
> (예: macOS/Linux `/abs/path/.venv/bin/python`, Windows `C:/abs/path/.venv/Scripts/python.exe`)

#### Claude Desktop

설정 파일 위치:

| OS | 경로 |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

또는 앱 내 **Settings → Developer → Edit Config** 메뉴.

```json
{
  "mcpServers": {
    "korean-persona": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "/abs/path/to/korean-people-persona/src",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

저장 후 **Claude Desktop 재시작** → 채팅창 우하단 망치(🔨) 아이콘에서 5개 도구 노출 확인.

#### Claude Code (CLI)

CLI 명령으로 한 줄 등록:

```bash
claude mcp add korean-persona python -m mcp_server \
  -e PYTHONPATH=/abs/path/to/korean-people-persona/src \
  -e PYTHONIOENCODING=utf-8
```

또는 프로젝트 루트의 `.mcp.json` / 사용자 설정 `~/.claude/settings.json`에 직접 작성:

```json
{
  "mcpServers": {
    "korean-persona": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "env": { "PYTHONPATH": "/abs/path/to/korean-people-persona/src" }
    }
  }
}
```

확인: `claude mcp list` → 활성화 후 `/mcp` 슬래시 명령으로 도구 호출 가능.

#### Cursor

프로젝트별 `.cursor/mcp.json` 또는 사용자 전역 `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "korean-persona": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "env": { "PYTHONPATH": "/abs/path/to/korean-people-persona/src" }
    }
  }
}
```

또는 **Settings → MCP → Add new MCP Server** UI 사용. 커서 재시작 후 `@korean-persona`로 호출.

#### ChatGPT (Developer Mode / Connectors)

ChatGPT의 MCP 통합은 **HTTP/SSE 트랜스포트** 기반으로 동작합니다(원격 커넥터). 본 서버는 stdio 서버이므로 그대로는 등록할 수 없고, **HTTP 어댑터로 감싸서** 노출해야 합니다.

1. `mcp` SDK의 HTTP 트랜스포트로 서버 실행:
   ```bash
   PYTHONPATH=src python -m mcp_server --transport sse --port 8765
   ```
   (현재 본 저장소 `server.py`는 stdio만 호출. HTTP/SSE 모드를 쓰려면 `mcp.run(transport="sse", port=8765)`로 분기 추가가 필요합니다.)

2. ngrok / Cloudflare Tunnel 등으로 외부 노출:
   ```bash
   ngrok http 8765
   ```

3. ChatGPT → **Settings → Connectors → Developer mode → Add custom connector**
   - URL: `https://<ngrok>/sse`
   - 인증: 필요 시 Bearer 토큰 헤더 추가 (`MCP_AUTH_TOKEN`)

4. 새 채팅에서 **Tools** 메뉴에서 커넥터를 활성화하면 도구 호출 가능.

> 보안 주의: ChatGPT 커넥터는 모델 외부에 도구를 노출하므로 **공개 URL은 반드시 인증으로 보호**하세요. 로컬 전용이면 stdio 기반 Claude Desktop / Cursor 사용을 권장.

#### Gemini CLI

Google `gemini-cli` 사용자 설정 `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "korean-persona": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "env": { "PYTHONPATH": "/abs/path/to/korean-people-persona/src" },
      "cwd": "/abs/path/to/korean-people-persona"
    }
  }
}
```

확인: `gemini mcp list` (또는 CLI 내 `/mcp` 명령) → 도구 자동 노출.

#### 공통 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| 도구가 안 보임 | 앱 재시작 누락. Claude Desktop은 완전 종료 필요 (트레이 아이콘까지) |
| `ModuleNotFoundError: mcp_server` | `PYTHONPATH`가 `src`를 가리키는지 확인 (절대경로 권장) |
| 한글 깨짐 | `env.PYTHONIOENCODING=utf-8` 추가 (특히 Windows) |
| `python` 명령 못 찾음 | `command`를 절대경로로 (예: `/usr/bin/python3`, `C:/Python311/python.exe`, venv의 python) |
| 권한 오류 | Windows에서 경로 공백 → 따옴표 또는 경로 변경 |

### 노출 도구

| 도구 | 설명 |
|---|---|
| `search_persona(query, fields, filters, limit, full)` | FTS5 자유 텍스트 검색 + 인구통계 필터 결합 (BM25 정렬) |
| `get_persona(uuid)` | uuid로 단일 페르소나 전체 조회 |
| `sample_persona(filters, n, full)` | 조건부 무작위 샘플링 |
| `aggregate(group_by, filters, limit)` | 인구통계 GROUP BY COUNT |
| `stats()` | 전체 데이터셋 통계·사용 가능 컬럼 안내 |

### 에이전트 활용 샘플

#### 1) 마케팅 인터뷰 시뮬레이션
> "60대 이상 여성 중 등산을 즐기는 분 10명을 샘플링해서, 새로 출시한 무릎 보호대 광고 카피에 대한 반응을 시뮬레이션해줘."

에이전트는 다음 흐름으로 작동:
1. `search_persona(query="등산을 OR 등산과", filters={"sex":"여자","age_min":60}, limit=10, full=True)`
2. 각 페르소나를 시스템 프롬프트로 주입 → 광고 카피 평가 응답 1인 1건씩 생성
3. 응답 클러스터링 후 인사이트 요약

#### 2) 지역 기반 캐릭터 캐스팅
> "부산 영도구에 사는 50대 자영업자 페르소나를 찾아서, 단편소설 주인공으로 쓸 수 있게 정리해줘."

```
search_persona(
  filters={"province":"부산", "district_like":"%영도%",
           "age_min":50, "age_max":59,
           "occupation_like":"%경영%"},   # occupation에 '자영업' 문자열은 없음 — 실제 값은 '소규모 상점 경영자' 등
  limit=5, full=True
)
```

#### 3) 정책 영향 분석
> "초등학교 졸업이 최종 학력인 70대 이상 1인 가구가 어느 시도에 가장 많은지 분포 분석해줘."

```
aggregate(
  group_by=["province"],
  filters={"education_level":"초등학교", "age_min":70,
           "family_type_like":"%혼자%"},
  limit=20
)
```

#### 4) 의미 기반 검색 + 인용
> "농촌에서 자랐고 손주가 있는 페르소나를 찾아 cultural_background 인용과 함께 알려줘."

```
search_persona(
  query='농촌에서 AND 손주들',
  fields=["cultural_background", "family_persona"],
  limit=5, full=True
)
```

#### 5) 합성 설문조사
> "전국 인구 분포에 비례해서 100명을 층화 샘플링한 뒤, 각자에게 '주 4일제 도입에 찬성하느냐'고 물어봐줘."

1. `aggregate(group_by=["province","sex","age"])` → 분포 비율 계산
2. 비율대로 `sample_persona`를 시도×성별×연령대별로 호출
3. 각 페르소나로 LLM에 1:1 응답 요청
4. 결과 집계 → 가중치 적용한 찬반 분포 산출

### 직접 사용 (코드)

MCP 없이 파이썬에서 바로 호출:

```python
import sys; sys.path.insert(0, "src")
from mcp_server import tools

tools.stats()
tools.search_persona(query="용접공", filters={"sex":"남자"}, limit=5)
tools.sample_persona(filters={"province":"제주"}, n=3, full=True)
```

## 활용 데모 (`examples/`)

[`docs/use-cases.md`](docs/use-cases.md)의 활용 사례 4종에 대응하는 **동작하는 데모 스크립트**.
각 사례 문서에는 코드 없이 Claude Code 세션에 붙여넣어 재현하는 "▶ Claude Code에서 바로 해보기"
프롬프트 레시피도 포함되어 있다.

| 스크립트 | 사례 | 내용 | 산출물 |
|---|---|---|---|
| `synthetic_survey.py` | 1 | 인구 비례 층화 샘플링 합성 설문 (5점 척도 + 이유) | `survey_result.json` |
| `user_simulator.py` | 2 | 가상 고객 ↔ 결함 내장 더미 상담봇 멀티턴 대화 + LLM judge 채점 | `simulator_result.json` |
| `synthetic_reviews.py` | 3 | 관심사 시드 상품 리뷰 생성 + 인구통계 라벨 + 표현 복사 검출 | `synthetic_reviews.jsonl` |
| `copy_ab_test.py` | 4A | 관심사 세그먼트 카피 A/B 선호 평가 (제시 순서 무작위화) | `ab_test_result.json` |
| `npc_casting.py` | 4B | 배역 요구 → 후보 추출 → 캐릭터 시트 생성 | `npc_candidates.md` |

`common.py`는 다섯 스크립트가 공유하는 헬퍼(MCP 접속·층화 샘플링·LLM 호출·집계)다.

### 설치

```bash
pip install -r examples/requirements.txt    # mcp, anthropic
```

### 실행

모든 스크립트는 **프로젝트 루트에서** 실행하며, MCP 서버를 직접 띄울 필요 없이
스크립트가 stdio로 자체 기동한다 (`database/persona.db` 빌드 선행 필요).

```bash
# 1) dry-run — API 키 없이 MCP 파이프라인(샘플링/검색)만 검증
python examples/synthetic_survey.py --dry-run --n 10
python examples/user_simulator.py --dry-run --per-group 3
python examples/synthetic_reviews.py --dry-run --n 5
python examples/copy_ab_test.py --dry-run
python examples/npc_casting.py --dry-run

# 2) 실제 실행 — LLM 롤플레이 포함 (ANTHROPIC_API_KEY 필요, 호출량만큼 과금)
#    Linux/macOS: export ANTHROPIC_API_KEY=sk-ant-...
#    PowerShell:  $env:ANTHROPIC_API_KEY = "sk-ant-..."
python examples/synthetic_survey.py --n 20 --question "주 4일제 도입에 찬성하십니까?"
python examples/user_simulator.py --per-group 5
python examples/synthetic_reviews.py --n 10
python examples/copy_ab_test.py --copy-a "카피 A 문구" --copy-b "카피 B 문구"
python examples/npc_casting.py --brief "서울 30대 미혼 직장인 조연"
```

공통 옵션: `--dry-run`(키 불필요), `--model`(기본 `claude-sonnet-4-6`), 표본 수(`--n` 등).
세부 옵션은 각 스크립트의 `--help` 참조. 산출물은 프로젝트 루트에 저장되며 gitignore 처리되어 있다.

### 테스트

```bash
python -m pytest examples/test_demos.py -v    # 순수 함수 + 더미봇 규칙 16개
```

## SQL 직접 쿼리

```sql
-- 1) 등산을 좋아하고 트로트 관련 언급이 있는 60대 여성 (trigram — 3글자 이상, '*' 불필요)
SELECT p.uuid, p.age, p.province, p.occupation
FROM persona_fts f
JOIN persona p ON p.id = f.rowid
WHERE persona_fts MATCH '등산과 AND 트로트'
  AND p.sex = '여자' AND p.age BETWEEN 60 AND 79
ORDER BY bm25(persona_fts) LIMIT 20;

-- 2) 특정 컬럼 검색 + 스니펫
SELECT p.uuid, snippet(persona_fts, 7, '<b>', '</b>', '...', 10) AS hit
FROM persona_fts f JOIN persona p ON p.id = f.rowid
WHERE f.skills_and_expertise MATCH '용접공' LIMIT 10;

-- 3) JSON 리스트 펼치기
SELECT p.uuid, j.value AS hobby
FROM persona p, json_each(p.hobbies_and_interests_list) j
WHERE j.value LIKE '%낚시%' LIMIT 10;

-- 4) 인구통계 분포
SELECT province, sex, COUNT(*) cnt
FROM persona GROUP BY province, sex ORDER BY cnt DESC;
```

## PRAGMA 설정 (적재/운영)

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA temp_store   = MEMORY;
PRAGMA cache_size   = -262144;   -- 256MB
```

## 빌드 절차

### 한 줄 빌드 (권장)

OS별 래퍼 스크립트가 가상환경 생성 → 의존성 설치 → 다운로드 → 변환까지 자동 수행.

| 플랫폼 | 명령 |
|---|---|
| **Linux / macOS** | `chmod +x build.sh && ./build.sh` |
| **Windows (cmd)** | `build.bat` |
| **Windows (PowerShell)** | `.\build.ps1` |

재다운로드 옵션은 모두 동일하게 전달:

```bash
./build.sh --force-download
build.bat --force-download
.\build.ps1 --force-download
```

> PowerShell에서 실행 정책 오류가 나면:
> `PowerShell -ExecutionPolicy Bypass -File .\build.ps1`

### 수동 실행

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows:     .venv\Scripts\activate
pip install -r requirements.txt
PYTHONPATH=src python -m convert [--download] [--force-download]
```

내부 처리:

1. (옵션) `--download` 시 parquet 누락분을 HuggingFace에서 받음
2. `persona.db` 신규 생성 (기존 파일 삭제)
3. PRAGMA 설정 + 스키마/인덱스 생성
4. 9개 parquet을 순차 읽어 행 단위 정규화 후 `executemany` 적재 (트랜잭션 단위: 파일 1개)
5. `*_list` 컬럼은 `ast.literal_eval` → `json.dumps(ensure_ascii=False)` 변환
6. FTS5 가상 테이블 생성 + `INSERT ... SELECT` 1회 빌드
7. `INSERT INTO persona_fts(persona_fts) VALUES('optimize')` 후 `ANALYZE`
8. WAL 체크포인트 후 종료

## 디스크 사용량 (실측)

- `persona.db` 합계 약 **10.7 GB** (메인 테이블 + 인덱스 + FTS5 trigram)
- 빌드 소요 시간 약 24분 (장비에 따라 상이)
- trigram 토크나이저는 모든 3글자 조합을 인덱싱하므로 unicode61 대비 용량이 크다 —
  부분 문자열 매칭의 대가
