"""
SkillMatch Board - DB 모델

크게 4개 묶음으로 구성된다.

  [1] 직업 분류 체계   JobCategory (3단계 자기참조) + Job
  [2] 태그 / 매칭 규칙  Tag + JobTag
  [3] 질문 흐름         Question + QuestionOption
  [4] 익명 세션 로그    Session + SessionAnswer + SessionRecommendation

분류 체계는 work.go.kr 직업정보(취업지원 > 취업가이드 > 직업정보)의
"분류별 찾기" 구조를 그대로 따른다.

  대분류(10)  →  중분류(35)  →  세분류  →  직업(538)
  예) 경영·사무·금융·보험직 → 경영·행정·사무직 → 기타 사무원 → 취업알선원
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------
class TagCategory(str, enum.Enum):
    """태그 성격. 질문 단계(D/E/F)와 1:1로 대응된다."""

    EXP = "EXP"    # 해본 일 / 희망 분야   (경로 D단계)
    CAN = "CAN"    # 실제 가능한 업무      (경로 E단계)
    HARD = "HARD"  # 하기 어려운 업무·조건 (경로 F단계)


class TagRole(str, enum.Enum):
    """직업 ↔ 태그 연결의 의미."""

    REQUIRED = "required"                          # 핵심 매칭 (가중치 큼)
    BONUS = "bonus"                                # 가점
    EXCLUDE_IF_DIFFICULT = "exclude_if_difficult"  # 사용자가 '어렵다'고 하면 제외


class UserType(str, enum.Enum):
    """PRD 페르소나. 내부 기획 용어이므로 사용자 화면에는 노출하지 않는다."""

    NO_GOAL = "no_goal"          # 무목표형
    TOO_BROAD = "too_broad"      # 과대 범위형
    OTHER = "other"              # MVP 범위 밖 (로그만 남김)


# ---------------------------------------------------------------------------
# [1] 직업 분류 체계
# ---------------------------------------------------------------------------
class JobCategory(Base):
    """대분류 / 중분류 / 세분류를 한 테이블에서 자기참조로 표현."""

    __tablename__ = "job_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=대, 2=중, 3=세
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_categories.id", ondelete="CASCADE")
    )
    # work.go.kr 화면의 DOM id (korSysJobA0, korSubJobA02 ...). 재수집 시 대조용.
    source_key: Mapped[str | None] = mapped_column(String(40))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    parent: Mapped[JobCategory | None] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[list[JobCategory]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[Job]] = relationship(back_populates="category")

    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_category_parent_name"),
        Index("ix_category_level", "level"),
    )

    def __repr__(self) -> str:
        return f"<JobCategory L{self.level} {self.name}>"


class Job(Base):
    """직업 마스터. work.go.kr 직업정보의 최종 직업명 단위."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 원본 직업명 (예: '전산자료입력원 및 사무보조원')
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    # 구직자 화면에 보여줄 쉬운 이름 (예: '사무보조원'). 미작성 시 name 사용.
    easy_name: Mapped[str | None] = mapped_column(String(120))
    # 결과 화면에 직무명과 함께 노출하는 한 줄 설명 (PRD: 직무명 + 한 줄 설명 3개)
    one_line_desc: Mapped[str | None] = mapped_column(String(300))

    category_id: Mapped[int] = mapped_column(
        ForeignKey("job_categories.id", ondelete="RESTRICT"), nullable=False
    )

    # 자격이 필요한 직무는 결과 화면에서 배지로 구분 표시 (PRD Edge Case)
    requires_cert: Mapped[bool] = mapped_column(Boolean, default=False)
    cert_note: Mapped[str | None] = mapped_column(String(300))

    # MVP 추천 풀에 포함할지 여부.
    # 538개 전체를 넣되, PoC 단계에서는 중장년 구직자에게 현실적인 직업만
    # True로 켜서 '테스트용 직무 후보 24~30개' 요건을 맞춘다.
    is_recommendable: Mapped[bool] = mapped_column(Boolean, default=False)

    category: Mapped[JobCategory] = relationship(back_populates="jobs")
    job_tags: Mapped[list[JobTag]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_jobs_recommendable", "is_recommendable"),)

    @property
    def display_name(self) -> str:
        return self.easy_name or self.name

    def __repr__(self) -> str:
        return f"<Job {self.display_name}>"


# ---------------------------------------------------------------------------
# [2] 태그 / 매칭 규칙
# ---------------------------------------------------------------------------
class Tag(Base):
    """버튼 응답이 변환되는 태그."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    category: Mapped[TagCategory] = mapped_column(
        Enum(TagCategory, native_enum=False), nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)  # 사용자용 표현
    description: Mapped[str | None] = mapped_column(Text)

    job_tags: Mapped[list[JobTag]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_tags_category", "category"),)

    def __repr__(self) -> str:
        return f"<Tag {self.code}>"


class JobTag(Base):
    """직업 ↔ 태그 매핑. 추천 점수 계산의 핵심 테이블."""

    __tablename__ = "job_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[TagRole] = mapped_column(
        Enum(TagRole, native_enum=False), nullable=False
    )
    # required=2, bonus=1, exclude_if_difficult=0(제외 판정에만 사용)
    weight: Mapped[int] = mapped_column(Integer, default=1)

    job: Mapped[Job] = relationship(back_populates="job_tags")
    tag: Mapped[Tag] = relationship(back_populates="job_tags")

    __table_args__ = (
        UniqueConstraint("job_id", "tag_id", "role", name="uq_job_tag_role"),
        Index("ix_job_tags_tag_role", "tag_id", "role"),
    )


# ---------------------------------------------------------------------------
# [3] 질문 흐름
# ---------------------------------------------------------------------------
class Question(Base):
    """질문 화면 한 개 = 레코드 한 개 (PRD: 한 화면에 하나의 질문)."""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    step: Mapped[str] = mapped_column(String(2), nullable=False)  # 경로 A~I
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    # 이 질문을 보여줄 유형. None이면 공통 질문.
    applies_to: Mapped[UserType | None] = mapped_column(
        Enum(UserType, native_enum=False)
    )
    is_multi_select: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    options: Mapped[list[QuestionOption]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="QuestionOption.sort_order",
    )

    def __repr__(self) -> str:
        return f"<Question {self.code}>"


class QuestionOption(Base):
    """버튼 선택지. tag_id가 없으면 '잘 모르겠어요' 같은 스킵 선택지."""

    __tablename__ = "question_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    tag_id: Mapped[int | None] = mapped_column(ForeignKey("tags.id", ondelete="SET NULL"))
    # '잘 모르겠어요' / '특별히 어려운 건 없어요' 등 (PRD 니즈: 모든 질문에 선택 가능)
    is_skip: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    question: Mapped[Question] = relationship(back_populates="options")
    tag: Mapped[Tag | None] = relationship()


# ---------------------------------------------------------------------------
# [4] 익명 세션 로그  (실명·연락처·주민번호는 저장하지 않음 = PRD Out of Scope)
# ---------------------------------------------------------------------------
class Session(Base):
    """키오스크 1회 이용 = 세션 1건. 성공 지표 산출의 기준 테이블."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID4
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    user_type: Mapped[UserType | None] = mapped_column(
        Enum(UserType, native_enum=False)
    )
    last_step: Mapped[str | None] = mapped_column(String(2))  # 단계별 이탈률용
    revision_count: Mapped[int] = mapped_column(Integer, default=0)  # 답변 수정률용
    staff_help_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    selected_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    # 키오스크 단말 구분용 익명 해시. 개인 식별 정보가 아니다.
    device_hash: Mapped[str | None] = mapped_column(String(64))

    selected_job: Mapped[Job | None] = relationship()
    answers: Mapped[list[SessionAnswer]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list[SessionRecommendation]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionRecommendation.rank",
    )

    __table_args__ = (Index("ix_sessions_completed", "completed_at"),)


class SessionAnswer(Base):
    """개별 버튼 응답. 수정 이력까지 남겨 '답변 수정률'을 계산한다."""

    __tablename__ = "session_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    option_id: Mapped[int] = mapped_column(
        ForeignKey("question_options.id", ondelete="RESTRICT"), nullable=False
    )
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # 이전 화면으로 돌아가 바꾼 응답인지
    is_revision: Mapped[bool] = mapped_column(Boolean, default=False)
    # 되돌리기 후 무효가 된 응답 (계산에서 제외, 로그는 유지)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    session: Mapped[Session] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()
    option: Mapped[QuestionOption] = relationship()

    __table_args__ = (Index("ix_answers_session", "session_id", "is_active"),)


class SessionRecommendation(Base):
    """세션별로 실제 노출된 추천 결과. 추천 품질 사후 분석용."""

    __tablename__ = "session_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1~3
    score: Mapped[int] = mapped_column(Integer, default=0)
    # 후보가 부족해 제외 조건을 완화하거나 유사 추천으로 채운 경우 표시
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)

    session: Mapped[Session] = relationship(back_populates="recommendations")
    job: Mapped[Job] = relationship()

    __table_args__ = (
        UniqueConstraint("session_id", "rank", name="uq_session_rank"),
    )
