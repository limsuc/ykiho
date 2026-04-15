import os
import time
import json
import requests
from flask import Flask, jsonify, render_template, request
from bs4 import BeautifulSoup

app = Flask(__name__)

HOSP_LIST_URL = "https://apis.data.go.kr/B551182/hospInfoServicev2/getHospBasisList"
HIRA_HOSP_DETAIL_URL = "https://www.hira.or.kr/ra/hosp/hospInfoAjax.do"
BIZNO_API_KEY = "IcSmJ3zQEcKm20SZlTBoIwdN"

# 심평원 상세 페이지에서 평문 요양기호 추출
def fetch_ykiho_from_hira(enc_ykiho):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(HIRA_HOSP_DETAIL_URL, params={"ykiho": enc_ykiho}, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        inp = soup.find("input", {"id": "ykiho"})
        return inp.get("value") if inp else None
    except:
        return None

@app.route("/")
def index():
    return render_template("index.html")

@app.get("/api/hospitals")
def api_hospitals():
    q = request.args.get("q", "").strip()
    sido = request.args.get("sido", "").strip()
    resolve_hira = request.args.get("resolveHira") == "1"

    service_key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    
    params = {
        "serviceKey": service_key,
        "pageNo": 1,
        "numOfRows": 30,
        "yadmNm": q,
        "_type": "json"
    }
    if sido: params["sidoCd"] = sido

    try:
        resp = requests.get(HOSP_LIST_URL, params=params, timeout=20)
        data = resp.json()
        items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict): items = [items]

        hospitals = []
        for it in items:
            h = {
                "yadmNm": it.get("yadmNm"),
                "addr": it.get("addr"),
                "ykiho": it.get("ykiho"),
                "yoyangNo8": None
            }
            if resolve_hira:
                h["yoyangNo8"] = fetch_ykiho_from_hira(it.get("ykiho"))
            hospitals.append(h)

        return jsonify({"hospitals": hospitals})
    except Exception as e:
        return jsonify({"error": str(e), "hospitals": []}), 500

@app.get("/api/bizno")
@app.route("/api/bizno", methods=["GET"])
def api_bizno():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "검색어가 없습니다.", "items": []}), 400

    BIZNO_API_KEY = "IcSmJ3zQEcKm20SZlTBoIwdN"
    params = {"key": BIZNO_API_KEY, "gb": 3, "q": q, "type": "json"}
    
    try:
        # 비즈노 서버가 봇(Bot)으로 인식하지 않도록 브라우저 정보 추가
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get("https://bizno.net/api/fapi", params=params, headers=headers, timeout=10)
        
        try:
            data = resp.json()
            return jsonify(data)
        except ValueError:
            # 비즈노가 JSON이 아닌 텍스트(예: "유효하지 않은 키입니다")를 보냈을 때
            return jsonify({"error": f"비즈노 거절 메시지: {resp.text[:50]}", "items": []}), 502
            
    except Exception as e:
        return jsonify({"error": f"서버 내부 에러: {str(e)}", "items": []}), 500