"""최근 1개월 입찰공고 재조회 (공개목록 Y · 나라장터/모두입찰 우선)."""

from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

DATA_PATH = Path(__file__).parent / "data" / "results.json"
RESULTS_MD = Path(__file__).parent.parent / "results.md"

TARGET_KEYWORDS = [
    "K-ICS", "KICS", "IFRS", "헤지회계", "위험회피", "FVO",
    "시장리스크", "FRTB", "ALM", "파생", "공정가치", "가격평가",
    "금융자산 평가", "산금채", "자기자본비율", "시장위험",
]

CREDIT_EXCLUDE = ["신용평가모형", "부도율", "신용리스크 산출"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}

_lock = threading.Lock()
_state: dict[str, Any] = {
    "status": "idle",
    "message": "",
    "progress": 0,
    "total": 0,
}


def get_refresh_state() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _set_state(**kwargs: Any) -> None:
    with _lock:
        _state.update(kwargs)


def load_data() -> dict[str, Any]:
    with DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    write_results_md(data)


def period_last_month(today: date | None = None) -> tuple[date, date]:
    """기준일로부터 정확히 1개월 전 ~ 기준일."""
    from calendar import monthrange

    end = today or date.today()
    y, m, d = end.year, end.month, end.day
    if m == 1:
        start = date(y - 1, 12, min(d, monthrange(y - 1, 12)[1]))
    else:
        start = date(y, m - 1, min(d, monthrange(y, m - 1)[1]))
    return start, end


def _parse_date(text: str) -> date | None:
    m = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _is_target(title: str) -> bool:
    t = title.upper()
    if any(ex in title for ex in CREDIT_EXCLUDE) and "시장" not in title and "헤지" not in title:
        # 순수 신용 중심은 제외하되, 헤지/시장 혼합은 유지
        if not any(k.upper() in t or k in title for k in ["헤지", "IFRS", "K-ICS", "FVO", "시장리스크", "ALM", "파생", "가격평가"]):
            return False
    return any(k.upper() in t or k in title for k in TARGET_KEYWORDS)


def fetch_modoobid(org_name: str) -> list[dict[str, Any]]:
    url = f"https://www.modoobid.co.kr/bid/org/{quote(org_name)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as e:
        return [{"error": str(e), "title": "", "posted": None}]

    soup = BeautifulSoup(resp.text, "lxml")
    text = soup.get_text("\n", strip=True)
    items: list[dict[str, Any]] = []

    # 패턴: 유형 제목 ... 게시 YYYY-MM-DD
    chunks = re.split(r"\n(?=(?:물품|용역|공사)\s)", text)
    for chunk in chunks:
        if "게시 20" not in chunk:
            continue
        posted = _parse_date(chunk[chunk.find("게시") : chunk.find("게시") + 20])
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if not lines:
            continue
        title_line = lines[0]
        title = re.sub(r"^(물품|용역|공사)\s+", "", title_line).strip()
        # 지역·카테고리 꼬리 제거 시도
        title = re.split(r"\s+전국|\s+서울|\s+부산|\s+추정", title)[0].strip()
        if len(title) < 4:
            continue
        items.append({
            "title": title,
            "posted": posted.isoformat() if posted else None,
            "link": url,
        })

    # 보조: 게시 날짜만 나열된 경우 대비 정규식 스캔
    if not items:
        for m in re.finditer(
            r"(물품|용역|공사)\s+(.+?)\s+게시\s+(20\d{2}-\d{2}-\d{2})",
            text,
            re.DOTALL,
        ):
            title = re.sub(r"\s+", " ", m.group(2)).strip()
            title = re.split(r"\s+전국|\s+서울", title)[0].strip()
            items.append({
                "title": title[:120],
                "posted": m.group(3),
                "link": url,
            })

    return items


def filter_period(items: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    out = []
    for it in items:
        if it.get("error"):
            continue
        p = it.get("posted")
        if not p:
            continue
        d = _parse_date(p) if isinstance(p, str) else p
        if d and start <= d <= end:
            out.append({**it, "posted": d.isoformat()})
    return out


def build_rows_for_company(
    base: dict[str, Any],
    notices: list[dict[str, Any]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """기간 내 공고 → 목표분야 hit 행 또는 공고 없음 행."""
    hits = [n for n in notices if _is_target(n.get("title", ""))]
    total = len(notices)
    period_note = f"{start.isoformat()}~{end.isoformat()}"

    if hits:
        rows = []
        for i, h in enumerate(hits):
            row = deepcopy(base)
            suffix = "" if i == 0 else f"-{i}"
            row["no"] = f"{base['no'].split('-')[0]}{suffix}" if i else base["no"].split("-")[0]
            if i and "-" not in str(base["no"]):
                row["no"] = f"{base['no']}-{i}"
            elif i:
                row["no"] = f"{base['no'].split('-')[0]}-{i}"
            row["title"] = h["title"]
            row["announce_date"] = h.get("posted") or "-"
            row["deadline"] = "-"
            row["budget"] = "-"
            row["note"] = f"조회기간 내 공개목록 총 {total}건 중 목표분야 해당 ({period_note})"
            row["link"] = h.get("link") or base.get("link") or ""
            row["hit"] = True
            rows.append(row)
        return rows

    row = deepcopy(base)
    row["no"] = str(base["no"]).split("-")[0]
    row["hit"] = False
    if base.get("public_list") == "N":
        row["title"] = ""
        row["note"] = ""
        row["announce_date"] = "-"
        row["deadline"] = "-"
        row["budget"] = "-"
    else:
        row["title"] = f"공고 없음 (총 {total}건)"
        row["announce_date"] = "-"
        row["deadline"] = "-"
        row["budget"] = "-"
        row["note"] = f"조회기간 내 공개목록 전수 {total}건, 목표분야 미해당 ({period_note})"
    return [row]


def refresh_survey() -> dict[str, Any]:
    data = load_data()
    start, end = period_last_month()
    _set_state(status="running", message="최근 1개월 조회 시작", progress=0, total=0)

    # 회사 단위로 묶기 (산은 7 / 7-1 등)
    companies: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in data["rows"]:
        key = row["company"]
        if key not in companies:
            companies[key] = deepcopy(row)
            companies[key]["no"] = str(row["no"]).split("-")[0]
            order.append(key)

    _set_state(total=len(order))
    new_rows: list[dict[str, Any]] = []

    for idx, company in enumerate(order, start=1):
        base = companies[company]
        _set_state(progress=idx, message=f"조회 중: {company} ({idx}/{len(order)})")

        if base.get("public_list") == "N":
            row = deepcopy(base)
            row["title"] = ""
            row["note"] = ""
            row["announce_date"] = "-"
            row["deadline"] = "-"
            row["budget"] = "-"
            row["hit"] = False
            new_rows.append(row)
            continue

        notices: list[dict[str, Any]] = []
        if base.get("source") == "modoobid" or base.get("org_key") or base.get("org_keys"):
            keys = base.get("org_keys") or [base.get("org_key")]
            keys = [k for k in keys if k]
            for k in keys:
                notices.extend(filter_period(fetch_modoobid(k), start, end))
            # 중복 제목 제거
            seen = set()
            uniq = []
            for n in notices:
                t = n.get("title", "")
                if t in seen:
                    continue
                seen.add(t)
                uniq.append(n)
            notices = uniq
            built = build_rows_for_company(base, notices, start, end)
            new_rows.extend(built)
        else:
            # 홈페이지 게시판: 네트워크 제약이 많아 기간만 갱신하고 기존 집계 유지 안내
            row = deepcopy(base)
            if row.get("hit"):
                # 기존 hit는 기간 밖이면 공고 없음으로 전환 시도는 불가 → 유지 + 기간 문구
                ad = _parse_date(row.get("announce_date") or "")
                if ad and not (start <= ad <= end):
                    row["hit"] = False
                    row["title"] = "공고 없음 (총 확인필요)"
                    row["announce_date"] = "-"
                    row["deadline"] = "-"
                    row["budget"] = "-"
                    row["note"] = (
                        f"홈페이지 게시판 자동전수 제한. 조회기간 {start}~{end} "
                        f"(이전 hit 공고일이 기간 외)"
                    )
                else:
                    row["note"] = (row.get("note") or "") + f" · 조회기간 {start}~{end}"
            else:
                # 총 N건 유지하되 기간 문구 갱신
                m = re.search(r"총\s*(\d+)건", row.get("title") or "")
                total = m.group(1) if m else "?"
                if row.get("title", "").startswith("공고 없음"):
                    row["title"] = f"공고 없음 (총 {total}건)" if total != "?" else row["title"]
                row["note"] = (
                    f"홈페이지 게시판(수동전수 기준 유지). "
                    f"나라장터 자동갱신 대상 아님. 조회기간 {start}~{end}"
                )
            new_rows.append(row)

    data["period_start"] = start.isoformat()
    data["period_end"] = end.isoformat()
    data["survey_date"] = end.isoformat()
    data["last_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["rows"] = new_rows
    data["status"] = "idle"
    data["message"] = f"갱신 완료 ({start} ~ {end})"
    save_data(data)
    _set_state(status="idle", message=data["message"], progress=len(order), total=len(order))
    return data


def start_refresh_async() -> bool:
    st = get_refresh_state()
    if st.get("status") == "running":
        return False

    def worker() -> None:
        try:
            refresh_survey()
        except Exception as e:  # noqa: BLE001
            _set_state(status="error", message=f"갱신 실패: {e}")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return True


def write_results_md(data: dict[str, Any]) -> None:
    lines = [
        f"**조회기간:** {data['period_start']} ~ {data['period_end']} (기본 1개월)  ",
        f"**조사기준일:** {data['survey_date']}  ",
        "",
        "※ `공고 없음 (총 N건)` = 조회기간 내 공개목록 N건 확인, 목표분야 미해당.  ",
        "※ `공개목록` = 로그인 없이 열람 가능한 입찰·공고 목록 (Y/N). **N이면 사업명·내용 공란.**",
        "",
        "| 번호 | 회사명 | 공개목록 | 사업명 | 공고일 | 마감일 | 예산 | 내용 | 링크 |",
        "|---:|---|:---:|---|---|---|---|---|---|",
    ]
    for r in data["rows"]:
        lines.append(
            f"| {r.get('no','')} | {r.get('company','')} | {r.get('public_list','')} | "
            f"{r.get('title','')} | {r.get('announce_date','-')} | {r.get('deadline','-')} | "
            f"{r.get('budget','-')} | {r.get('note','')} | {r.get('link','')} |"
        )
    RESULTS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
