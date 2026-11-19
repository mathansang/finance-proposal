"""최근 1개월 입찰공고 재조회 (공개목록 Y · 나라장터/모두입찰 우선)."""

from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

DATA_PATH = Path(__file__).parent / "data" / "results.json"
RESULTS_MD = Path(__file__).parent.parent / "results.md"

# 페이지 '목표분야 판별'에 노출하는 기준 키워드와 동일하게 유지
TARGET_KEYWORDS = [
    "시장리스크", "FRTB", "ALM", "K-ICS", "KICS", "IFRS", "RMS", "리스크관리",
    "헤지회계", "위험회피", "FVO", "파생", "공정가치", "가격평가",
    "산금채", "자기자본비율",
    "신용리스크", "신용평가", "IRB", "PD", "LGD", "EAD",
    "부도율", "여신포트폴리오", "스트레스테스트", "스트레스 테스트",
]

# UI 표기용 (검색 동의어 KICS·스트레스 테스트 공백형은 숨김)
TARGET_KEYWORDS_DISPLAY = [
    "시장리스크", "FRTB", "ALM", "K-ICS", "IFRS", "RMS", "리스크관리",
    "헤지회계", "위험회피", "FVO", "파생", "공정가치", "가격평가",
    "산금채", "자기자본비율",
    "신용리스크", "신용평가", "IRB", "PD", "LGD", "EAD",
    "부도율", "여신포트폴리오", "스트레스테스트",
]

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
    for k in TARGET_KEYWORDS:
        ku = k.upper()
        # 짧은 영문 약어(PD/LGD 등)는 단어 경계로 매칭 (PDF 오탐 방지)
        if len(ku) <= 3 and ku.isascii() and ku.isalpha():
            if re.search(rf"(?<![A-Z0-9]){re.escape(ku)}(?![A-Z0-9])", t):
                return True
        elif ku in t or k in title:
            return True
    return False


def fetch_modoobid(org_name: str) -> list[dict[str, Any]]:
    """기관 공개목록에서 개별 공고 상세 URL(/bid/…)을 추출."""
    list_url = f"https://www.modoobid.co.kr/bid/org/{quote(org_name)}"
    try:
        resp = requests.get(list_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as e:
        return [{"error": str(e), "title": "", "posted": None}]

    soup = BeautifulSoup(resp.text, "lxml")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not re.match(r"^/bid/[A-Za-z0-9]+/\d{4}", href):
            continue
        detail = urljoin("https://www.modoobid.co.kr", href)
        if detail in seen:
            continue
        text = " ".join((a.get_text() or "").split())
        m_title = re.search(r"(?:물품|용역|공사)\s+(.+?)(?:\s+전국|\s+서울|\s+부산|\s+게시\s+20)", text)
        if m_title:
            title = m_title.group(1).strip()
        else:
            title = re.sub(r"^(물품|용역|공사)\s+", "", text).strip()
            title = re.split(r"\s+전국|\s+서울|\s+부산|\s+게시\s+20", title)[0].strip()
        if len(title) < 4:
            continue
        posted = None
        m_date = re.search(r"게시\s+(20\d{2}-\d{2}-\d{2})", text)
        if m_date:
            posted = m_date.group(1)
        seen.add(detail)
        items.append({
            "title": title[:200],
            "posted": posted,
            "link": detail,
        })

    return items


def fetch_shinhan_notices() -> list[dict[str, Any]]:
    """신한금융그룹 PR 공지 API → 상세(boardNo) 링크."""
    api = "https://www.shinhangroup.com/api/v1/pr/notice/list"
    headers = {
        **HEADERS,
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.shinhangroup.com",
        "Referer": "https://www.shinhangroup.com/kr/pr/notice",
    }
    items: list[dict[str, Any]] = []
    try:
        resp = requests.post(
            api,
            headers=headers,
            data={
                "pageType": "FRONT",
                "lang": "KOR",
                "current": 1,
                "searchText": "",
            },
            timeout=25,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as e:
        return [{"error": str(e), "title": "", "posted": None}]

    rows = ((payload or {}).get("result") or {}).get("list") or []
    for row in rows:
        title = str(row.get("title") or "").strip()
        board_no = row.get("boardNo")
        if not title or board_no is None:
            continue
        # 사이트 상세는 POST only → Pages 리다이렉트로 연결
        link = f"redirect-shinhan.html?boardNo={board_no}"
        base_dt = str(row.get("baseDt") or "").replace(".", "-")
        posted = None
        d = _parse_date(base_dt)
        if d:
            posted = d.isoformat()
        items.append({
            "title": re.sub(r"^\[입찰안내\]\s*", "", title).strip(),
            "posted": posted,
            "link": link,
            "board_no": board_no,
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


def _fmt_ymd(y: str | int, m: str | int, d: str | int) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _fmt_deadline(ymd: str, hour: str | int | None = None, minute: str | int | None = None) -> str:
    # 화면에는 날짜만 표기 (시각 파싱 인자는 호환용으로 유지)
    _ = (hour, minute)
    return ymd


def parse_deadline_from_text(text: str) -> str | None:
    """상세 본문/텍스트에서 마감·제출기한·개찰일 추출."""
    if not text:
        return None
    compact = re.sub(r"[ \t]+", " ", text)

    # 모두입찰 라벨: 마감일 2026-11-26 / 마감일 —
    m = re.search(r"마감일\s*(?:\||:|：)?\s*([^\n|]{1,24})", compact)
    if m:
        raw = m.group(1).strip()
        d = _parse_date(raw)
        if d:
            return d.isoformat()

    # 한글 제출기한/마감: 2026년 11월 30일(월) 17시
    m = re.search(
        r"(?:제출기한|접수\s*마감|입찰\s*마감|투찰\s*마감|제안서\s*제출|마감일(?:시)?|마감)\s*[:：]?\s*"
        r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"
        r"(?:\s*\([^)]*\))?\s*(?:(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?)?",
        compact,
    )
    if m:
        return _fmt_deadline(_fmt_ymd(m.group(1), m.group(2), m.group(3)), m.group(4), m.group(5))

    # 점/하이픈 + 시각: 마감 2026.11.04.(수) 18:00
    m = re.search(
        r"(?:제출기한|접수\s*마감|입찰\s*마감|투찰\s*마감|마감일(?:시)?|마감)\s*[:：]?\s*"
        r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})"
        r"(?:[.\s]*\([^)]*\))?\s*(?:(\d{1,2}):(\d{2}))?",
        compact,
    )
    if m:
        return _fmt_deadline(_fmt_ymd(m.group(1), m.group(2), m.group(3)), m.group(4), m.group(5))

    # 개찰일 대용 (마감 비공개일 때) — 날짜만 표시
    m = re.search(r"개찰일\s*(?:\||:|：)?\s*(20\d{2}[-./]\d{1,2}[-./]\d{1,2})", compact)
    if m:
        d = _parse_date(m.group(1))
        if d:
            return d.isoformat()

    return None


def normalize_deadline(value: Any) -> str:
    """표시용: '개찰 ' / '(마감)' / 시각 제거, 날짜만 남김."""
    text = str(value or "").strip()
    if not text or text in ("-", "확인 불가"):
        return "-"
    text = re.sub(r"^개찰\s*", "", text)
    text = re.sub(r"\s*\(마감\)\s*$", "", text)
    text = text.strip()
    d = _parse_date(text)
    if d:
        return d.isoformat()
    return text or "-"


def fetch_deadline_for_notice(notice_or_row: dict[str, Any]) -> str | None:
    """hit 상세 페이지에서 마감일 조회."""
    link = str(notice_or_row.get("link") or "").strip()
    board_no = notice_or_row.get("board_no")
    if board_no is None:
        m = re.search(r"boardNo=(\d+)", link)
        if m:
            board_no = m.group(1)

    try:
        if board_no is not None or "redirect-shinhan" in link or "shinhangroup.com" in link:
            if board_no is None:
                return None
            resp = requests.post(
                "https://www.shinhangroup.com/kr/pr/notice/detail",
                headers={
                    **HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "Referer": "https://www.shinhangroup.com/kr/pr/notice",
                    "Origin": "https://www.shinhangroup.com",
                },
                data={"boardNo": str(board_no), "searchText": ""},
                timeout=25,
            )
            resp.raise_for_status()
            text = BeautifulSoup(resp.text, "lxml").get_text("\n", strip=True)
            return parse_deadline_from_text(text)

        if not link.startswith("http"):
            return None

        resp = requests.get(link, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        text = BeautifulSoup(resp.text, "lxml").get_text("\n", strip=True)
        return parse_deadline_from_text(text)
    except (requests.RequestException, ValueError):
        return None


def enrich_hit_deadline(row: dict[str, Any]) -> dict[str, Any]:
    """기존 마감이 비어 있으면 상세에서 채움. 표기는 날짜만."""
    cur = normalize_deadline(row.get("deadline"))
    row["deadline"] = cur
    if cur != "-":
        return row
    found = fetch_deadline_for_notice(row)
    if found:
        row["deadline"] = normalize_deadline(found)
    return row


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
            row["deadline"] = h.get("deadline") or "-"
            row["budget"] = "-"
            row["note"] = f"조회기간 내 공개목록 총 {total}건 중 목표분야 해당 ({period_note})"
            row["list_link"] = base.get("link") or ""
            row["link"] = h.get("link") or base.get("link") or ""
            if h.get("board_no") is not None:
                row["board_no"] = h.get("board_no")
            row["hit"] = True
            enrich_hit_deadline(row)
            rows.append(row)
        return rows

    row = deepcopy(base)
    row["no"] = str(base["no"]).split("-")[0]
    row["hit"] = False
    row["list_link"] = base.get("link") or ""
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
        shinhan_board = "shinhangroup.com/kr/pr/notice" in str(base.get("link") or "")
        if shinhan_board or "신한금융" in company:
            notices = filter_period(fetch_shinhan_notices(), start, end)
            built = build_rows_for_company(base, notices, start, end)
            # 기관 목록용 기본 링크는 게시판 유지, hit 행은 상세 링크 유지
            for row in built:
                if not row.get("hit"):
                    row["link"] = "https://www.shinhangroup.com/kr/pr/notice"
            new_rows.extend(built)
        elif base.get("source") == "modoobid" or base.get("org_key") or base.get("org_keys"):
            keys = base.get("org_keys") or [base.get("org_key")]
            keys = [k for k in keys if k]
            for k in keys:
                notices.extend(filter_period(fetch_modoobid(k), start, end))
            # 중복 제목 제거 (동일 상세 URL 우선)
            seen: set[str] = set()
            uniq = []
            for n in notices:
                key = n.get("link") or n.get("title", "")
                if key in seen:
                    continue
                seen.add(key)
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
                    enrich_hit_deadline(row)
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
