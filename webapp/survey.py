"""최근 1개월 입찰공고 재조회.

수집 우선순위:
1) 기관·계열·정부 공식 게시판
2) 모두입찰 등 중계 사이트 (보조)
"""

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

# 중계·보조 수집 채널
AGGREGATOR_HOSTS = (
    "modoobid.co.kr",
    "00data.kr",
    "narais.com",
    "bidpro.co.kr",
    "sankun.com",
    "jodaln.com",
)

# 공식 게시판 (우선). url은 홈이 아니라 공고·입찰 목록으로 지정.
# prefer_g2b=True 이면 중계 상세를 나라장터 원문 링크로 승격.
OFFICIAL_BOARDS: dict[str, dict[str, Any]] = {
    "신한금융그룹·신한은행": {
        "url": "https://www.shinhangroup.com/kr/pr/notice",
        "fetcher": "shinhan",
    },
    "금융감독원": {
        "url": "https://www.fss.or.kr/fss/bbs/B0000191/list.do?menuNo=200222",
        "fetcher": "fss",
        "org_key": "금융감독원",
    },
    "금융위원회": {
        "url": "https://www.fsc.go.kr/no010101",
        "org_key": "금융위원회",
        "prefer_g2b": True,
    },
    "한국은행": {
        "url": "https://www.bok.or.kr/portal/bbs/B0000235/list.do?menuNo=200786",
        "org_key": "한국은행",
        "prefer_g2b": True,
    },
    "한국거래소": {
        "url": "https://info.krx.co.kr/board/KRX06040000T3/bbs",
        "org_key": "(주)한국거래소",
        "prefer_g2b": True,
    },
    "금융결제원": {
        "url": "https://www.kftc.or.kr/notice/bidAll",
        "org_key": "금융결제원",
        "prefer_g2b": True,
    },
    "한국예탁결제원": {
        "url": "https://www.ksd.or.kr/ko/about-ksd/ksd-news/bid-notice",
        "org_key": "한국예탁결제원",
        "prefer_g2b": True,
    },
    "예금보험공사": {
        "url": "https://www.kdic.or.kr/di/pbcr/selectPbcrNtcList.do",
        "org_key": "예금보험공사",
        "prefer_g2b": True,
    },
    "한국자산관리공사": {
        "url": "https://www.kamco.or.kr/portal/bbs/list.do?mId=0701020000&ptIdx=480",
        "org_key": "한국자산관리공사",
        "prefer_g2b": True,
    },
    "한국주택금융공사": {
        "url": "https://www.hf.go.kr/ko/sub05/sub05_06.do",
        "org_key": "한국주택금융공사",
        "prefer_g2b": True,
    },
    "신용보증기금": {
        "url": "https://www.alio.go.kr/item/itemOrganList.do?apbaId=C0091&reportFormRootNo=B1030",
        "org_key": "신용보증기금",
        "prefer_g2b": True,
    },
    "기술보증기금": {
        "url": "https://www.alio.go.kr/item/itemOrganList.do?apbaId=C0038&reportFormRootNo=B1030",
        "org_key": "기술보증기금",
        "prefer_g2b": True,
    },
    "한국해양진흥공사": {
        "url": "https://www.kobc.or.kr/ebz/kor/bbs/list.do?mId=0603000000&ptIdx=264",
        "org_key": "한국해양진흥공사",
        "fetcher": "kobc",
        "prefer_g2b": True,
    },
    "한국교직원공제회": {
        "url": "https://www.tp.or.kr",
        "org_key": "한국교직원공제회",
        "prefer_g2b": True,
    },
    "IBK기업은행": {
        "url": "https://www.ibk.co.kr/cyber/noticeListCyber.ibk?pageId=IR03010400",
        "org_key": "중소기업은행",
        "prefer_g2b": True,
    },
    "한국산업은행": {
        "url": "https://www.alio.go.kr/item/itemOrganList.do?apbaId=C0210&reportFormRootNo=B1030",
        "org_key": "한국산업은행",
        "prefer_g2b": True,
    },
    "한국수출입은행": {
        "url": "https://www.koreaexim.go.kr",
        "org_key": "한국수출입은행",
        "prefer_g2b": True,
    },
}

BID_NO_RE = re.compile(r"(R\d{2}[A-Z]{2}\d{5,})(?:-(\d{3}))?")


def is_aggregator_url(url: str | None) -> bool:
    u = (url or "").lower()
    return any(h in u for h in AGGREGATOR_HOSTS)


def g2b_notice_url(bid_no: str, bid_ord: str | None = None) -> str:
    """나라장터 입찰공고 상세 딥링크."""
    no = (bid_no or "").strip()
    ord_ = (bid_ord or "000").strip() or "000"
    return (
        "https://www.g2b.go.kr/link/PNPE027_01/single/"
        f"?bidPbancNo={no}&bidPbancOrd={ord_}"
    )


def parse_bid_no(text: str) -> tuple[str, str] | None:
    m = BID_NO_RE.search(text or "")
    if not m:
        return None
    return m.group(1), (m.group(2) or "000")


def extract_bid_no_from_page(url: str) -> tuple[str, str] | None:
    """중계 상세에서 나라장터 공고번호 추출."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    return parse_bid_no(resp.text)


def upgrade_notice_to_g2b(notice: dict[str, Any]) -> dict[str, Any]:
    """중계 링크를 나라장터 원문으로 승격. 마감은 중계에서 먼저 확보."""
    link = str(notice.get("link") or "").strip()
    if not is_aggregator_url(link):
        return notice
    if notice.get("bid_no"):
        bid = str(notice["bid_no"])
        ord_ = str(notice.get("bid_ord") or "000")
        out = {**notice, "link": g2b_notice_url(bid, ord_), "source": "g2b"}
        return out

    # 마감·공고번호는 중계 상세에서
    deadline = notice.get("deadline")
    if not deadline or deadline == "-":
        found = fetch_deadline_for_notice(notice)
        if found:
            deadline = found

    parsed = extract_bid_no_from_page(link)
    if not parsed:
        if deadline:
            return {**notice, "deadline": deadline}
        return notice

    bid, ord_ = parsed
    out = {
        **notice,
        "bid_no": bid,
        "bid_ord": ord_,
        "link": g2b_notice_url(bid, ord_),
        "source": "g2b",
        "aggregator_link": link,
    }
    if deadline:
        out["deadline"] = deadline
    return out


def upgrade_target_notices_to_g2b(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """목표분야 hit만 나라장터 원문 링크로 교체."""
    out: list[dict[str, Any]] = []
    for n in notices:
        if _is_target(str(n.get("title") or "")) and is_aggregator_url(n.get("link")):
            out.append(upgrade_notice_to_g2b(n))
        else:
            out.append(n)
    return out


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


def fetch_fss_notices() -> list[dict[str, Any]]:
    """금융감독원 공식 공개입찰 게시판."""
    list_url = "https://www.fss.or.kr/fss/bbs/B0000191/list.do?menuNo=200222"
    try:
        resp = requests.get(list_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as e:
        return [{"error": str(e), "title": "", "posted": None}]

    soup = BeautifulSoup(resp.text, "lxml")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=True)
        if not a:
            continue
        text = " ".join(tr.get_text(" ", strip=True).split())
        m_date = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
        if not m_date:
            continue
        title = " ".join((a.get_text() or "").split()).strip()
        title = re.sub(r"^\[?입찰\s*재공고\]?\s*", "", title)
        title = re.sub(r"^[\(\[]?입찰공고[\)\]]?\s*", "", title)
        title = title.strip()
        if len(title) < 4:
            continue
        href = str(a.get("href") or "").strip()
        detail = urljoin("https://www.fss.or.kr", href)
        if detail in seen:
            continue
        seen.add(detail)
        items.append({
            "title": title[:200],
            "posted": m_date.group(1),
            "link": detail,
            "source": "official",
        })
    return items


def fetch_kobc_notices() -> list[dict[str, Any]]:
    """한국해양진흥공사 공식 입찰공고 게시판."""
    list_url = "https://www.kobc.or.kr/ebz/kor/bbs/list.do?mId=0603000000&ptIdx=264"
    try:
        resp = requests.get(list_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as e:
        return [{"error": str(e), "title": "", "posted": None}]

    soup = BeautifulSoup(resp.text, "lxml")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tr in soup.find_all("tr"):
        text = " ".join(tr.get_text(" ", strip=True).split())
        m_date = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
        if not m_date:
            continue
        a = tr.find("a", href=True)
        title = " ".join(((a.get_text() if a else "") or "").split()).strip()
        if not title:
            # 번호 제거 후 제목 추정
            title = re.sub(r"^\d+\s+", "", text)
            title = re.sub(r"\s+관리자\s+20\d{2}-\d{2}-\d{2}.*$", "", title).strip()
        title = re.sub(r"^\[(?:입찰공고|사전규격|조달물자[^\]]*)\]\s*", "", title).strip()
        if len(title) < 4:
            continue
        href = str((a.get("href") if a else "") or "").strip()
        if href and href not in ("#", "javascript:;") and not href.startswith("javascript:"):
            detail = urljoin(list_url, href)
        else:
            detail = list_url
        key = f"{title}|{m_date.group(1)}"
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": title[:200],
            "posted": m_date.group(1),
            "link": detail,
            "source": "official",
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
            "source": "official",
        })
    return items


def merge_notices_prefer_official(
    official: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """공식 공고를 우선하고, 없는 제목만 보조(모두입찰)로 채움."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in official + secondary:
        if n.get("error"):
            continue
        key = _title_dedupe_key(str(n.get("title") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(n)
    return merged


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


def _title_dedupe_key(title: str) -> str:
    """재공고·재입찰 표기 제거 후 동일 사업 판별 키."""
    t = str(title or "").strip()
    t = re.sub(r"\s*[\(\[【]?\s*재공고\s*[\)\]】]?", " ", t)
    t = re.sub(r"\s*[\(\[【]?\s*재입찰\s*[\)\]】]?", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def keep_latest_notices(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """동일 사업(제목 키)은 공고일 최신 1건만 유지."""
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for n in notices:
        key = _title_dedupe_key(str(n.get("title") or ""))
        if not key:
            continue
        posted = _parse_date(str(n.get("posted") or "")) or date.min
        if key not in best:
            best[key] = n
            order.append(key)
            continue
        prev = best[key]
        prev_posted = _parse_date(str(prev.get("posted") or "")) or date.min
        if posted > prev_posted:
            best[key] = n
        elif posted == prev_posted:
            # 동일일이면 재공고/재입찰 표기가 있는 쪽 우선
            cur_t = str(n.get("title") or "")
            prev_t = str(prev.get("title") or "")
            if ("재공고" in cur_t or "재입찰" in cur_t) and not (
                "재공고" in prev_t or "재입찰" in prev_t
            ):
                best[key] = n
    return [best[k] for k in order]


def build_rows_for_company(
    base: dict[str, Any],
    notices: list[dict[str, Any]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """기간 내 공고 → 목표분야 hit 행 또는 공고 없음 행."""
    hits = keep_latest_notices(
        [n for n in notices if _is_target(n.get("title", ""))]
    )
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

        official_cfg = OFFICIAL_BOARDS.get(company) or {}
        official_url = str(official_cfg.get("url") or "").strip()
        base_link = str(base.get("link") or "").strip()
        if not official_url and base_link and not is_aggregator_url(base_link):
            official_url = base_link

        org_keys = base.get("org_keys") or [base.get("org_key")]
        org_keys = [k for k in org_keys if k]
        if official_cfg.get("org_key") and official_cfg["org_key"] not in org_keys:
            org_keys.append(official_cfg["org_key"])

        official_notices: list[dict[str, Any]] = []
        secondary_notices: list[dict[str, Any]] = []
        channels: list[str] = []

        # 1) 공식·계열·정부 게시판 우선
        fetcher = official_cfg.get("fetcher")
        prefer_g2b = bool(official_cfg.get("prefer_g2b"))
        if fetcher == "shinhan" or "신한금융" in company or "shinhangroup.com/kr/pr/notice" in base_link:
            official_notices = filter_period(fetch_shinhan_notices(), start, end)
            official_url = official_url or "https://www.shinhangroup.com/kr/pr/notice"
            channels.append("공식(신한)")
        elif fetcher == "fss":
            official_notices = filter_period(fetch_fss_notices(), start, end)
            channels.append("공식(금감원)")
        elif fetcher == "kobc":
            official_notices = filter_period(fetch_kobc_notices(), start, end)
            channels.append("공식(해양진흥)")
        elif base.get("source") == "board" and not is_aggregator_url(base_link):
            channels.append("공식게시판")

        # 2) 모두입찰 등 중계는 후순위
        #    - 순수 공식게시판(은행·증권 등 수동 유지)은 중계로 덮지 않음
        #    - 공식 fetcher hit가 있으면 중계 생략, 없을 때만 보조 수집
        official_has_target = any(
            _is_target(str(n.get("title") or "")) for n in official_notices
        )
        pure_board = (
            base.get("source") == "board"
            and not is_aggregator_url(base_link)
            and not fetcher
        )
        use_secondary = bool(org_keys) and not pure_board and not official_has_target

        if use_secondary:
            for k in org_keys:
                secondary_notices.extend(filter_period(fetch_modoobid(k), start, end))
            if secondary_notices:
                channels.append("모두입찰(보조)")
                # 공공기관: 중계 hit → 나라장터 원문 링크로 승격
                if prefer_g2b:
                    secondary_notices = upgrade_target_notices_to_g2b(secondary_notices)
                    if any(n.get("source") == "g2b" for n in secondary_notices):
                        channels.append("나라장터(원문)")

        if official_notices or secondary_notices:
            notices = merge_notices_prefer_official(official_notices, secondary_notices)
            built = build_rows_for_company(base, notices, start, end)
            list_link = official_url or (
                f"https://www.modoobid.co.kr/bid/org/{quote(org_keys[0])}" if org_keys else base_link
            )
            channel_note = " · ".join(channels) if channels else "수집"
            for row in built:
                row["list_link"] = list_link
                if not row.get("hit"):
                    row["link"] = list_link
                    if is_aggregator_url(row.get("link")) and official_url:
                        row["link"] = official_url
                # hit가 아직 중계면 한 번 더 나라장터 승격 시도
                if row.get("hit") and prefer_g2b and is_aggregator_url(row.get("link")):
                    upgraded = upgrade_notice_to_g2b(row)
                    row["link"] = upgraded.get("link") or row["link"]
                    if upgraded.get("deadline") and upgraded["deadline"] != "-":
                        row["deadline"] = normalize_deadline(upgraded["deadline"])
                    if upgraded.get("bid_no"):
                        row["bid_no"] = upgraded["bid_no"]
                        row["bid_ord"] = upgraded.get("bid_ord") or "000"
                row["note"] = (row.get("note") or "") + f" · 수집우선: {channel_note}"
                if official_url:
                    row["official_link"] = official_url
            new_rows.extend(built)
            continue

        # 공식 자동수집 미연동 게시판: 기존 집계 유지 (중계로 대체하지 않음)
        row = deepcopy(base)
        if official_url:
            row["list_link"] = official_url
            row["official_link"] = official_url
            if not row.get("hit"):
                row["link"] = official_url
        # 기존 hit가 중계·공공일감이면 나라장터 원문으로 승격
        if row.get("hit") and is_aggregator_url(row.get("link")):
            upgraded = upgrade_notice_to_g2b(row)
            row["link"] = upgraded.get("link") or row["link"]
            if upgraded.get("deadline") and upgraded["deadline"] != "-":
                row["deadline"] = normalize_deadline(upgraded["deadline"])
            if upgraded.get("bid_no"):
                row["bid_no"] = upgraded["bid_no"]
                row["bid_ord"] = upgraded.get("bid_ord") or "000"
        if row.get("hit"):
            ad = _parse_date(row.get("announce_date") or "")
            if ad and not (start <= ad <= end):
                row["hit"] = False
                row["title"] = "공고 없음 (총 확인필요)"
                row["announce_date"] = "-"
                row["deadline"] = "-"
                row["budget"] = "-"
                row["note"] = (
                    f"공식 게시판 자동전수 제한. 조회기간 {start}~{end} "
                    f"(이전 hit 공고일이 기간 외)"
                )
            else:
                row["note"] = (row.get("note") or "") + f" · 조회기간 {start}~{end} · 수집우선: 공식게시판"
                enrich_hit_deadline(row)
        else:
            m = re.search(r"총\s*(\d+)건", row.get("title") or "")
            total = m.group(1) if m else "?"
            if row.get("title", "").startswith("공고 없음"):
                row["title"] = f"공고 없음 (총 {total}건)" if total != "?" else row["title"]
            row["note"] = (
                f"공식 게시판(수동전수 기준 유지). "
                f"중계사이트 미사용. 조회기간 {start}~{end}"
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
