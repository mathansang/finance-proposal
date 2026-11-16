(() => {
  const btn = document.getElementById("btnRefresh");
  const meta = document.getElementById("refreshMeta");
  const toast = document.getElementById("toast");
  const periodChip = document.getElementById("periodChip");
  const body = document.getElementById("resultsBody");

  let polling = null;

  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toast.classList.remove("show"), 3200);
  }

  function setBusy(busy) {
    btn.disabled = busy;
    btn.classList.toggle("spinning", busy);
    btn.querySelector("span").textContent = busy ? "조회 중…" : "갱신";
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function render(data) {
    periodChip.textContent = `${data.period_start} ~ ${data.period_end}`;
    meta.textContent = data.last_refresh
      ? `마지막 갱신 ${data.last_refresh}`
      : "저장된 조사 결과";

    const hits = data.rows.filter((r) => r.hit).length;
    const companies = new Set(data.rows.map((r) => r.company)).size;
    const y = data.rows.filter((r) => r.public_list === "Y").length;
    const n = data.rows.filter((r) => r.public_list === "N").length;
    document.getElementById("statHits").textContent = hits;
    document.getElementById("statCompanies").textContent = companies;
    document.getElementById("statY").textContent = y;
    document.getElementById("statN").textContent = n;

    body.innerHTML = data.rows
      .map((r) => {
        const cls = [
          r.hit ? "hit" : "",
          r.public_list === "N" ? "no-public" : "",
        ]
          .filter(Boolean)
          .join(" ");
        const titleCls = r.hit
          ? "title-hit"
          : !r.title
            ? "title-empty"
            : "";
        const link = r.link
          ? `<a class="link" href="${escapeHtml(r.link)}" target="_blank" rel="noopener">열기</a>`
          : "";
        return `<tr class="${cls}">
          <td class="num">${escapeHtml(r.no)}</td>
          <td class="company">${escapeHtml(r.company)}</td>
          <td><span class="badge ${(r.public_list || "").toLowerCase()}">${escapeHtml(r.public_list)}</span></td>
          <td class="${titleCls}">${escapeHtml(r.title || "")}</td>
          <td>${escapeHtml(r.announce_date || "-")}</td>
          <td>${escapeHtml(r.deadline || "-")}</td>
          <td>${escapeHtml(r.budget || "-")}</td>
          <td class="note">${escapeHtml(r.note || "")}</td>
          <td>${link}</td>
        </tr>`;
      })
      .join("");
  }

  async function fetchResults() {
    const res = await fetch("/api/results");
    if (!res.ok) throw new Error("결과 조회 실패");
    return res.json();
  }

  async function pollStatus() {
    const res = await fetch("/api/status");
    const st = await res.json();
    if (st.status === "running") {
      setBusy(true);
      meta.textContent = st.message || "조회 중…";
      return false;
    }
    if (st.status === "error") {
      setBusy(false);
      showToast(st.message || "갱신 실패");
      return true;
    }
    setBusy(false);
    const data = await fetchResults();
    render(data);
    showToast(st.message || "갱신 완료");
    return true;
  }

  async function startRefresh() {
    try {
      setBusy(true);
      const res = await fetch("/api/refresh", { method: "POST" });
      const payload = await res.json();
      if (!res.ok) {
        setBusy(false);
        showToast(payload.message || "갱신 시작 실패");
        return;
      }
      showToast(payload.message);
      if (polling) clearInterval(polling);
      polling = setInterval(async () => {
        try {
          const done = await pollStatus();
          if (done) {
            clearInterval(polling);
            polling = null;
          }
        } catch (e) {
          clearInterval(polling);
          polling = null;
          setBusy(false);
          showToast("상태 확인 실패");
        }
      }, 1500);
    } catch (e) {
      setBusy(false);
      showToast("갱신 요청 실패");
    }
  }

  btn.addEventListener("click", startRefresh);

  // 페이지 로드 시 진행 중이면 폴링 재개
  pollStatus().then((done) => {
    if (!done) {
      polling = setInterval(async () => {
        const finished = await pollStatus();
        if (finished) {
          clearInterval(polling);
          polling = null;
        }
      }, 1500);
    } else {
      setBusy(false);
    }
  }).catch(() => {});
})();
