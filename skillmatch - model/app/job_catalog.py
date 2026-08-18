"""split_jobs.db 접근 + 2번째 LLM에 넘길 직무 카탈로그 구성.

split_jobs.db 는 대분류(10)별로 테이블이 나뉘어 있고, 각 테이블에는
중분류(second_category) / 세분류(third_category) / 직업명(job) / 설명(description)
컬럼만 있다. 대분류 이름 자체는 컬럼으로 없어서 여기서 고정 매핑으로 관리한다.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SPLIT_DB_PATH = BASE_DIR / "split_jobs.db"

CATEGORY_NAMES: dict[str, str] = {
    "job_01": "건설·채굴직",
    "job_02": "경영·사무·금융·보험직",
    "job_03": "교육·법률·사회복지·경찰·소방직 및 군인",
    "job_04": "농림어업직",
    "job_05": "미용·여행·숙박·음식·경비·청소직",
    "job_06": "보건·의료직",
    "job_07": "설치·정비·생산직",
    "job_08": "연구직 및 공학 기술직",
    "job_09": "영업·판매·운전·운송직",
    "job_10": "예술·디자인·방송·스포츠직",
}


@dataclass(frozen=True)
class JobRow:
    table: str
    id: int
    second_category: str
    third_category: str
    job: str
    description: str


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(SPLIT_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def load_jobs(tables: list[str] | None = None) -> list[JobRow]:
    """tables를 지정하면 그 대분류(job_XX)들만 읽는다. 생략하면 10개 전부."""
    tables = list(tables) if tables else list(CATEGORY_NAMES)
    rows: list[JobRow] = []
    with _connect() as con:
        for table in tables:
            for r in con.execute(
                f"SELECT ID, second_category, third_category, job, description FROM {table}"
            ):
                rows.append(
                    JobRow(
                        table=table,
                        id=r["ID"],
                        second_category=r["second_category"],
                        third_category=r["third_category"],
                        job=r["job"],
                        description=r["description"],
                    )
                )
    return rows


def build_indexed_catalog(
    tables: list[str] | None = None,
) -> tuple[list[JobRow], str]:
    """2번째 LLM에 넘길 번호 매긴 직무 카탈로그.

    LLM이 직무명 한글을 그대로 베끼게 하면(JSON 강제 모드 + 로컬 소형 모델
    조합에서) 한글이 깨져 나올 때가 있어서, 모델에게는 번호만 고르게 하고
    실제 JobRow는 반환된 인덱스로 이 리스트에서 매핑한다. tables를 지정하면
    그 대분류만 담아 프롬프트 크기(=응답 속도)를 줄인다.
    """
    rows = load_jobs(tables)
    lines = [f"{i}. [{r.table}] {r.job}" for i, r in enumerate(rows, start=1)]
    return rows, "\n".join(lines)
