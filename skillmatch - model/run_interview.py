"""LLM 기반 직무 추천 인터뷰 실행기.

사전 준비:
  ollama serve
  ollama pull gemma3n:e2b       # 또는 OLLAMA_MODEL 환경변수로 원하는 모델 지정

실행:
  python run_interview.py
"""
from __future__ import annotations

from app.job_catalog import CATEGORY_NAMES
from app.llm_interview import (
    BasicInfo,
    build_transcript_text,
    recommend_jobs,
    run_interactive_interview,
)


MAX_DESIRED_FIELDS = 3


def _ask_basic_info() -> BasicInfo:
    print("=== 기본 정보 ===")
    age = int(input("나이: ").strip())
    gender = input("성별: ").strip()

    codes = list(CATEGORY_NAMES)
    dont_know_no = len(codes) + 1

    print(f"\n희망 분야를 선택하세요 (최대 {MAX_DESIRED_FIELDS}개까지, 쉼표로 구분. 예: 1,3,5):")
    for i, code in enumerate(codes, start=1):
        print(f"  {i}. {CATEGORY_NAMES[code]}")
    print(f"  {dont_know_no}. 잘 모르겠음")

    while True:
        raw = input("번호 선택: ").strip()
        picks = [p for p in raw.replace(" ", ",").split(",") if p]

        if not picks or not all(p.isdigit() for p in picks):
            print("숫자를 쉼표로 구분해서 입력하세요.")
            continue

        nums = [int(p) for p in picks]
        if any(n < 1 or n > dont_know_no for n in nums):
            print("올바른 번호를 입력하세요.")
            continue
        if len(set(nums)) != len(nums):
            print("같은 번호를 중복 선택할 수 없습니다.")
            continue

        if dont_know_no in nums:
            if len(nums) > 1:
                print("'잘 모르겠음'은 다른 분야와 함께 선택할 수 없습니다.")
                continue
            desired_field_codes: list[str] = []
            break

        if len(nums) > MAX_DESIRED_FIELDS:
            print(f"최대 {MAX_DESIRED_FIELDS}개까지만 선택할 수 있습니다.")
            continue

        desired_field_codes = [codes[n - 1] for n in nums]
        break

    return BasicInfo(age=age, gender=gender, desired_field_codes=desired_field_codes)


def main() -> None:
    basic_info = _ask_basic_info()
    history = run_interactive_interview(basic_info)

    print("\n=== 인터뷰 요약 ===")
    print(build_transcript_text(basic_info, history))

    print("\n추천을 생성하는 중입니다...")
    result = recommend_jobs(basic_info, history)

    print("\n=== 추천 직무 3가지 ===")
    for i, rec in enumerate(result["recommendations"], start=1):
        mark = "OK" if rec["verified"] else "!! (DB 미확인)"
        print(f"{i}. [{rec['category']}] {rec['job']} [{mark}]")
        print(f"   이유: {rec['reason']}")


if __name__ == "__main__":
    main()
