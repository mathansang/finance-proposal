from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from survey import get_refresh_state, load_data, start_refresh_async

app = Flask(__name__)


@app.get("/")
def index():
    data = load_data()
    hits = sum(1 for r in data["rows"] if r.get("hit"))
    public_y = sum(1 for r in data["rows"] if r.get("public_list") == "Y")
    public_n = sum(1 for r in data["rows"] if r.get("public_list") == "N")
    companies = len({r["company"] for r in data["rows"]})
    return render_template(
        "index.html",
        data=data,
        stats={
            "hits": hits,
            "companies": companies,
            "public_y": public_y,
            "public_n": public_n,
            "rows": len(data["rows"]),
        },
    )


@app.get("/api/results")
def api_results():
    return jsonify(load_data())


@app.get("/api/status")
def api_status():
    data = load_data()
    state = get_refresh_state()
    return jsonify({
        "status": state.get("status") or data.get("status") or "idle",
        "message": state.get("message") or data.get("message") or "",
        "progress": state.get("progress", 0),
        "total": state.get("total", 0),
        "period_start": data.get("period_start"),
        "period_end": data.get("period_end"),
        "last_refresh": data.get("last_refresh"),
    })


@app.post("/api/refresh")
def api_refresh():
    ok = start_refresh_async()
    if not ok:
        return jsonify({"ok": False, "message": "이미 갱신 중입니다."}), 409
    return jsonify({"ok": True, "message": "최근 1개월 조회를 시작했습니다."})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
