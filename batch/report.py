"""survey JSON → prompt.md §9 형식 MD + Pages용 data.json (Vue 템플릿 분리)."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROPOSAL_ROOT = Path(__file__).resolve().parent.parent
BATCH_DIR = Path(__file__).resolve().parent
DOCS_DIR = PROPOSAL_ROOT / "docs"
ARCHIVE_DIR = DOCS_DIR / "archive"
TEMPLATE_INDEX = BATCH_DIR / "templates" / "index.html"
TEMPLATE_SHINHAN_REDIRECT = BATCH_DIR / "templates" / "redirect-shinhan.html"


def _ymd(survey_date: str | None) -> str:
    if survey_date and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", survey_date):
        return survey_date.replace("-", "")
    return date.today().strftime("%Y%m%d")


def _announce_sort_key(value: Any) -> tuple[int, int, int]:
    text = str(value or "")
    m = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", text)
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits = [r for r in rows if r.get("hit")]
    return sorted(hits, key=lambda r: _announce_sort_key(r.get("announce_date")), reverse=True)


def _public_y(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("public_list") == "Y"]


def _companies(rows: list[dict[str, Any]]) -> int:
    return len({r.get("company") for r in rows if r.get("company")})


def _display_deadline(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^개찰\s*", "", text)
    text = re.sub(r"\s*\(마감\)\s*$", "", text).strip()
    m = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if not text or text == "-":
        return "확인 불가"
    return text


def _unique_institutions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """기관별 1행 (조사 링크·공개목록). hit가 있으면 해당 행 우선."""
    by_company: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for r in rows:
        company = str(r.get("company") or "").strip()
        if not company:
            continue
        if company not in by_company:
            by_company[company] = r
            order.append(company)
            continue
        prev = by_company[company]
        if r.get("hit") and not prev.get("hit"):
            by_company[company] = r
    return [by_company[c] for c in order]


def build_markdown(data: dict[str, Any]) -> str:
    rows = data.get("rows") or []
    hits = _hits(rows)
    survey_date = data.get("survey_date") or date.today().isoformat()
    period_start = data.get("period_start") or "-"
    period_end = data.get("period_end") or "-"
    last_refresh = data.get("last_refresh") or "-"
    n_companies = _companies(rows)
    n_closed_public = sum(
        1
        for r in _public_y(rows)
        if not r.get("hit") and str(r.get("title") or "").startswith("공고 없음")
    )

    lines: list[str] = [
        "# 금융권 신규프로젝트 공고현황",
        "",
        f"**조사 기준일:** {survey_date}  ",
        f"**조회기간:** {period_start} ~ {period_end}  ",
        f"**자동갱신:** {last_refresh}  ",
        "",
        "> 본 문서는 공개목록 자동수집(모두입찰·기관 공개목록) 결과입니다. "
        "예산·마감·RFP·참가요건은 원문 확인 전 **확인 불가**로 표시합니다.",
        "",
        "---",
        "",
        "## 9.1 조사 요약",
        "",
        "| 항목 | 내용 |",
        "|---|---|",
        f"| 조사 기준일 | {survey_date} |",
        f"| 조사 대상 기관 수 | {n_companies} |",
        "| 검색 방식 | 모두입찰(modoobid) 공개목록 + 기존 홈페이지 게시판 집계 유지 |",
        f"| 목표분야 hit 공고 수 | **{len(hits)}** |",
        f"| 목표분야 미해당(공고 없음 표기) | {n_closed_public} |",
        "| 목표분야 | 시장·신용리스크, ALM, K-ICS, IFRS, 파생·공정가치 등 |",
        "",
        "### 핵심 결론",
        "",
    ]

    if hits:
        lines.append(
            f"조회기간 내 목표분야(시장·신용리스크·ALM·K-ICS·IFRS·파생·공정가치 등) "
            f"**관련 공고 {len(hits)}건**이 자동 탐지되었습니다. "
            "접수 가능 여부는 원문 마감일 확인이 필요합니다."
        )
    else:
        lines.append(
            "조회기간 내 목표분야 키워드에 해당하는 **자동 탐지 공고는 없습니다.** "
            "공개목록 미제공 기관·홈페이지 게시판은 자동전수 제한이 있어 누락 가능성이 있습니다."
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 9.2 목표분야 해당 공고 (자동탐지)",
            "",
            "| 번호 | 기관 | 사업명 | 예산 | 마감 | 분야 | 참여 방식 | 공고 링크 |",
            "|---|---|---|---:|---|---|---|---|",
        ]
    )

    if hits:
        for i, r in enumerate(hits, start=1):
            budget = r.get("budget") or "확인 불가"
            if budget in ("-", ""):
                budget = "확인 불가"
            deadline = _display_deadline(r.get("deadline"))
            link = r.get("link") or ""
            link_cell = f"[링크]({link})" if link else "확인 불가"
            lines.append(
                f"| {i} | {r.get('company', '')} | {r.get('title', '')} | "
                f"{budget} | {deadline} | 확인 불가 | 확인 불가 | {link_cell} |"
            )
    else:
        lines.append(
            "| — | — | **목표분야 자동탐지 공고 없음** | — | — | — | — | — |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 9.3 접수 예정 공고",
            "",
            "| 번호 | 기관 | 사업명 | 예상 일정 | 분야 | 확인 근거 |",
            "|---|---|---|---|---|---|",
            "| — | — | 자동수집 범위 외 (발주계획 별도 모니터링 필요) | — | — | — |",
            "",
            "---",
            "",
            "## 9.4 조사 기관 전체 목록",
            "",
            "| 번호 | 기관 | 조사 링크 |",
            "|---:|---|---|",
        ]
    )

    for i, r in enumerate(_unique_institutions(rows), start=1):
        link = (r.get("link") or "").strip()
        link_cell = f"[{link}]({link})" if link else "—"
        lines.append(f"| {i} | {r.get('company', '')} | {link_cell} |")

    lines.extend(
        [
            "",
            "### 기관별 조회 결과 상세",
            "",
            "| 번호 | 기관 | 사업명/결과 | 공고일 | 마감일 | 비고 | 링크 |",
            "|---:|---|---|---|---|---|---|",
        ]
    )

    for r in rows:
        link = (r.get("link") or "").strip()
        link_cell = f"[{link}]({link})" if link else "—"
        title = r.get("title") or "—"
        deadline = _display_deadline(r.get("deadline"))
        lines.append(
            f"| {r.get('no', '')} | {r.get('company', '')} | "
            f"{title} | {r.get('announce_date', '-')} | {deadline} | "
            f"{r.get('note', '')} | {link_cell} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 9.5 참여 우선순위",
            "",
            "| 순위 | 사업명 | 직접/협력 참여 | 적합도 | 판단 근거 |",
            "|---|---|---|---|---|",
        ]
    )
    if hits:
        for i, r in enumerate(hits, start=1):
            lines.append(
                f"| {i} | {r.get('title', '')} | 확인 불가 | 자동탐지 | "
                f"키워드 매칭 · 원문·참가요건 미검증 |"
            )
    else:
        lines.append("| — | — | — | — | 해당 없음 |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 9.6 공고별 상세 / 조사 한계",
            "",
            "1. 본 배치는 나라장터 API·기관 로그인 게시판 전수를 수행하지 않습니다.",
            "2. 모두입찰 공개목록 및 기존 수동 집계를 기준으로 하며, 제목 키워드로 목표분야를 판별합니다.",
            "3. 예산·마감·입찰방식·참가요건·RFP는 원문 확인 없이 추정하지 않습니다.",
            "4. 로그인·회원 전용 게시판만 있는 기관은 자동전수하지 못했으며, "
            "링크가 기관 홈페이지 수준이면 입찰목록 URL을 아직 확보하지 못한 것입니다.",
            "5. 신용리스크(PD/LGD/IRB·신용평가 등)도 목표분야 키워드에 포함합니다.",
            "",
            f"**검색 한계 명시:** 조사 기준일 {survey_date}, 조회기간 {period_start}~{period_end}, "
            f"기관 {n_companies}곳. 자동수집으로 확인하지 못한 기관·사이트는 '미검색'과 동일하게 취급하지 말고 "
            "누락 가능성으로 해석해야 합니다.",
            "",
        ]
    )
    return "\n".join(lines)


def _git_short_sha(repo: Path | None = None) -> str:
    root = repo or PROPOSAL_ROOT
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        sha = (r.stdout or "").strip()
        return sha if r.returncode == 0 and sha else "unknown"
    except OSError:
        return "unknown"


def _page_build_meta(repo: Path | None = None) -> dict[str, str]:
    """배포 확인용: 페이지 생성 시각 + git 버전."""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    updated = now.strftime("%Y-%m-%d %H:%M:%S KST")
    sha = _git_short_sha(repo)
    stamp = now.strftime("%Y%m%d%H%M%S")
    return {
        "page_updated_at": updated,
        "page_version": f"{sha}-{stamp}",
    }


def build_pages_payload(data: dict[str, Any], archive_names: list[str]) -> dict[str, Any]:
    """Vue가 fetch하는 data.json 본문."""
    meta = _page_build_meta()
    try:
        from survey import TARGET_KEYWORDS_DISPLAY
        keywords = list(TARGET_KEYWORDS_DISPLAY)
    except Exception:  # noqa: BLE001
        keywords = data.get("target_keywords") or []
    return {
        "survey_date": data.get("survey_date"),
        "period_start": data.get("period_start"),
        "period_end": data.get("period_end"),
        "last_refresh": data.get("last_refresh"),
        "message": data.get("message"),
        "rows": data.get("rows") or [],
        "archives": archive_names,
        "target_keywords": keywords,
        **meta,
    }


def write_docs(data: dict[str, Any], docs_dir: Path | None = None) -> dict[str, Path]:
    """MD + data.json 기록, Vue 템플릿을 docs/index.html 로 복사."""
    root = docs_dir or DOCS_DIR
    archive = root / "archive"
    archive.mkdir(parents=True, exist_ok=True)

    ymd = _ymd(data.get("survey_date"))
    report_name = f"금융권_신규프로젝트_공고현황_{ymd}.md"
    md_text = build_markdown(data)

    archive_path = archive / report_name
    archive_path.write_text(md_text, encoding="utf-8")

    latest_path = root / "latest.md"
    latest_path.write_text(md_text, encoding="utf-8")

    archive_names = sorted(
        (p.name for p in archive.glob("금융권_신규프로젝트_공고현황_*.md")),
        reverse=True,
    )

    if not TEMPLATE_INDEX.is_file():
        raise FileNotFoundError(f"Vue 템플릿 없음: {TEMPLATE_INDEX}")

    index_path = root / "index.html"
    shutil.copyfile(TEMPLATE_INDEX, index_path)

    shinhan_redirect = root / "redirect-shinhan.html"
    if TEMPLATE_SHINHAN_REDIRECT.is_file():
        shutil.copyfile(TEMPLATE_SHINHAN_REDIRECT, shinhan_redirect)

    data_path = root / "data.json"
    payload = build_pages_payload(data, archive_names)
    data_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    archive_index = archive / "index.html"
    items = "\n".join(
        f'<li><a href="{html.escape(n)}">{html.escape(n)}</a></li>' for n in archive_names
    )
    archive_index.write_text(
        f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8" /><title>아카이브</title></head>
<body>
  <h1>공고현황 아카이브</h1>
  <p><a href="../index.html">← 목록으로</a></p>
  <ul>{items or "<li>(없음)</li>"}</ul>
</body></html>
""",
        encoding="utf-8",
    )

    return {
        "archive": archive_path,
        "latest": latest_path,
        "index": index_path,
        "data": data_path,
        "archive_index": archive_index,
    }
