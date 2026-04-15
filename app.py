import json
import os
import time
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

HIRA_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

_YOYANG8_MAP: dict[str, str] | None = None
_YOYANG8_MAP_MTIME: float | None = None
YOYANG8_MAP_FILENAME = "ykiho_to_yoyang8.json"

API_NOTICE_YOYANG8 = (
    "공공데이터 getHospBasisList는 평문 요양기호를 주지 않습니다. "
    "선택 시 심평원 병원찾기와 동일한 상세 페이지 HTML에서 "
    "name=ykiho hidden input의 value를 읽어 옵니다(과도한 호출 자제). "
    "로컬 ykiho_to_yoyang8.json이 있으면 그 값이 우선합니다."
)


def fetch_plain_yoyang_from_hira_html(enc_ykiho: str) -> str | None:
    """심평원 병원 상세(hospInfoAjax.do) HTML의 hidden ykiho value(평문 요양기호) 추출."""
    if not enc_ykiho or not str(enc_ykiho).strip():
        return None
    try:
        resp = requests.get(
            HIRA_HOSP_DETAIL_URL,
            params={"ykiho": enc_ykiho},
            headers=HIRA_REQUEST_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    inp = soup.find("input", attrs={"name": "ykiho", "id": "ykiho"})
    if inp is None:
        inp = soup.find("input", id="ykiho")
    if inp is None:
        return None
    raw = inp.get("value")
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _unique_enc_ykiho_in_order(rows: list[dict[str, str | None]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        yk = row.get("ykiho")
        if not yk or yk in seen:
            continue
        seen.add(yk)
        out.append(yk)
    return out


def _batch_resolve_hira_plain(enc_list: list[str], limit: int, pause_sec: float) -> dict[str, str | None]:
    resolved: dict[str, str | None] = {}
    n = min(len(enc_list), max(0, limit))
    for i, yk in enumerate(enc_list[:n]):
        resolved[yk] = fetch_plain_yoyang_from_hira_html(yk)
        if i < n - 1 and pause_sec > 0:
            time.sleep(pause_sec)
    return resolved


def _get_yoyang8_map() -> dict[str, str]:
    """ykiho 문자열 → 평문 요양기호(예: 8자리). 로컬 JSON으로만 보강 가능."""
    global _YOYANG8_MAP, _YOYANG8_MAP_MTIME
    path = _BASE_DIR / YOYANG8_MAP_FILENAME
    if not path.is_file():
        _YOYANG8_MAP = {}
        _YOYANG8_MAP_MTIME = None
        return _YOYANG8_MAP
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _YOYANG8_MAP = {}
        _YOYANG8_MAP_MTIME = None
        return _YOYANG8_MAP
    if _YOYANG8_MAP is not None and _YOYANG8_MAP_MTIME == mtime:
        return _YOYANG8_MAP
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        _YOYANG8_MAP = {}
        _YOYANG8_MAP_MTIME = mtime
        return _YOYANG8_MAP
    if not isinstance(raw, dict):
        _YOYANG8_MAP = {}
        _YOYANG8_MAP_MTIME = mtime
        return _YOYANG8_MAP
    _YOYANG8_MAP = {
        str(k).strip(): str(v).strip()
        for k, v in raw.items()
        if k is not None
        and v is not None
        and str(k).strip()
        and str(v).strip()
        and not str(k).lstrip().startswith("_")
    }
    _YOYANG8_MAP_MTIME = mtime
    return _YOYANG8_MAP


def _merge_yoyang8_column(
    rows: list[dict[str, str | None]],
    ymap: dict[str, str],
    hira_plain: dict[str, str | None] | None,
) -> list[dict[str, str | None]]:
    out: list[dict[str, str | None]] = []
    for row in rows:
        d = dict(row)
        yk = d.get("ykiho")
        if yk and yk in ymap:
            d["yoyangNo8"] = ymap[yk]
        elif yk and hira_plain is not None and yk in hira_plain:
            d["yoyangNo8"] = hira_plain[yk]
        else:
            d["yoyangNo8"] = None
        out.append(d)
    return out


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


def _str_field(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _pick_first(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in item and item[k] is not None:
            return item[k]
    return None


def _extract_hospital_row(item: dict[str, Any]) -> dict[str, str | None]:
    """Map API item dict to UI fields. ykiho는 공공데이터 JSON 표준 키 `ykiho` 외 변형 대비."""
    ykiho = _pick_first(item, ("ykiho", "YKIHO", "ykihO"))
    yadm_nm = _pick_first(item, ("yadmNm", "YADM_NM", "yadm_nm"))
    addr = _pick_first(item, ("addr", "ADDR", "address"))
    return {
        "ykiho": _str_field(ykiho),
        "yadmNm": _str_field(yadm_nm),
        "addr": _str_field(addr),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/hospitals")
def api_hospitals():
    q = (request.args.get("q") or "").strip()
    sido_code = (request.args.get("sido") or "").strip() # 지역 코드 변수 추가

    if not q:
        return jsonify({"error": "검색어(q)를 입력해 주세요.", "hospitals": []}), 400

    service_key = (
        os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip().lstrip("\ufeff").strip('"').strip("'")
    )
    if not service_key:
        return jsonify(
            {
                "error": "서버에 DATA_GO_KR_SERVICE_KEY 환경 변수가 설정되어 있지 않습니다.",
                "hospitals": [],
            }
        ), 500

    params = {
        "serviceKey": service_key,
        "pageNo": 1,
        "numOfRows": 50,
        "yadmNm": q,
        "_type": "json",
    }

    # 지역 코드가 선택되었다면 파라미터에 추가
    if sido_code:
        params["sidoCd"] = sido_code

    try:
        resp = requests.get(HOSP_LIST_URL, params=params, timeout=30)
    except requests.RequestException as e:
        return jsonify({"error": f"외부 API 호출 실패: {e!s}", "hospitals": []}), 502

    if resp.status_code == 401:
        return jsonify(
            {
                "error": "공공데이터 API 인증 실패(401). .env의 DATA_GO_KR_SERVICE_KEY와 "
                "「건강보험심사평가원 병원정보서비스」 활용신청 여부를 확인해 주세요.",
                "hospitals": [],
            }
        ), 502

    try:
        data = resp.json()
    except ValueError:
        snippet = (resp.text or "")[:400].strip()
        hint = (
            " 응답이 Unauthorized이면 인증키가 잘못되었거나 만료된 경우가 많습니다."
            if "nauthorized" in snippet
            else ""
        )
        return jsonify(
            {
                "error": f"외부 API 응답을 JSON으로 읽을 수 없습니다.{hint} (HTTP {resp.status_code}) {snippet!r}",
                "hospitals": [],
            }
        ), 502

    header = (data.get("response") or {}).get("header") or {}
    result_code = str(header.get("resultCode", "")).strip()
    if result_code and result_code != "00":
        msg = header.get("resultMsg", "알 수 없는 오류")
        return jsonify(
            {"error": f"공공데이터 API 오류 ({result_code}): {msg}", "hospitals": []}
        ), 502

    body = (data.get("response") or {}).get("body") or {}
    items_block = body.get("items")
    raw_items = _normalize_items(items_block)
    base_rows = [_extract_hospital_row(it) for it in raw_items]

    resolve_flag = request.args.get("resolveHira", "").strip().lower()
    resolve_hira = resolve_flag in ("1", "true", "yes", "on")
    try:
        resolve_limit = int(request.args.get("resolveLimit", "25"))
    except ValueError:
        resolve_limit = 25
    resolve_limit = max(0, min(resolve_limit, 50))

    hira_plain: dict[str, str | None] | None = None
    hira_attempted = 0
    hira_ok = 0
    if resolve_hira and base_rows and resolve_limit > 0:
        unique_yk = _unique_enc_ykiho_in_order(base_rows)
        if unique_yk:
            hira_attempted = min(len(unique_yk), resolve_limit)
            hira_plain = _batch_resolve_hira_plain(unique_yk, resolve_limit, 0.2)
            fetched = unique_yk[:hira_attempted]
            hira_ok = sum(1 for yk in fetched if hira_plain.get(yk))

    ymap = _get_yoyang8_map()
    map_path = _BASE_DIR / YOYANG8_MAP_FILENAME
    hospitals = _merge_yoyang8_column(base_rows, ymap, hira_plain)

    return jsonify(
        {
            "hospitals": hospitals,
            "totalCount": body.get("totalCount"),
            "pageNo": body.get("pageNo"),
            "numOfRows": body.get("numOfRows"),
            "noticeYoyang8": API_NOTICE_YOYANG8,
            "yoyang8MapFile": YOYANG8_MAP_FILENAME,
            "yoyang8MapLoaded": map_path.is_file(),
            "yoyang8MapEntryCount": len(ymap),
            "hiraResolveEnabled": resolve_hira,
            "hiraResolveLimit": resolve_limit,
            "hiraResolveAttempted": hira_attempted,
            "hiraResolveOk": hira_ok,
        }
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)