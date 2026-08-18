"""
DB 생성 + 시딩.

    python -m scripts.init_db          # 없으면 만들고 채움
    python -m scripts.init_db --reset  # 기존 DB 삭제 후 새로 생성

직업 538개 전체를 넣으려면 scripts/collect_jobs.js 로 수집한 JSON을
--jobs 옵션으로 넘긴다.

    python -m scripts.init_db --reset --jobs data/jobs.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import DB_PATH, Base, SessionLocal, engine
from app.models import (
    Job,
    JobCategory,
    JobTag,
    Question,
    QuestionOption,
    Tag,
    TagCategory,
    TagRole,
    UserType,
)
from app.seed.questions import QUESTIONS
from app.seed.sample_jobs import SAMPLE_JOBS, WEIGHT_BONUS, WEIGHT_REQUIRED
from app.seed.tags import CAN_TAGS, EXP_TAGS, HARD_TAGS
from app.seed.taxonomy import TAXONOMY, TOTAL_EXPECTED_JOBS


def seed_taxonomy(db) -> dict[str, JobCategory]:
    """대분류·중분류를 넣고 source_key → 카테고리 맵을 돌려준다."""
    by_key: dict[str, JobCategory] = {}
    for order, (major_key, major_name, _cnt, mids) in enumerate(TAXONOMY):
        major = JobCategory(
            name=major_name, level=1, source_key=major_key, sort_order=order
        )
        db.add(major)
        by_key[major_key] = major
        for m_order, (mid_key, mid_name) in enumerate(mids):
            mid = JobCategory(
                name=mid_name, level=2, parent=major,
                source_key=mid_key, sort_order=m_order,
            )
            db.add(mid)
            by_key[mid_key] = mid
    db.flush()
    return by_key


def seed_tags(db) -> dict[str, Tag]:
    by_code: dict[str, Tag] = {}
    for code, label, desc, _mids in EXP_TAGS:
        by_code[code] = Tag(
            code=code, category=TagCategory.EXP, label=label, description=desc
        )
    for code, label, desc in CAN_TAGS:
        by_code[code] = Tag(
            code=code, category=TagCategory.CAN, label=label, description=desc
        )
    for code, label, desc in HARD_TAGS:
        by_code[code] = Tag(
            code=code, category=TagCategory.HARD, label=label, description=desc
        )
    db.add_all(by_code.values())
    db.flush()
    return by_code


def seed_questions(db, tags: dict[str, Tag]) -> None:
    for q_order, (code, step, text, applies, multi, options) in enumerate(QUESTIONS):
        q = Question(
            code=code,
            step=step,
            text=text,
            applies_to=UserType(applies) if applies else None,
            is_multi_select=multi,
            sort_order=q_order,
        )
        db.add(q)
        for o_order, (label, tag_code, is_skip) in enumerate(options):
            db.add(
                QuestionOption(
                    question=q,
                    label=label,
                    tag=tags.get(tag_code) if tag_code else None,
                    is_skip=is_skip,
                    sort_order=o_order,
                )
            )
    db.flush()


def seed_all_jobs(db, cats: dict[str, JobCategory], jobs_path: Path) -> int:
    """collect_jobs.js 결과(JSON)를 jobs 테이블에 넣는다.

    JSON 형식: [{"major":..,"mid":..,"group":..,"job":..}, ...]
    group(세분류)은 level 3 카테고리로 만들어 붙인다.
    """
    rows = json.loads(jobs_path.read_text(encoding="utf-8"))
    mid_by_name = {c.name: c for c in cats.values() if c.level == 2}
    level3: dict[tuple[int, str], JobCategory] = {}
    added = 0

    for row in rows:
        mid = mid_by_name.get(row["mid"])
        if mid is None:
            print(f"  [경고] 중분류를 찾을 수 없음: {row['mid']}")
            continue
        key = (mid.id, row["group"])
        cat = level3.get(key)
        if cat is None:
            cat = JobCategory(name=row["group"], level=3, parent=mid)
            db.add(cat)
            db.flush()
            level3[key] = cat
        db.add(Job(name=row["job"], category=cat, is_recommendable=False))
        added += 1

    db.flush()
    print(f"  직업 {added}건 적재 (기대값 {TOTAL_EXPECTED_JOBS})")
    if added != TOTAL_EXPECTED_JOBS:
        print("  [경고] 기대 직업 수와 다릅니다. 분류 개편 또는 크롤러 확인 필요")
    return added


def seed_sample_jobs(db, cats: dict[str, JobCategory], tags: dict[str, Tag]) -> None:
    """MVP 추천 풀. 이미 있는 직업이면 태그만 붙이고, 없으면 새로 만든다."""
    for spec in SAMPLE_JOBS:
        job = db.scalar(select(Job).where(Job.name == spec["name"]))
        if job is None:
            cat = cats.get(spec["mid_key"])
            if cat is None:
                print(f"  [경고] 중분류 키 없음: {spec['mid_key']}")
                continue
            job = Job(name=spec["name"], category=cat)
            db.add(job)
        job.easy_name = spec["easy_name"]
        job.one_line_desc = spec["one_line_desc"]
        job.requires_cert = spec["requires_cert"]
        job.cert_note = spec["cert_note"]
        job.is_recommendable = True
        db.flush()

        pairs = (
            [(c, TagRole.REQUIRED, WEIGHT_REQUIRED) for c in spec["required"]]
            + [(c, TagRole.BONUS, WEIGHT_BONUS) for c in spec["bonus"]]
            + [(c, TagRole.EXCLUDE_IF_DIFFICULT, 0) for c in spec["exclude"]]
        )
        for code, role, weight in pairs:
            tag = tags.get(code)
            if tag is None:
                print(f"  [경고] 태그 없음: {code} ({spec['name']})")
                continue
            db.add(JobTag(job=job, tag=tag, role=role, weight=weight))
    db.flush()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="기존 DB 삭제")
    ap.add_argument("--jobs", type=Path, help="collect_jobs.js 결과 JSON 경로")
    args = ap.parse_args()

    if args.reset and DB_PATH.exists():
        DB_PATH.unlink()
        print(f"기존 DB 삭제: {DB_PATH.name}")

    Base.metadata.create_all(engine)
    print(f"테이블 생성 완료 ({len(Base.metadata.tables)}개)")

    with SessionLocal() as db:
        if db.scalar(select(Tag).limit(1)) is not None:
            print("이미 시딩된 DB입니다. --reset 을 쓰세요.")
            return

        cats = seed_taxonomy(db)
        print(f"  분류 {len(cats)}개 (대분류 10 / 중분류 35)")

        tags = seed_tags(db)
        print(f"  태그 {len(tags)}개")

        seed_questions(db, tags)
        print(f"  질문 {len(QUESTIONS)}개")

        if args.jobs:
            seed_all_jobs(db, cats, args.jobs)
        else:
            print("  (--jobs 미지정: 전체 직업 적재 건너뜀)")

        seed_sample_jobs(db, cats, tags)
        print(f"  추천 풀 {len(SAMPLE_JOBS)}개 직업에 태그 부여")

        db.commit()
    print("완료.")


if __name__ == "__main__":
    main()
