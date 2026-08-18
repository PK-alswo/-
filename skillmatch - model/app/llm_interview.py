"""LLM 기반 인터뷰 진행 + 직무 추천 로직.

흐름
  1) 기본 정보(나이 / 성별 / 희망 분야) 수집 — 호출부 책임
     희망 분야는 job_01~job_10 중 최대 3개, 또는 '잘 모르겠음'(빈 목록)
  2) 1번 LLM이 지금까지의 문답을 바탕으로 질문 1개 + 선택지 6개를 생성
     ('잘 모르겠음'은 시스템이 항상 마지막 선택지로 추가함). 희망 분야를
     선택했다면 그 분야(들)에 맞는 질문을, '잘 모르겠음'이면 전 분야에
     걸친 균형 잡힌 질문을 생성한다.
  3) 사용자가 답하면 이력에 쌓고 2)를 반복 — 총 5라운드
  4) 2번 LLM이 기본 정보 + 5라운드 문답 + 직무 카탈로그를 보고 직무 3개를
     추천 (DB에 실제로 있는지 검증까지 수행). 희망 분야를 선택했다면
     그 분야들의 직무만, '잘 모르겠음'이면 538개 전체를 카탈로그로 준다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .job_catalog import CATEGORY_NAMES, build_indexed_catalog
from .ollama_client import chat_json

TOTAL_ROUNDS = 5
NUM_OPTIONS = 6
DONT_KNOW = "잘 모르겠음"

# 희망 분야를 선택한 경우 그 분야(들)에 맞는 실무 적성 질문을 하되, 2~3개를
# 선택했다면 하나로만 몰리지 않게 한다. '잘 모르겠음'인 경우에만 예전처럼
# 전 분야에 걸친 균형 잡힌 질문으로 되돌아간다.
QUESTION_SYSTEM_PROMPT = """
당신은 직무 적합성을 파악하는 한국어 커리어 인터뷰어입니다.
사용자의 정보와 이전 답변을 참고하여, 아직 확인하지 않은 직무 성향을 묻는 질문을 하나 만드세요.
규칙:
1. 질문은 띄어쓰기 포함 45자 이내의 짧고 자연스러운 한 문장으로 작성하세요.
2. 질문은 한 가지 성향만 물어야 하며, 둘 이상의 질문을 연결하지 마세요.
3. 이전 질문과 의미가 겹치지 않아야 합니다.
4. 희망 분야명과 직업 분야 코드는 질문과 선택지에 쓰지 마세요.
5. 선택지는 정확히 6개만 작성하세요.
6. 각 선택지는 띄어쓰기 포함 25자 이내로 작성하세요.
7. 선택지는 서로 다른 구체적인 행동이나 업무 방식을 나타내야 합니다.
8. 정도를 나타내는 척도형 선택지는 작성하지 마세요.
9. '잘 모르겠음', '기타', '모두 해당', '해당 없음'은 작성하지 마세요.
10. question과 options라는 JSON 키를 제외하고 한글, 숫자, 공백, 한국어 문장부호만 사용하세요.
11. 영어 알파벳, 한자, 일본어, 중국어, 외국어 단어와 외국어 약어를 사용하지 마세요.
12. 설명, 번호, 인사말, 마크다운 없이 유효한 JSON 객체 하나만 출력하세요.
출력 형식:
{"question":"45자 이내의 질문","options":["25자 이내 선택지","25자 이내 선택지","25자 이내 선택지","25자 이내 선택지","25자 이내 선택지","25자 이내 선택지"]}
"""

RECOMMEND_SYSTEM_PROMPT = """
당신은 한국어 진로 추천 전문가입니다.

사용자 정보와 인터뷰 결과를 바탕으로 제공된 직무 목록에서 가장 적합한 직무 3개를 추천하세요.

규칙:
1. 직무 목록에 실제로 존재하는 서로 다른 번호 3개만 선택하세요.
2. 목록에 없는 번호를 만들지 마세요.
3. 희망 분야가 여러 개라면 한 분야에 치우치지 말고 전체 후보를 비교하세요.
4. 각 이유는 인터뷰에서 확인된 성향, 강점 또는 제약을 근거로 한글 한 문장으로 작성하세요.
5. 각 이유는 띄어쓰기 포함 60자 이내로 작성하세요.
6. 영어, 한자, 외국어 약어와 직무 분야 코드를 이유에 쓰지 마세요.
7. 설명이나 마크다운 없이 유효한 JSON 객체 하나만 출력하세요.
8. recommendations 배열에는 정확히 3개의 객체만 넣으세요.
9. index는 직무 목록의 번호와 일치하는 정수여야 합니다.

출력 형식:
{"recommendations":[{"index":1,"reason":"추천 이유"},{"index":2,"reason":"추천 이유"},{"index":3,"reason":"추천 이유"}]}
"""


@dataclass
class BasicInfo:
    age: int
    gender: str
    # "job_01"~"job_10" 중 최대 3개. 빈 목록이면 '잘 모르겠음' (특정 분야 없음).
    desired_field_codes: list[str]

    @property
    def is_unknown_field(self) -> bool:
        return not self.desired_field_codes

    @property
    def desired_field_names(self) -> list[str]:
        return [CATEGORY_NAMES[c] for c in self.desired_field_codes]


@dataclass
class QAPair:
    question: str
    options: list[str]
    answer: str


def _format_history(history: list[QAPair]) -> str:
    if not history:
        return "(아직 없음)"
    lines = []
    for i, qa in enumerate(history, start=1):
        lines.append(f"{i}. Q: {qa.question}\n   A: {qa.answer}")
    return "\n".join(lines)


def _basic_info_block(basic_info: BasicInfo) -> str:
    if basic_info.is_unknown_field:
        field_text = "잘 모르겠음 (특정 희망 분야 없음)"
    else:
        field_text = ", ".join(
            f"{CATEGORY_NAMES[c]} ({c})" for c in basic_info.desired_field_codes
        )
    return (
        f"나이: {basic_info.age}\n"
        f"성별: {basic_info.gender}\n"
        f"희망 분야: {field_text}"
    )


def generate_next_question(
    basic_info: BasicInfo, history: list[QAPair], round_no: int, retries: int = 3
) -> dict:
    """1번 LLM 호출: 다음 질문 + 선택지 6개를 생성한다.

    모델이 선택지를 6개보다 적게/많이 주는 등 형식을 안 지킬 때가 있어,
    무엇이 틀렸는지 구체적으로 알려주고 재시도한다.
    """
    user_prompt = f"""[기본 정보]
{_basic_info_block(basic_info)}

[지금까지의 질문과 답변]
{_format_history(history)}

지금은 총 {TOTAL_ROUNDS}개 질문 중 {round_no}번째입니다.
위 규칙에 따라 다음 질문과 선택지 6개를 JSON으로 생성하세요."""

    messages = [
        {"role": "system", "content": QUESTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    last_result: dict = {}
    for _ in range(retries):
        last_result = chat_json(messages)
        question = last_result.get("question")
        options = last_result.get("options")
        if question and isinstance(options, list) and len(options) == NUM_OPTIONS:
            return {"question": question, "options": list(options)}

        num_options = len(options) if isinstance(options, list) else 0
        messages = messages + [
            {"role": "assistant", "content": json.dumps(last_result, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    f"형식이 올바르지 않습니다 (선택지 {num_options}개 수신, {NUM_OPTIONS}개 필요). "
                    f"question은 빈 값이 아니어야 하고, options는 정확히 {NUM_OPTIONS}개의 "
                    "문자열 배열이어야 합니다. 다른 설명 없이 이 형식의 JSON만 다시 출력하세요."
                ),
            },
        ]

    raise ValueError(f"LLM이 {retries}번 시도 후에도 형식에 맞는 질문을 반환하지 않았습니다: {last_result}")


def run_interactive_interview(basic_info: BasicInfo) -> list[QAPair]:
    """터미널 input()으로 5라운드 문답을 직접 진행한다."""
    history: list[QAPair] = []
    for round_no in range(1, TOTAL_ROUNDS + 1):
        q = generate_next_question(basic_info, history, round_no)
        options = q["options"] + [DONT_KNOW]

        print(f"\n[질문 {round_no}/{TOTAL_ROUNDS}] {q['question']}")
        for i, opt in enumerate(options, start=1):
            print(f"  {i}. {opt}")

        while True:
            choice = input("번호 선택: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                answer = options[int(choice) - 1]
                break
            print("올바른 번호를 입력하세요.")

        history.append(QAPair(question=q["question"], options=options, answer=answer))

    return history


def build_transcript_text(basic_info: BasicInfo, history: list[QAPair]) -> str:
    return f"""[기본 정보]
{_basic_info_block(basic_info)}

[문답 기록]
{_format_history(history)}"""


_PLACEHOLDER_REASONS = {"", "...", "…", "<고른 근거 1~2문장>"}


def _extract_valid_recs(result: dict) -> list[dict] | None:
    """result가 {"recommendations": [정확히 3개, index가 정수, 근거도 채워진]} 형태인지 확인.

    로컬 소형 모델이 지시를 따르면서도 최상위 키 철자를 "recommendactions" 등으로
    틀리는 경우가 있어, 키 이름과 무관하게 형태가 맞는 리스트를 찾아 허용한다.
    """
    recs = result.get("recommendations")
    if not isinstance(recs, list):
        for value in result.values():
            if isinstance(value, list):
                recs = value
                break
    if not isinstance(recs, list) or len(recs) != 3:
        return None
    for rec in recs:
        if not isinstance(rec, dict) or "index" not in rec or "reason" not in rec:
            return None
        if not isinstance(rec.get("index"), int):
            return None
        if str(rec.get("reason", "")).strip() in _PLACEHOLDER_REASONS:
            return None
    return recs


def recommend_jobs(basic_info: BasicInfo, history: list[QAPair], retries: int = 3) -> dict:
    """2번 LLM 호출: 문답 결과를 바탕으로 직무 3개를 추천한다.

    직무명을 직접 베끼게 하면 JSON 강제 모드 + 로컬 소형 모델 조합에서
    한글이 깨져 나올 때가 있어서, 모델에게는 카탈로그의 번호(index)만
    고르게 하고 실제 직무는 Python에서 인덱스로 매핑한다. 그래서 이 결과는
    항상 DB에 실제로 존재하는 직무다 — 별도 사후 검증이 필요 없다.

    희망 분야를 선택한 사용자라면 그 분야(들)의 직무만 카탈로그에 담아
    프롬프트를 대폭 줄인다 (538개 전체를 볼 때보다 훨씬 빠르다).
    '잘 모르겠음'(분야 미선택)이면 기존처럼 전체 538개를 그대로 준다.
    """
    tables = basic_info.desired_field_codes or None
    catalog_rows, catalog_text = build_indexed_catalog(tables)

    user_prompt = f"""{build_transcript_text(basic_info, history)}

[직무 목록]
{catalog_text}

위 정보를 바탕으로 번호 3개를 JSON으로 추천하세요."""

    messages = [
        {"role": "system", "content": RECOMMEND_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    verified_recs: list[dict] | None = None
    last_result: dict = {}
    for _ in range(retries):
        last_result = chat_json(messages, temperature=0.4)
        recs = _extract_valid_recs(last_result)
        if recs is None:
            messages = messages + [
                {"role": "assistant", "content": json.dumps(last_result, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": (
                        "형식이 올바르지 않습니다. 최상위 키는 반드시 \"recommendations\" 하나여야 하고, "
                        "그 값은 정확히 3개의 객체로 이루어진 배열이어야 합니다. "
                        "각 객체는 반드시 index(정수)와 reason 키를 모두 가져야 합니다. "
                        "다른 설명 없이 이 형식의 JSON만 다시 출력하세요."
                    ),
                },
            ]
            continue

        indices = [rec["index"] for rec in recs]
        out_of_range = [i for i in indices if not (1 <= i <= len(catalog_rows))]
        has_dup = len(set(indices)) != len(indices)
        if out_of_range or has_dup:
            problems = []
            if out_of_range:
                problems.append(f"목록에 없는 번호: {out_of_range}")
            if has_dup:
                problems.append("번호가 서로 겹칩니다")
            messages = messages + [
                {"role": "assistant", "content": json.dumps(last_result, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": (
                        f"{' / '.join(problems)}. [직무 목록]에 실제로 있는 1~{len(catalog_rows)} "
                        "사이의 서로 다른 번호 3개를 다시 고르세요. 다른 설명 없이 JSON만 출력하세요."
                    ),
                },
            ]
            continue

        verified_recs = []
        for rec in recs:
            row = catalog_rows[rec["index"] - 1]
            verified_recs.append(
                {
                    "job_code": row.table,
                    "category": CATEGORY_NAMES[row.table],
                    "job": row.job,
                    "reason": (rec.get("reason") or "").strip(),
                    "verified": True,
                    "description": row.description,
                }
            )
        break

    if verified_recs is None:
        raise ValueError(f"LLM이 유효한 번호 3개를 지정된 형식으로 반환하지 않았습니다: {last_result}")

    return {"recommendations": verified_recs}
