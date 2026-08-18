"""SAMPLE_JOBS의 직업명을 워크넷 원본(jobs.json)과 대조한다."""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.seed.sample_jobs import SAMPLE_JOBS
from app.seed.taxonomy import TAXONOMY

JOBS_JSON = Path("data/jobs.json")
SAMPLE_PATH = Path("app/seed/sample_jobs.py")

MID_NAME = {
    mid_key: mid_name
    for _mk, _mn, _cnt, mids in TAXONOMY
    for mid_key, mid_name in mids
}


def normalize(s: str) -> str:
    """띄어쓰기·가운뎃점·괄호를 제거해 표기 차이를 무시한 비교용 키."""
    return re.sub(r"[\s·∙()\-]", "", s)


def load_real(path: Path) -> tuple[set[str], dict[str, list[str]]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    all_names = {r["job"] for r in rows}
    by_mid: dict[str, list[str]] = {}
    for r in rows:
        by_mid.setdefault(r["mid"], []).append(r["job"])
    return all_names, by_mid


def suggest(target: str, pool: list[str], limit: int = 3) -> list[str]:
    key = normalize(target)

    exact = [p for p in pool if normalize(p) == key]
    if exact:
        return exact

    contains = [p for p in pool if key in normalize(p) or normalize(p) in key]
    fuzzy = difflib.get_close_matches(target, pool, n=limit, cutoff=0.5)

    out: list[str] = []
    for name in contains + fuzzy:
        if name not in out:
            out.append(name)
    return out[:limit]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=Path, default=JOBS_JSON)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not args.jobs.exists():
        print(f"jobs.json 을 찾을 수 없습니다: {args.jobs}")
        raise SystemExit(1)

    real_names, by_mid = load_real(args.jobs)
    ok, auto, manual = [], [], []

    for spec in SAMPLE_JOBS:
        name = spec["name"]
        if name in real_names:
            ok.append(name)
            continue

        mid_name = MID_NAME.get(spec["mid_key"], "")
        pool = by_mid.get(mid_name, [])
        cands = suggest(name, pool)

        confident = [c for c in cands if normalize(c) == normalize(name)]
        if len(confident) == 1:
            auto.append((name, confident[0], mid_name))
        else:
            manual.append((name, cands, mid_name, pool))

    print(f"\n일치 {len(ok)}개 / 자동교정 가능 {len(auto)}개 / 수동확인 {len(manual)}개\n")

    if auto:
        print("=" * 64)
        print("자동 교정 가능 (띄어쓰기·표기 차이)")
        print("=" * 64)
        for old, new, mid in auto:
            print(f"  {old!r}\n    -> {new!r}   [{mid}]")
        print()

    if manual:
        print("=" * 64)
        print("수동 확인 필요")
        print("=" * 64)
        for old, cands, mid, pool in manual:
            print(f"\n  [{old}]   ({mid})")
            if cands:
                print("     비슷한 후보:")
                for c in cands:
                    print(f"       - {c}")
            else:
                print("     비슷한 후보 없음")
            print(f"     이 중분류의 전체 직업 {len(pool)}개:")
            for p in pool:
                print(f"       . {p}")
        print()

    if args.apply and auto:
        text = SAMPLE_PATH.read_text(encoding="utf-8")
        changed = 0
        for old, new, _mid in auto:
            if f'_j("{old}"' in text:
                text = text.replace(f'_j("{old}"', f'_j("{new}"', 1)
                changed += 1
        SAMPLE_PATH.write_text(text, encoding="utf-8")
        print(f"{SAMPLE_PATH} 에 {changed}건 반영했습니다.")
        print("-> py -m scripts.init_db --reset --jobs data/jobs.json 로 다시 시딩하세요.\n")
    elif args.apply:
        print("자동 교정할 항목이 없습니다.\n")


if __name__ == "__main__":
    main()