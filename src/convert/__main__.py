"""
korean-people-persona parquet -> SQLite 변환기.

데이터 출처:
    NVIDIA, Nemotron-Personas-Korea
    https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea

사용법:
    python convert_to_sqlite.py                # 현재 폴더에 있는 parquet으로 변환
    python convert_to_sqlite.py --download     # 누락 시 HuggingFace에서 자동 다운로드
    python convert_to_sqlite.py --download --force-download   # 항상 재다운로드
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]  # src/convert/ → 프로젝트 루트
DATA_DIR = ROOT / "data"
DB_DIR = ROOT / "database"
DB_PATH = DB_DIR / "persona.db"
PARQUET_GLOB = str(DATA_DIR / "train-*-of-*.parquet")

HF_REPO_ID = "nvidia/Nemotron-Personas-Korea"
HF_REPO_TYPE = "dataset"
HF_PARQUET_PATTERN = "train-*-of-*.parquet"

COLUMNS = [
    "uuid",
    "persona",
    "professional_persona",
    "sports_persona",
    "arts_persona",
    "travel_persona",
    "culinary_persona",
    "family_persona",
    "cultural_background",
    "skills_and_expertise",
    "hobbies_and_interests",
    "career_goals_and_ambitions",
    "skills_and_expertise_list",
    "hobbies_and_interests_list",
    "sex",
    "age",
    "marital_status",
    "military_status",
    "family_type",
    "housing_type",
    "education_level",
    "bachelors_field",
    "occupation",
    "district",
    "province",
    "country",
]

LIST_COLUMNS = {"skills_and_expertise_list", "hobbies_and_interests_list"}

FTS_COLUMNS = [
    "professional_persona",
    "sports_persona",
    "arts_persona",
    "travel_persona",
    "culinary_persona",
    "family_persona",
    "cultural_background",
    "skills_and_expertise",
    "hobbies_and_interests",
    "career_goals_and_ambitions",
]

DDL = f"""
CREATE TABLE persona (
  id                         INTEGER PRIMARY KEY,                                  -- rowid 별칭 (자동 증가)
  uuid                       TEXT    NOT NULL,                                     -- 원본 32자 hex 문자열 (대시 없음)
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
  marital_status   TEXT    NOT NULL,                                               -- 결혼상태 (4종)
  military_status  TEXT    NOT NULL,                                               -- 병역상태
  family_type      TEXT    NOT NULL,                                               -- 가구 유형 (39종)
  housing_type     TEXT    NOT NULL,                                               -- 주거 형태 (6종)
  education_level  TEXT    NOT NULL,                                               -- 최종 학력 (7종)
  bachelors_field  TEXT    NOT NULL,                                               -- 학사 전공 분야
  occupation       TEXT    NOT NULL,                                               -- 직업 (자유 텍스트)
  district         TEXT    NOT NULL,                                               -- 시군구
  province         TEXT    NOT NULL,                                               -- 시도 (17종)
  country          TEXT    NOT NULL DEFAULT '대한민국'                             -- 국가 (단일값)
) STRICT;

CREATE INDEX idx_persona_demo    ON persona(sex, age);
CREATE INDEX idx_persona_region  ON persona(province, district);
CREATE INDEX idx_persona_edu_occ ON persona(education_level, occupation);
CREATE INDEX idx_persona_family  ON persona(family_type, marital_status);
CREATE INDEX idx_persona_prov_sex ON persona(province, sex);  -- 시도×성별 집계/층화 샘플링용 커버링 인덱스
CREATE UNIQUE INDEX idx_persona_uuid ON persona(uuid);
"""

# trigram: 연속 3글자를 토큰으로 사용 — 형태소 분석 없이 한국어 부분 문자열 매칭 지원.
# 단, 3글자 미만 검색어는 매칭 불가. trigram 특성상 prefix 인덱스는 불필요.
FTS_DDL = f"""
CREATE VIRTUAL TABLE persona_fts USING fts5(
  {", ".join(FTS_COLUMNS)},
  content='persona',
  content_rowid='id',
  tokenize='trigram'
);
"""

INSERT_SQL = (
    "INSERT INTO persona (" + ", ".join(COLUMNS) + ") VALUES ("
    + ", ".join(["?"] * len(COLUMNS)) + ")"
)


def normalize_list_field(value: object) -> str:
    """파이썬 repr 리스트 문자열을 JSON 배열 문자열로 정규화."""
    if value is None:
        return "[]"
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    s = str(value)
    try:
        parsed = ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return json.dumps([s], ensure_ascii=False)
    if not isinstance(parsed, (list, tuple)):
        parsed = [parsed]
    return json.dumps(list(parsed), ensure_ascii=False)


def iter_rows(parquet_path: str):
    table = pq.read_table(parquet_path, columns=COLUMNS)
    py = table.to_pydict()
    n = len(py["uuid"])
    for i in range(n):
        row = []
        for col in COLUMNS:
            v = py[col][i]
            if col in LIST_COLUMNS:
                v = normalize_list_field(v)
            row.append(v)
        yield row


def configure(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous  = NORMAL")
    conn.execute("PRAGMA temp_store   = MEMORY")
    conn.execute("PRAGMA cache_size   = -262144")  # 256MB


def download_parquet_files(force: bool = False) -> None:
    """HuggingFace Hub에서 parquet 파일을 ROOT로 다운로드."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("[ERROR] huggingface_hub 미설치. `pip install huggingface_hub` 후 재시도",
              file=sys.stderr)
        raise SystemExit(2)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] 다운로드: {HF_REPO_ID} ({HF_PARQUET_PATTERN}) -> {DATA_DIR}")
    snapshot_download(
        repo_id=HF_REPO_ID,
        repo_type=HF_REPO_TYPE,
        allow_patterns=[HF_PARQUET_PATTERN],
        local_dir=str(DATA_DIR),
        force_download=force,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download", action="store_true",
        help="parquet 파일이 없으면 HuggingFace에서 자동 다운로드",
    )
    parser.add_argument(
        "--force-download", action="store_true",
        help="이미 있어도 재다운로드 (--download 함의)",
    )
    args = parser.parse_args()

    parquet_files = sorted(glob.glob(PARQUET_GLOB))
    if args.force_download or (args.download and not parquet_files):
        download_parquet_files(force=args.force_download)
        parquet_files = sorted(glob.glob(PARQUET_GLOB))

    if not parquet_files:
        print(f"[ERROR] parquet 파일을 찾을 수 없음: {PARQUET_GLOB}", file=sys.stderr)
        print("[HINT]  --download 옵션으로 자동 다운로드 가능", file=sys.stderr)
        return 1

    DB_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] 출처: nvidia/Nemotron-Personas-Korea")
    print(f"[INFO] 입력: {DATA_DIR} ({len(parquet_files)}개 parquet)")
    print(f"[INFO] DB:   {DB_PATH}")

    if DB_PATH.exists():
        print(f"[INFO] 기존 DB 삭제: {DB_PATH}")
        DB_PATH.unlink()
    # WAL 부산물도 정리
    for ext in ("-wal", "-shm"):
        p = DB_PATH.with_name(DB_PATH.name + ext)
        if p.exists():
            p.unlink()

    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)
    try:
        configure(conn)
        conn.executescript(DDL)

        total = 0
        for path in parquet_files:
            tf = time.time()
            with conn:  # 파일 단위 트랜잭션
                conn.executemany(INSERT_SQL, iter_rows(path))
            n = conn.execute("SELECT COUNT(*) FROM persona").fetchone()[0] - total
            total += n
            print(f"[INFO] {os.path.basename(path)}: +{n:,}행 "
                  f"({time.time()-tf:.1f}s, 누적 {total:,})")

        print(f"[INFO] 메인 적재 완료: {total:,}행, {time.time()-t0:.1f}s")

        # FTS 빌드 (trigram 토크나이저)
        print("[INFO] FTS5 가상 테이블 생성 + 빌드 (trigram)")
        conn.executescript(FTS_DDL)
        tf = time.time()
        with conn:
            conn.execute(
                f"INSERT INTO persona_fts(rowid, {', '.join(FTS_COLUMNS)}) "
                f"SELECT id, {', '.join(FTS_COLUMNS)} FROM persona"
            )
        print(f"[INFO] FTS 적재 완료: {time.time()-tf:.1f}s")

        print("[INFO] FTS optimize")
        with conn:
            conn.execute("INSERT INTO persona_fts(persona_fts) VALUES('optimize')")

        print("[INFO] ANALYZE")
        conn.execute("ANALYZE")

        # 통계
        cnt = conn.execute("SELECT COUNT(*) FROM persona").fetchone()[0]
        print(f"[INFO] 최종 행 수: {cnt:,}")

    finally:
        conn.close()

    # WAL 체크포인트(파일 통합) 위해 짧게 다시 열고 닫기
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"[DONE] {DB_PATH} ({size_mb:,.1f} MB), 총 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
