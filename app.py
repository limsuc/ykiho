import json
import os
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR / ".env")

app = Flask(__name__)

HOSP_LIST_URL = "https://apis.data.go.kr/B551182/hospInfoServicev2/getHospBasisList"
HIRA_HOSP_DETAIL_URL = "https://www.hira.or.kr/ra/hosp/hospInfoAjax.do"
BIZNO_API_KEY = "IcSmJ3zQEcKm20SZlTBoIwdN"

HIRA_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

# 심평원 상세 페이지 크롤링 함수
def fetch_plain_yoyang_from_hira_html(enc_ykiho: str) -> str | None:
    if not enc_ykiho or not str(enc_ykiho).strip():
        return None
    try:
        resp = requests.get(HIRA_HOSP_DETAIL_URL, params={"ykiho": enc_ykiho}, headers=HIRA_REQUEST_HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        inp = soup.find("input", attrs={"id": "ykiho"})
        if inp:
            return str(inp.get("value")).strip() or None
    except:
        pass
    return None

# 공공데이터 API 에러 방어용 파싱 함수
def _normalize_items(items_block: Any) -> list[dict[str, Any]]:
    if items_block is None or items_block == "":
        return []
    if isinstance(items_block, dict):
        item = items_block.get("item")
    else:
        item = None
    if item is None:
        return []
    if isinstance(item, list):
        return [x for x in item if isinstance(x, dict)]
    if isinstance(item, dict):
        return [item]
    return []

def _extract_hospital_row(item: dict[str, Any]) -> dict[str, str | None]:
    ykiho = item.get("ykiho")
    yadm_nm = item.get("yadmNm")
    addr = item.get("addr")
    return {
        "ykiho": str(ykiho).strip() if ykiho else None,
        "yadmNm": str(yadm_nm).strip() if yadm_nm else None,
        "addr": str(addr).strip() if addr else None,
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/hospitals", methods=["GET"])
def api_hospitals():
    q = request.args.get("q", "").strip()
    sido_code = request.args.get("sido", "").strip()
    
    if not q:
        return jsonify({"error": "검색어(q)를 입력해 주세요.", "hospitals": []}), 400

    service_key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip().lstrip("\ufeff").strip('"').strip("'")
    
    params = {
        "serviceKey": service_key,
        "pageNo": 1,
        "numOfRows": 50,
        "yadmNm": q,
        "_type": "json",
    }
    if sido_code:
        params["sidoCd"] = sido_code

    try:
        resp = requests.get(HOSP_LIST_URL, params=params, timeout=30)
        data = resp.json()
    except Exception as e:
        return jsonify({"error": f"심평원 API 에러: {str(e)}", "hospitals": []}), 502

    body = (data.get("response") or {}).get("body") or {}
    items_block = body.get("items")
    raw_items = _normalize_items(items_block)
    hospitals = [_extract_hospital_row(it) for it in raw_items]

    # 요양기호 크롤링 옵션
    resolve_hira = request.args.get("resolveHira", "0").strip() == "1"
    
    for h in hospitals:
        if resolve_hira and h.get("ykiho"):
            h["yoyangNo8"] = fetch_plain_yoyang_from_hira_html(h["ykiho"])
        else:
            h["yoyangNo8"] = None

    return jsonify({"hospitals": hospitals, "totalCount": body.get("totalCount")})

@app.route("/api/bizno", methods=["GET"])
def api_bizno():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "검색어가 없습니다.", "items": []}), 400

    params = {"key": BIZNO_API_KEY, "gb": 3, "q": q, "type": "json"}
    try:
        # 비즈노 로봇 차단 방어
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get("https://bizno.net/api/fapi", params=params, headers=headers, timeout=10)
        data = resp.json()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": f"비즈노 서버 에러: {str(e)}", "items": []}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)