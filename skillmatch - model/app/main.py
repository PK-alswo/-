"""
SkillMatch Board API 스켈레톤.

PRD '5. API, 파트너'의 인터페이스를 그대로 구현한다.
  GET  /api/questions            질문 목록
  POST /api/recommendations      추천 결과 요청
  GET  /api/jobs/{id}            직무 상세
  POST /api/sessions/complete    익명 세션 완료 기록

실행: uvicorn app.main:app --reload
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession, selectinload

from .database import get_db
from .models import (
    Job,
    Question,
    Session,
    SessionAnswer,
    SessionRecommendation,
    UserType,
)
from .recommender import find_conflicts, recommend, resolve_tag_codes

app = FastAPI(title="SkillMatch Board API", version="0.1.0")


# ---------------------------------------------------------------------------
# 스키마
# ---------------------------------------------------------------------------
class OptionOut(BaseModel):
    id: int
    label: str
    tag_code: str | None = None
    is_skip: bool


class QuestionOut(BaseModel):
    id: int
    code: str
    step: str
    text: str
    applies_to: UserType | None
    is_multi_select: bool
    options: list[OptionOut]


class JobOut(BaseModel):
    id: int
    name: str
    display_name: str
    one_line_desc: str | None
    requires_cert: bool
    cert_note: str | None
    category_path: list[str]


class RecommendIn(BaseModel):
    session_id: str | None = None
    option_ids: list[int] = Field(min_length=1)


class RecommendedJob(BaseModel):
    rank: int
    job_id: int
    display_name: str
    one_line_desc: str | None
    requires_cert: bool
    cert_note: str | None
    score: int
    is_fallback: bool


class RecommendOut(BaseModel):
    # 상반된 답변이 있으면 결과 대신 재확인이 필요하다는 신호를 준다
    conflicts: list[tuple[str, str]]
    results: list[RecommendedJob]


class SessionCompleteIn(BaseModel):
    session_id: str
    user_type: UserType | None = None
    last_step: str | None = None
    selected_job_id: int | None = None
    revision_count: int = 0
    staff_help_requested: bool = False
    device_hash: str | None = None


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------
@app.get("/api/questions", response_model=list[QuestionOut])
def list_questions(db: DbSession = Depends(get_db)):
    stmt = (
        select(Question)
        .order_by(Question.sort_order)
        .options(selectinload(Question.options))
    )
    out = []
    for q in db.scalars(stmt):
        out.append(
            QuestionOut(
                id=q.id, code=q.code, step=q.step, text=q.text,
                applies_to=q.applies_to, is_multi_select=q.is_multi_select,
                options=[
                    OptionOut(
                        id=o.id, label=o.label,
                        tag_code=o.tag.code if o.tag else None,
                        is_skip=o.is_skip,
                    )
                    for o in q.options
                ],
            )
        )
    return out


@app.post("/api/recommendations", response_model=RecommendOut)
def create_recommendations(payload: RecommendIn, db: DbSession = Depends(get_db)):
    positive, hard = resolve_tag_codes(db, payload.option_ids)
    conflicts = find_conflicts(positive | hard)
    candidates = recommend(db, positive, hard)

    results = [
        RecommendedJob(
            rank=i,
            job_id=c.job.id,
            display_name=c.job.display_name,
            one_line_desc=c.job.one_line_desc,
            requires_cert=c.job.requires_cert,
            cert_note=c.job.cert_note,
            score=c.score,
            is_fallback=c.is_blocked or c.score == 0,
        )
        for i, c in enumerate(candidates, start=1)
    ]

    # 노출된 추천 결과를 세션에 기록 (추천 품질 사후 분석용)
    if payload.session_id:
        sess = db.get(Session, payload.session_id)
        if sess is None:
            sess = Session(id=payload.session_id)
            db.add(sess)
        for r in results:
            db.add(
                SessionRecommendation(
                    session_id=payload.session_id, job_id=r.job_id,
                    rank=r.rank, score=r.score, is_fallback=r.is_fallback,
                )
            )
        for oid in payload.option_ids:
            opt_q = db.scalar(
                select(Question.id)
                .join(Question.options)
                .where(Question.options.any(id=oid))
            )
            if opt_q:
                db.add(
                    SessionAnswer(
                        session_id=payload.session_id,
                        question_id=opt_q, option_id=oid,
                    )
                )
        db.commit()

    return RecommendOut(conflicts=conflicts, results=results)


@app.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: DbSession = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "직무를 찾을 수 없습니다")

    path, node = [], job.category
    while node is not None:
        path.append(node.name)
        node = node.parent
    path.reverse()

    return JobOut(
        id=job.id, name=job.name, display_name=job.display_name,
        one_line_desc=job.one_line_desc, requires_cert=job.requires_cert,
        cert_note=job.cert_note, category_path=path,
    )


@app.post("/api/sessions/start")
def start_session(db: DbSession = Depends(get_db)):
    sess = Session(id=str(uuid.uuid4()))
    db.add(sess)
    db.commit()
    return {"session_id": sess.id, "started_at": sess.started_at}


@app.post("/api/sessions/complete")
def complete_session(payload: SessionCompleteIn, db: DbSession = Depends(get_db)):
    sess = db.get(Session, payload.session_id)
    if sess is None:
        raise HTTPException(404, "세션을 찾을 수 없습니다")

    sess.completed_at = datetime.now(timezone.utc)
    sess.user_type = payload.user_type
    sess.last_step = payload.last_step
    sess.selected_job_id = payload.selected_job_id
    sess.revision_count = payload.revision_count
    sess.staff_help_requested = payload.staff_help_requested
    sess.device_hash = payload.device_hash
    db.commit()

    elapsed = (sess.completed_at - sess.started_at).total_seconds()
    return {"session_id": sess.id, "elapsed_seconds": elapsed}
