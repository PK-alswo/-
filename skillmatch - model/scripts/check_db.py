"""
DB가 제대로 만들어졌는지 한 번에 확인하는 스크립트.

    python -m scripts.check_db

출력 3부분
  1. 테이블별 레코드 수
  2. 분류 체계 트리 (대분류 → 중분류)
  3. 페르소나 시나리오별 추천 결과
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, inspect, select

from app.database import DB_PATH, SessionLocal, engine
from app.models import (
    Job,
    JobCategory,
    JobTag,
    Question,
    QuestionOption,
    Session,
    SessionAnswer,
    SessionRecommendation,
    Tag,
    TagCategory,
)
from app.recommender import find_conflicts, recommend

TABLES = [
    ("job_categories", JobCategory),
    ("jobs", Job),
    ("tags", Tag),
    ("job_tags", JobTag),
    ("questions", Question),
    ("question_options", QuestionOption),
    ("sessions", Session),
    ("session_answers", SessionAnswer),
    ("session_recommendations", SessionRecommendation),
]

SCENARIOS = [
    (
        "무목표형 — 해본 일 없음 / 사람 만나는 건 괜찮 / 컴퓨터 가능",
        {"EXP_없음", "CAN_사람응대", "CAN_컴퓨터사용"},
        set(),
    ),
    (
        "과대범위형 — '사무직이요' / 컴퓨터 가능 / 오래 서있기 힘듦",
        {"EXP_사무", "CAN_컴퓨터사용"},
        {"HARD_장시간서있기"},
    ),
    (
        "생산직 희망 — 반복작업·체력 OK / 무거운 물건 못 듦 (충돌 케이스)",
        {"EXP_생산제조", "CAN_반복작업", "CAN_체력업무"},
        {"HARD_무거운물건"},
    ),
    (
        "돌봄 희망 — 야간 불가 (제외 완화 케이스)",
        {"EXP_돌봄복지", "CAN_돌봄케어"},
        {"HARD_야간근무"},
    ),
    (
        "아무것도 안 고름 (빈 응답 방어 확인)",
        set(),
        set(),
    ),
]


def check_tables(db) -> None:
    print("=" * 60)
    print("1. 테이블별 레코드 수")
    print("=" * 60)

    actual = set(inspect(engine).get_table_names())
    expected = {name for name, _ in TABLES}
    missing = expected - actual
    if missing:
        print(f"  [오류] 없는 테이블: {', '.join(sorted(missing))}")
        print("  → python -m scripts.init_db --reset 를 먼저 실행하세요.\n")
        return

    for name, model in TABLES:
        n = db.scalar(select(func.count()).select_from(model))
        print(f"  {name:28s} {n:>6,}")

    recommendable = db.scalar(
        select(func.count()).select_from(Job).where(Job.is_recommendable.is_(True))
    )
    total_jobs = db.scalar(select(func.count()).select_from(Job))
    print(f"\n  추천 대상 직업: {recommendable} / 전체 {total_jobs}")
    if total_jobs <= 30:
        print("  (전체 직업 538개를 넣으려면 --jobs data/jobs.json 옵션 사용)")

    for cat in TagCategory:
        n = db.scalar(
            select(func.count()).select_from(Tag).where(Tag.category == cat)
        )
        print(f"  태그 {cat.value:5s} {n}개")
    print()


def check_taxonomy(db) -> None:
    print("=" * 60)
    print("2. 분류 체계")
    print("=" * 60)

    majors = db.scalars(
        select(JobCategory)
        .where(JobCategory.level == 1)
        .order_by(JobCategory.sort_order)
    ).all()

    for m in majors:
        mids = sorted(m.children, key=lambda c: c.sort_order)
        print(f"  {m.name}  (중분류 {len(mids)})")
        for d in mids:
            # level 3(세분류)까지 있으면 그 아래 직업 수도 센다
            job_count = len(d.jobs) + sum(len(g.jobs) for g in d.children)
            suffix = f"  · 직업 {job_count}" if job_count else ""
            print(f"     └ {d.name}{suffix}")
    print(f"\n  대분류 {len(majors)}개 / 중분류 "
          f"{sum(len(m.children) for m in majors)}개\n")


def check_recommendations(db) -> None:
    print("=" * 60)
    print("3. 추천 로직 시나리오")
    print("=" * 60)

    for title, positive, hard in SCENARIOS:
        print(f"\n  ■ {title}")

        conflicts = find_conflicts(positive | hard)
        if conflicts:
            for a, b in conflicts:
                print(f"     ⚠ 답변 충돌: {a} ↔ {b} → 재확인 질문 필요")

        results = recommend(db, positive, hard)
        if not results:
            print("     (추천 결과 없음)")
            continue

        for i, c in enumerate(results, 1):
            flags = []
            if c.is_blocked:
                flags.append(f"완화: {','.join(c.blocked_by)}")
            if c.score == 0:
                flags.append("유사도 추천")
            if c.job.requires_cert:
                flags.append("자격필요")
            flag_txt = f"  [{' / '.join(flags)}]" if flags else ""
            print(f"     {i}. {c.job.display_name} (점수 {c.score}){flag_txt}")
            print(f"        {c.job.one_line_desc}")
    print()


def main() -> None:
    if not DB_PATH.exists():
        print(f"DB 파일이 없습니다: {DB_PATH}")
        print("→ python -m scripts.init_db --reset 를 먼저 실행하세요.")
        raise SystemExit(1)

    size_kb = DB_PATH.stat().st_size / 1024
    print(f"\nDB 파일: {DB_PATH}  ({size_kb:,.0f} KB)\n")

    with SessionLocal() as db:
        check_tables(db)
        check_taxonomy(db)
        check_recommendations(db)

    print("점검 완료.")


if __name__ == "__main__":
    main()
