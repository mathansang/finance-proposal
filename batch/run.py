"""일일 조사 CLI: (선택) 수집 → docs/ 정적 문서 생성 → (선택) git push."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BATCH_DIR = Path(__file__).resolve().parent
PROPOSAL_ROOT = BATCH_DIR.parent
WEBAPP_DIR = PROPOSAL_ROOT / "webapp"


def _ensure_paths() -> None:
    # webapp.survey / batch.* import
    for p in (str(PROPOSAL_ROOT), str(WEBAPP_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="금융권 공고 일일 조사 → docs/ (GitHub Pages) 생성",
    )
    p.add_argument(
        "--skip-fetch",
        action="store_true",
        help="네트워크 수집 생략, 기존 webapp/data/results.json 으로 문서만 생성",
    )
    p.add_argument(
        "--push",
        action="store_true",
        help="docs/ 등 변경을 commit 후 origin 으로 push",
    )
    p.add_argument(
        "--commit",
        action="store_true",
        help="push 없이 commit 만 수행",
    )
    p.add_argument(
        "--message",
        default=None,
        help="git commit 메시지",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _ensure_paths()

    from batch.report import write_docs
    from batch.publish import publish_docs

    if args.skip_fetch:
        from survey import load_data

        print("[batch] --skip-fetch: 기존 results.json 사용")
        data = load_data()
    else:
        from survey import refresh_survey

        print("[batch] 최근 1개월 공개목록 수집 중...")
        data = refresh_survey()
        print(f"[batch] 수집 완료: {data.get('message', '')}")

    paths = write_docs(data)
    print(f"[batch] 보고서: {paths['archive']}")
    print(f"[batch] latest:  {paths['latest']}")
    print(f"[batch] index:   {paths['index']}")
    print(f"[batch] data:    {paths['data']}")

    if args.push or args.commit:
        result = publish_docs(
            push=bool(args.push),
            message=args.message,
        )
        flag = "OK" if result["ok"] else "FAIL"
        print(f"[batch] git [{flag}] {result['detail']}")
        if not result["ok"]:
            return 1
    else:
        print("[batch] git 생략 (필요 시 --commit / --push)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
