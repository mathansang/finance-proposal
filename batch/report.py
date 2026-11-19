"""survey JSON → prompt.md §9 형식 MD + GitHub Pages용 정적 HTML."""

from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path
from typing import Any


PROPOSAL_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROPOSAL_ROOT / "docs"
ARCHIVE_DIR = DOCS_DIR / "archive"


def _ymd(survey_date: str | None) -> str:
    if survey_date and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", survey_date):
        return survey_date.replace("-", "")
    return date.today().strftime("%Y%m%d")


def _hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("hit")]


def _public_y(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("public_list") == "Y"]


def _companies(rows: list[dict[str, Any]]) -> int:
    return len({r.get("company") for r in rows if r.get("company")})


def build_markdown(data: dict[str, Any]) -> str:
    rows = data.get("rows") or []
    hits = _hits(rows)
    survey_date = data.get("survey_date") or date.today().isoformat()
    period_start = data.get("period_start") or "-"
    period_end = data.get("period_end") or "-"
    last_refresh = data.get("last_refresh") or "-"
    n_companies = _companies(rows)
    n_public = len(_public_y(rows))
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
        f"| 공개목록 조회 가능(Y) | {n_public} |",
        "| 검색 방식 | 모두입찰(modoobid) 공개목록 + 기존 홈페이지 게시판 집계 유지 |",
        f"| 목표분야 hit 공고 수 | **{len(hits)}** |",
        f"| 공개목록 내 목표분야 미해당(공고 없음) | {n_closed_public} |",
        "| 신용리스크 제외 | 키워드 필터로 순수 신용 중심 제목 제외 (상세 원문 검증은 별도) |",
        "",
        "### 핵심 결론",
        "",
    ]

    if hits:
        lines.append(
            f"조회기간 내 목표분야(시장리스크·ALM·K-ICS·IFRS·파생·공정가치 등) "
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
            deadline = r.get("deadline") or "확인 불가"
            if deadline in ("-", ""):
                deadline = "확인 불가"
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
            "## 9.4 기관별 조회 결과 (전체)",
            "",
            "| 번호 | 기관 | 공개목록 | 사업명/결과 | 공고일 | 비고 | 링크 |",
            "|---:|---|:---:|---|---|---|---|",
        ]
    )

    for r in rows:
        link = r.get("link") or ""
        link_cell = f"[링크]({link})" if link else ""
        title = r.get("title") or ("(공개목록 N)" if r.get("public_list") == "N" else "")
        lines.append(
            f"| {r.get('no', '')} | {r.get('company', '')} | {r.get('public_list', '')} | "
            f"{title} | {r.get('announce_date', '-')} | {r.get('note', '')} | {link_cell} |"
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
            "4. 공개목록이 N인 기관은 사업명·내용을 공란으로 둡니다.",
            "5. 신용리스크 중심 사업은 제목 키워드 필터로만 제외하며, 혼합형 사업은 원문 재검토가 필요합니다.",
            "",
            f"**검색 한계 명시:** 조사 기준일 {survey_date}, 조회기간 {period_start}~{period_end}, "
            f"기관 {n_companies}곳. 자동수집으로 확인하지 못한 기관·사이트는 '미검색'과 동일하게 취급하지 말고 "
            "누락 가능성으로 해석해야 합니다.",
            "",
        ]
    )
    return "\n".join(lines)


def build_index_html(data: dict[str, Any], archive_names: list[str]) -> str:
    rows = data.get("rows") or []
    hits = _hits(rows)
    survey_date = html.escape(str(data.get("survey_date") or "-"))
    period_start = html.escape(str(data.get("period_start") or "-"))
    period_end = html.escape(str(data.get("period_end") or "-"))
    last_refresh = html.escape(str(data.get("last_refresh") or "-"))

    hit_rows = []
    if hits:
        for r in hits:
            link = r.get("link") or ""
            title = html.escape(str(r.get("title") or ""))
            company = html.escape(str(r.get("company") or ""))
            posted = html.escape(str(r.get("announce_date") or "-"))
            if link:
                title_cell = f'<a href="{html.escape(link)}" target="_blank" rel="noopener">{title}</a>'
            else:
                title_cell = title
            hit_rows.append(
                f"<tr><td>{company}</td><td>{title_cell}</td><td>{posted}</td></tr>"
            )
    else:
        hit_rows.append(
            '<tr><td colspan="3">목표분야 자동탐지 공고 없음</td></tr>'
        )

    archive_items = []
    for name in archive_names:
        safe = html.escape(name)
        archive_items.append(f'<li><a href="archive/{safe}">{safe}</a></li>')
    if not archive_items:
        archive_items.append("<li>(아카이브 없음)</li>")

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>금융권 신규프로젝트 공고현황</title>
  <style>
    :root {{
      --bg: #f7f5f1;
      --ink: #1a1a1a;
      --muted: #5c5c5c;
      --line: #d8d2c8;
      --accent: #0b5fff;
      --card: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Pretendard", "Noto Sans KR", "Malgun Gothic", sans-serif;
      background: linear-gradient(180deg, #efebe3 0%, var(--bg) 40%);
      color: var(--ink);
      line-height: 1.55;
    }}
    main {{
      max-width: 960px;
      margin: 0 auto;
      padding: 2.5rem 1.25rem 4rem;
    }}
    h1 {{
      font-size: clamp(1.6rem, 3vw, 2.1rem);
      margin: 0 0 0.4rem;
      letter-spacing: -0.02em;
    }}
    .meta {{ color: var(--muted); font-size: 0.95rem; margin-bottom: 1.5rem; }}
    .stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 1.75rem;
    }}
    .stat {{
      background: var(--card);
      border: 1px solid var(--line);
      padding: 0.85rem 1.1rem;
      min-width: 8rem;
    }}
    .stat strong {{ display: block; font-size: 1.4rem; }}
    .stat span {{ color: var(--muted); font-size: 0.85rem; }}
    section {{
      background: var(--card);
      border: 1px solid var(--line);
      padding: 1.25rem 1.35rem;
      margin-bottom: 1.25rem;
    }}
    h2 {{
      margin: 0 0 0.85rem;
      font-size: 1.15rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      text-align: left;
      padding: 0.55rem 0.4rem;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    a {{ color: var(--accent); }}
    ul {{ margin: 0; padding-left: 1.2rem; }}
    .links a {{ margin-right: 1rem; }}
    footer {{
      color: var(--muted);
      font-size: 0.85rem;
      margin-top: 1.5rem;
    }}
  </style>
</head>
<body>
  <main>
    <h1>금융권 신규프로젝트 공고현황</h1>
    <p class="meta">
      조사 기준일 {survey_date} · 조회기간 {period_start} ~ {period_end}<br />
      자동갱신 {last_refresh}
    </p>
    <div class="stats">
      <div class="stat"><strong>{len(hits)}</strong><span>목표분야 hit</span></div>
      <div class="stat"><strong>{_companies(rows)}</strong><span>조사 기관</span></div>
      <div class="stat"><strong>{len(_public_y(rows))}</strong><span>공개목록 Y</span></div>
    </div>
    <section>
      <h2>목표분야 해당 공고</h2>
      <table>
        <thead><tr><th>기관</th><th>사업명</th><th>공고일</th></tr></thead>
        <tbody>
          {"".join(hit_rows)}
        </tbody>
      </table>
    </section>
    <section>
      <h2>문서</h2>
      <p class="links">
        <a href="latest.md">최신 보고서 (Markdown)</a>
        <a href="archive/">아카이브 폴더</a>
      </p>
      <h2>아카이브</h2>
      <ul>
        {"".join(archive_items)}
      </ul>
    </section>
    <footer>
      자동수집 결과입니다. 예산·마감·참가요건은 공식 원문으로 재확인하세요.
      신용리스크 중심 사업은 키워드 필터로만 제외됩니다.
    </footer>
  </main>
</body>
</html>
"""


def write_docs(data: dict[str, Any], docs_dir: Path | None = None) -> dict[str, Path]:
    """MD/HTML을 docs/에 기록하고 생성된 경로를 반환."""
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

    # 기존 아카이브 목록 (최신순)
    archive_names = sorted(
        (p.name for p in archive.glob("금융권_신규프로젝트_공고현황_*.md")),
        reverse=True,
    )

    index_path = root / "index.html"
    index_path.write_text(build_index_html(data, archive_names), encoding="utf-8")

    # GitHub Pages가 디렉터리 링크를 열 때 빈 안내가 보이도록
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
        "archive_index": archive_index,
    }
