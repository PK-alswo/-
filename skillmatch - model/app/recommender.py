"""
직무 후보 추천 로직.

  score(job) = Σ weight(tag)   tag ∈ (required ∪ bonus) ∩ 사용자 긍정 태그
  제외        job의 exclude_if_difficult 태그가 사용자 HARD 태그와 겹치면 후보 제외

후보가 3개보다 적으면 PRD Edge Case 순서대로 완화한다.
  1) 제외 조건이 1개만 걸린 직무부터 되살림 (is_fallback=True)
  2) 그래도 부족하면 태그 자카드 유사도가 가장 높은 직무로 채움
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession, selectinload

from .models import Job, JobTag, Tag, TagRole
from .seed.tags import CONFLICT_PAIRS

TOP_N = 3


@dataclass
class Candidate:
    job: Job
    score: int = 0
    matched: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocked_by)


def find_conflicts(selected_codes: set[str]) -> list[tuple[str, str]]:
    """상반되는 태그가 함께 선택됐는지 검사. PRD Edge Case 대응."""
    return [
        (a, b) for a, b in CONFLICT_PAIRS
        if a in selected_codes and b in selected_codes
    ]


def _score_all(db: DbSession, positive: set[str], hard: set[str]) -> list[Candidate]:
    stmt = (
        select(Job)
        .where(Job.is_recommendable.is_(True))
        .options(selectinload(Job.job_tags).selectinload(JobTag.tag))
    )
    out = []
    for job in db.scalars(stmt):
        c = Candidate(job=job)
        for jt in job.job_tags:
            code = jt.tag.code
            if jt.role is TagRole.EXCLUDE_IF_DIFFICULT:
                if code in hard:
                    c.blocked_by.append(code)
            elif code in positive:
                c.score += jt.weight
                c.matched.append(code)
        out.append(c)
    return out


def _tag_codes(job: Job, roles: tuple[TagRole, ...]) -> set[str]:
    return {jt.tag.code for jt in job.job_tags if jt.role in roles}


def recommend(
    db: DbSession,
    positive_tags: set[str],
    hard_tags: set[str],
    top_n: int = TOP_N,
) -> list[Candidate]:
    """추천 후보를 순위대로 반환. 부족하면 단계적으로 완화한다."""
    scored = _score_all(db, positive_tags, hard_tags)

    # 1차: 제외되지 않고 점수가 붙은 직무
    primary = [c for c in scored if not c.is_blocked and c.score > 0]
    primary.sort(key=lambda c: (-c.score, c.job.id))
    if len(primary) >= top_n:
        return primary[:top_n]

    picked = list(primary)
    picked_ids = {c.job.id for c in picked}

    # 2차 완화: 제외 조건이 적게 걸린 직무부터 되살림
    relaxed = [
        c for c in scored
        if c.job.id not in picked_ids and c.score > 0 and c.is_blocked
    ]
    relaxed.sort(key=lambda c: (len(c.blocked_by), -c.score, c.job.id))
    for c in relaxed:
        if len(picked) >= top_n:
            break
        picked.append(c)
        picked_ids.add(c.job.id)

    # 3차 완화: 점수 0이지만 태그 유사도가 높은 직무 (PRD의 '가장 근사한 후보')
    if len(picked) < top_n and positive_tags:
        rest = [c for c in scored if c.job.id not in picked_ids]
        roles = (TagRole.REQUIRED, TagRole.BONUS)
        rest.sort(
            key=lambda c: (
                -_jaccard(positive_tags, _tag_codes(c.job, roles)),
                c.job.id,
            )
        )
        for c in rest:
            if len(picked) >= top_n:
                break
            picked.append(c)

    return picked[:top_n]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def resolve_tag_codes(db: DbSession, option_ids: list[int]) -> tuple[set[str], set[str]]:
    """선택한 option_id 목록을 (긍정 태그, HARD 태그)로 변환."""
    from .models import QuestionOption  # 순환 임포트 방지

    stmt = (
        select(QuestionOption)
        .where(QuestionOption.id.in_(option_ids))
        .options(selectinload(QuestionOption.tag))
    )
    positive: set[str] = set()
    hard: set[str] = set()
    for opt in db.scalars(stmt):
        if opt.tag is None:  # '잘 모르겠어요' → 태그 없음
            continue
        tag: Tag = opt.tag
        if tag.category.value == "HARD":
            hard.add(tag.code)
        else:
            positive.add(tag.code)
    return positive, hard
