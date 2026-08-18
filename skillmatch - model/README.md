# SkillMatch Board — 직무DB (FastAPI + SQLite)

상담 전 키오스크에서 구직자의 희망직종을 구체화하기 위한 직무DB와 API 스켈레톤입니다.

## 실행

```bash
pip install -r requirements.txt
python -m scripts.init_db --reset        # DB 생성 + 시딩
uvicorn app.main:app --reload            # http://127.0.0.1:8000/docs
```

직업 538개 전체를 넣으려면:

```bash
# 1. work.go.kr 직업정보 페이지에서 scripts/collect_jobs.js 실행 → jobs.json 다운로드
# 2. 내려받은 파일을 data/jobs.json 으로 옮긴 뒤
python -m scripts.init_db --reset --jobs data/jobs.json
```

## 테이블 구조 (9개)

```
[분류 체계]
job_categories ─┐ 자기참조 3단계
                │  level 1 = 대분류(10)   예) 경영·사무·금융·보험직
                │  level 2 = 중분류(35)   예) 경영·행정·사무직
                │  level 3 = 세분류       예) 기타 사무원
                └─< jobs (538)            예) 취업알선원

[태그 / 매칭 규칙]
tags ─────────┐  EXP(해본 일·희망 분야) / CAN(가능 업무) / HARD(어려운 조건)
              └─< job_tags >── jobs
                   role = required(w2) / bonus(w1) / exclude_if_difficult

[질문 흐름]
questions ──< question_options ──> tags
   step B/D/E/F        tag_id 없으면 '잘 모르겠어요' 스킵 선택지

[익명 세션 로그]
sessions ──< session_answers        ──> questions, question_options
         └─< session_recommendations ──> jobs
```

### 설계 포인트

**분류 체계를 자기참조 한 테이블로** — work.go.kr이 대/중/세 3단계인데 깊이가
바뀔 수 있어서, 테이블 3개로 쪼개는 대신 `parent_id` + `level`로 처리했습니다.
`source_key`에 원본 DOM id(`korSubJobA02` 등)를 남겨서 분류가 개편돼도 대조가 됩니다.

**직업 538개 전부를 추천 대상으로 쓰지 않습니다** — `jobs.is_recommendable`로
구분합니다. 538개는 분류 참조용으로 다 넣되, 태그를 붙인 24개만 `True`로 켜서
PoC 추천 풀로 씁니다(PRD의 "테스트용 직무 후보 24~30개" 요건).
검증 후 대상을 늘리면 됩니다.

**제외 조건은 삭제가 아니라 완화 가능한 조건** — `exclude_if_difficult` 태그가
걸려도 후보가 3개 미만이면 되살리고 `is_fallback=True`로 표시합니다.
"오래 서 있기 힘듦" 하나로 후보가 0개가 되는 상황을 막습니다.

**답변 수정 이력을 지우지 않습니다** — `session_answers.is_active`로 무효 처리만
하고 로그는 남깁니다. PRD 성공지표의 '답변 수정률'을 계산하려면 필요합니다.

**개인정보는 스키마 자체에 없습니다** — 실명·연락처·주민번호 컬럼을 아예 두지
않았습니다(PRD Out of Scope). 단말 구분은 `device_hash` 익명 해시만 씁니다.

## 성공지표 산출

| 지표 | 산출 방법 |
|---|---|
| 흐름 완료율 (KR1) | `sessions.completed_at IS NOT NULL` 비율 |
| 직무 구체화율 (KR2) | `sessions.selected_job_id IS NOT NULL` 비율 |
| 평균 완료 시간 (KR4) | `AVG(completed_at - started_at)` |
| 단계별 이탈률 | `sessions.last_step` 분포 |
| 답변 수정률 | `sessions.revision_count` |

KR3(주요 업무 이해도)은 이용 후 별도 설문이 필요해 DB에 없습니다.

## 추천 로직 (`app/recommender.py`)

```
score(job) = Σ weight(tag)   tag ∈ (required ∪ bonus) ∩ 사용자 긍정 태그
제외        job의 exclude_if_difficult 태그가 사용자 HARD 태그와 겹치면 제외
정렬        score 내림차순 → 상위 3개

후보가 3개 미만이면
  1) 제외 조건이 적게 걸린 직무부터 되살림 (is_fallback)
  2) 그래도 부족하면 태그 자카드 유사도 최상위로 채움
```

`find_conflicts()`가 상반된 답변(예: "몸 쓰는 일 괜찮아요" + "무거운 물건 힘들어요")을
감지하면 결과를 내기 전에 재확인 질문을 띄우도록 `conflicts`를 함께 반환합니다.

## 확인 필요 항목

1. **`SAMPLE_JOBS`의 직업명 대조** — 24개 중 `verified=True`인 10개(경영·행정·사무직
   소속)만 원본 화면에서 확인한 이름입니다. 나머지 14개는 분류만 확정된 상태라,
   전체 수집 후 실제 직업명과 대조해 고쳐야 합니다. 이름이 안 맞으면 시딩 시
   경고가 뜨고 별도 레코드로 생성됩니다.
2. **`is_recommendable` 대상 선정** — 현재 24개는 제안값입니다. 중장년 구직자에게
   현실적인 직업인지 상담원 검토가 필요합니다.
3. **자격 필요 여부(`requires_cert`)** — 요양보호사·경비원 등은 명확하지만,
   조리사처럼 사업장에 따라 갈리는 직업은 표기 기준을 정해야 합니다.
4. **제외 완화 정책** — 지금은 "부족하면 되살림"입니다. 자격·안전 관련 조건은
   절대 완화하지 않는 식으로 예외를 둘지 결정이 필요합니다.
5. **KECO 공식 코드** — `source_key`는 화면 DOM id일 뿐 공식 분류코드가 아닙니다.
   고용센터 전산과 연계하려면 한국고용직업분류 2025 해설서의 코드 컬럼을 추가해야
   합니다.

## 데이터 출처

work.go.kr > 취업지원 > 취업가이드 > 직업정보 > 분류별 찾기
(2026-07-29 수집: 대분류 10 / 중분류 35 / 직업 538)
