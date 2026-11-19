# 금융권 공고 일일 배치 (`batch`)

`prompt.md` 기준 목표분야(시장리스크·ALM·K-ICS·IFRS·파생 등) 공고를 **로컬에서 하루 1회** 수집하고, GitHub Pages용 정적 문서(`docs/`)로 발행합니다.

지금은 **로컬 스케줄(2-B)** 입니다. 이후 같은 `python -m batch` 엔트리로 GitHub Actions cron(2-A)에 옮기면 됩니다.

## 준비

```powershell
cd proposal
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r batch\requirements.txt
```

`webapp`용 venv가 이미 있으면 그걸로도 실행 가능합니다 (`run.ps1`이 자동 탐지).

## 실행

```powershell
# 문서만 생성 (기존 JSON, 네트워크 없음 — 테스트용)
python -m batch --skip-fetch

# 실제 수집 후 docs/ 생성
python -m batch

# 수집 + commit + push (Pages 반영)
python -m batch --push

# PowerShell 래퍼
.\batch\run.ps1 -SkipFetch
.\batch\run.ps1 -Push
```

생성물:

| 경로 | 설명 |
|------|------|
| `batch/templates/index.html` | Vue CDN 템플릿 (UI) |
| `docs/index.html` | 템플릿 복사본 (Pages 홈) |
| `docs/data.json` | 조사 데이터 (Vue가 fetch) |
| `docs/latest.md` | 최신 보고서 |
| `docs/archive/금융권_신규프로젝트_공고현황_YYYYMMDD.md` | 일자별 아카이브 |

## GitHub Pages 연결

1. GitHub에 repo를 만들고 remote를 추가합니다.

```powershell
cd proposal
gh repo create <owner>/<name> --private --source=. --remote=origin --push
```

이미 로컬 커밋만 있다면:

```powershell
git remote add origin https://github.com/<owner>/<name>.git
git push -u origin main
```

2. GitHub → **Settings → Pages**
   - Source: **Deploy from a branch**
   - Branch: `main` (또는 기본 브랜치)
   - Folder: **`/docs`**
   - Save

3. 이후 `python -m batch --push` 하면 Pages가 갱신됩니다.  
   URL 예: `https://<owner>.github.io/<name>/`

## Windows 작업 스케줄러 (매일)

1. 작업 스케줄러 → 기본 작업 만들기
2. 트리거: 매일 오전 9:00 (원하는 시각)
3. 동작: 프로그램 시작

| 항목 | 값 |
|------|-----|
| 프로그램 | `powershell.exe` |
| 인수 | `-NoProfile -ExecutionPolicy Bypass -File "C:\...\proposal\batch\run.ps1" -Push` |
| 시작 위치 | `C:\...\proposal` |

`-Push`는 remote가 있을 때만 실제로 push합니다. remote가 없으면 커밋만 되고 안내 메시지를 남깁니다.

## 조사 범위 / 한계

- `webapp/survey.py`의 모두입찰 공개목록 + 키워드 필터를 재사용합니다.
- 예산·마감·RFP·참가요건은 원문 미확인 시 **확인 불가**로 둡니다.
- 공개목록 N 기관·홈페이지 로그인 게시판은 자동전수하지 않습니다.

## 이후: GitHub Actions (2-A)

로컬 테스트가 끝나면 `.github/workflows/daily-survey.yml`에서 동일하게:

```text
python -m batch --push
```

를 cron(`0 0 * * *` 등)으로 호출하면 됩니다. (Pages write 권한·`contents: write` 필요)
