"""
kiwoom_sector_watcher.py
-------------------------------------------------------------
키움 REST API로 1분마다 테마(업종) 랭킹 + 구성종목 시세 + 거래대금 상위를 가져와서
sector-monitor-live.html이 읽는 data.json을 갱신하는 로컬 스크립트.

✅ ka90001 (테마그룹별요청), ka90002 (테마구성종목요청),
   ka10032 (거래대금상위요청) 모두 openapi.kiwoom.com 공식 문서 스크린샷으로
   필드를 확정했습니다. URL, 헤더, 요청/응답 필드 모두 문서 그대로입니다.

⚠️ ka90003 (프로그램순매수상위50요청) — URL(/api/dostk/stkinfo)과 요청 파라미터
   (trde_upper_tp, amt_qty_tp, mrkt_tp, stex_tp)는 공식 문서로 확정했지만,
   문서 사이트의 Response 예시가 이 TR에서는 계속 엉뚱한 데이터(시장 전체
   프로그램매매 추이)를 보여주고 있어서 실제 응답 필드명은 아직 못 정했습니다.
   그래서 fetch_program_buy_top()은 응답에서 "stk_cd가 들어있는 리스트"를
   자동으로 찾아내는 방어적인 방식으로 작성했습니다. 실행 로그에
   "ka90003 응답 구조 확인 필요"가 뜨면 그때 출력되는 키 목록을 알려주세요.

참고
  - ka90002 응답에는 "거래대금" 필드가 없어서, 현재가 × 누적거래량으로
    근사치를 계산해 표시합니다.
  - ka10032의 trde_prica는 "백만원" 단위라서 100으로 나눠 "억원"으로 변환합니다.
  - ETF/ETN 제외는 공식 필드가 아니라 종목명 키워드 기반 추정입니다
    (KODEX/TIGER/ETN 등). 100% 정확하지 않을 수 있어요.
  - 거래대금 상위 리스트의 각 항목에는 실제 순위(1~20)가 rank 필드로 들어갑니다.

사용법
  1) pip install requests python-dotenv
  2) 같은 폴더에 .env 파일:
       KIWOOM_APPKEY=발급받은_앱키
       KIWOOM_SECRETKEY=발급받은_시크릿키
       KIWOOM_ENV=real   # 모의투자면 mock
  3) python kiwoom_sector_watcher.py   (계속 실행 상태로 둠)
  4) 같은 폴더에서: python -m http.server 8000
  5) 브라우저: http://localhost:8000/sector-monitor-live.html
-------------------------------------------------------------
"""
import os
import json
import time
import datetime
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

APPKEY = os.environ.get("KIWOOM_APPKEY", "")
SECRETKEY = os.environ.get("KIWOOM_SECRETKEY", "")
ENV = os.environ.get("KIWOOM_ENV", "real")  # real | mock

BASE_URL = "https://mockapi.kiwoom.com" if ENV == "mock" else "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
THEME_PATH = "/api/dostk/thme"     # ka90001 / ka90002 공통 URL (문서 확인됨)
RANK_PATH = "/api/dostk/rkinfo"    # ka10032 거래대금상위요청 URL (문서 확인됨)
PROGRAM_PATH = "/api/dostk/stkinfo"  # ka90003 프로그램순매수상위50요청 URL (문서 확인됨)

# ka90001 요청 파라미터 (필요시 조정)
DATE_TP = os.environ.get("KIWOOM_DATE_TP", "10")          # n일전 (1~99), 기간수익률 계산 기준
FLU_PL_AMT_TP = os.environ.get("KIWOOM_FLU_TP", "3")      # 1상위기간수익률 2하위기간수익률 3상위등락률 4하위등락률
STEX_TP = os.environ.get("KIWOOM_STEX_TP", "3")           # 1:KRX 2:NXT 3:통합

# 거래대금 상위 하이라이트 기준
TRADE_VALUE_MIN_EOK = float(os.environ.get("KIWOOM_TRADE_MIN_EOK", "300"))  # 300억 이상
TRADE_VALUE_TOP_N = int(os.environ.get("KIWOOM_TRADE_TOP_N", "20"))

# 종목명 기반 ETF/ETN 제외 휴리스틱 (공식 종목유형 필드가 없어 이름으로만 추정)
ETF_ETN_HINTS = [
    "ETN", "KODEX", "TIGER", "ACE", "SOL", "KBSTAR", "HANARO", "KINDEX",
    "ARIRANG", "TIMEFOLIO", "KOSEF", "MASTER", "WOORI", "FOCUS", "PLUS",
    "히어로즈", "마이다스",
]


def is_etf_like(name):
    if not name:
        return False
    upper = name.upper()
    return any(h.upper() in upper for h in ETF_ETN_HINTS)

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
POLL_SECONDS = 60
TOP_N_SECTORS = 8
TOP_N_STOCKS_PER_SECTOR = 4

_token_cache = {"token": None, "expires_dt": None}


def get_token():
    """접근토큰발급: POST /oauth2/token (공식 문서 확인됨)."""
    now = datetime.datetime.now()
    if _token_cache["token"] and _token_cache["expires_dt"] and now < _token_cache["expires_dt"]:
        return _token_cache["token"]

    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/json;charset=UTF-8"},
        json={"grant_type": "client_credentials", "appkey": APPKEY, "secretkey": SECRETKEY},
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("return_code") not in (0, None):
        raise RuntimeError(f"토큰 발급 실패: {body}")

    token = body["token"]
    expires_dt = datetime.datetime.strptime(body["expires_dt"], "%Y%m%d%H%M%S")
    _token_cache["token"] = token
    _token_cache["expires_dt"] = expires_dt - datetime.timedelta(minutes=5)
    return token


def call_tr(path, api_id, body, cont_yn="N", next_key=""):
    """공통 TR 호출. 헤더 구조는 ka90001 문서 기준(다른 TR도 동일 패턴).
    반환: (응답 body, 응답 헤더의 cont-yn, 응답 헤더의 next-key) — 연속조회에 사용."""
    token = get_token()
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "cont-yn": cont_yn,
        "next-key": next_key,
        "api-id": api_id,
    }
    resp = requests.post(f"{BASE_URL}{path}", headers=headers, json=body, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("return_code") != 0:
        raise RuntimeError(f"{api_id} 호출 실패: {data.get('return_msg')}")
    resp_cont_yn = resp.headers.get("cont-yn", "N")
    resp_next_key = resp.headers.get("next-key", "")
    return data, resp_cont_yn, resp_next_key


def parse_number(s):
    if s is None:
        return 0.0
    s = str(s).replace(",", "").replace("%", "").strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def fetch_theme_list():
    """ka90001 테마그룹별요청. 문서 확인된 필드 그대로 매핑."""
    data, _, _ = call_tr(THEME_PATH, "ka90001", {
        "qry_tp": "0",             # 0:전체검색, 2:종목검색
        "stk_cd": "",
        "date_tp": DATE_TP,        # n일전 (1~99)
        "thema_nm": "",            # 삭제 예정 필드, 빈 값
        "flu_pl_amt_tp": FLU_PL_AMT_TP,
        "stex_tp": STEX_TP,
    })
    items = data.get("thema_grp", [])
    sectors = []
    for it in items:
        stk_num = int(parse_number(it.get("stk_num")))
        rising = int(parse_number(it.get("rising_stk_num")))
        fall = int(parse_number(it.get("fall_stk_num")))
        main_stocks = [s.strip() for s in (it.get("main_stk") or "").split(",") if s.strip()]
        sectors.append({
            "code": it.get("thema_grp_cd", ""),
            "name": it.get("thema_nm", ""),
            "avgPct": parse_number(it.get("flu_rt")),         # 등락율 (%)
            "periodPct": parse_number(it.get("dt_prft_rt")),  # 기간수익률 (%)
            "stockCount": stk_num,
            "risingCount": rising,
            "fallCount": fall,
            "flatCount": max(stk_num - rising - fall, 0),
            "mainStocks": main_stocks,   # 이름만 있음 (가격/등락률 없음, ka90002 필요)
        })
    sectors.sort(key=lambda x: x["avgPct"], reverse=True)
    return sectors


def fetch_theme_stocks(theme_code):
    """
    ka90002 테마구성종목요청 (공식 문서 확인 완료).
    요청 Body: date_tp(선택), thema_grp_cd(필수, ka90001의 thema_grp_cd 값), stex_tp(필수)
    응답 Body: flu_rt, dt_prft_rt(테마 전체), thema_comp_stk: [
        stk_cd, stk_nm, cur_prc, flu_sig, pred_pre, flu_rt,
        acc_trde_qty, sel_bid, sel_req, buy_bid, buy_req, dt_prft_rt_n
    ]
    반환: [{name, code, price, chgAmt, chgPct, amount}, ...] (등락률 내림차순)
    """
    data, _, _ = call_tr(THEME_PATH, "ka90002", {
        "date_tp": "",
        "thema_grp_cd": theme_code,
        "stex_tp": STEX_TP,
    })
    items = data.get("thema_comp_stk", [])
    stocks = []
    for it in items:
        price = parse_number(it.get("cur_prc"))
        qty = parse_number(it.get("acc_trde_qty"))
        # ka90002에는 거래대금(원) 필드가 없어 현재가 x 누적거래량으로 근사치만 계산합니다.
        # (일중 체결가가 계속 바뀌므로 실제 거래대금과는 다소 차이가 있을 수 있음)
        amount_eok = round(price * qty / 1e8, 1) if price and qty else 0
        stocks.append({
            "name": it.get("stk_nm", ""),
            "code": it.get("stk_cd", ""),
            "price": price,
            "chgAmt": parse_number(it.get("pred_pre")),
            "chgPct": parse_number(it.get("flu_rt")),
            "amount": amount_eok,
        })
    stocks.sort(key=lambda x: x["chgPct"], reverse=True)
    return stocks


def _finalize_ranked(result):
    """거래대금 내림차순 정렬 + 상위 N개 자르기 + rank(1~N) 필드 부여."""
    result.sort(key=lambda x: x["amount"], reverse=True)
    result = result[:TRADE_VALUE_TOP_N]
    for i, item in enumerate(result):
        item["rank"] = i + 1
    return result


def fetch_trade_value_top():
    """
    ka10032 거래대금상위요청 (공식 문서 확인 완료, URL: /api/dostk/rkinfo).
    문서 예시 요청 그대로 사용: mrkt_tp="001", mang_stk_incls="1", stex_tp="3"
    응답: trde_prica_upper: [stk_cd, stk_nm, cur_prc, flu_rt, trde_prica(백만원 단위), ...]

    응답이 이미 거래대금 내림차순으로 정렬돼서 오므로, ETF/ETN을 걸러내다 보면
    한 페이지(보통 상위 몇십 개)만으로는 "300억 이상 + ETF/ETN 제외" 조건을 만족하는
    종목이 20개가 안 모일 수 있습니다. 그래서 응답 헤더의 cont-yn이 "Y"인 동안
    next-key로 다음 페이지를 계속 조회해서 20개를 채웁니다.

    반환: [{code, name, amount(억원), rank(1~20)}, ...]
    """
    result = []
    seen_codes = set()
    cont_yn, next_key = "N", ""
    max_pages = 10  # 무한 루프 방지용 안전장치

    for _ in range(max_pages):
        data, resp_cont_yn, resp_next_key = call_tr(RANK_PATH, "ka10032", {
            "mrkt_tp": "001",
            "mang_stk_incls": "1",
            "stex_tp": STEX_TP,
        }, cont_yn=cont_yn, next_key=next_key)

        items = data.get("trde_prica_upper", [])
        for it in items:
            code = it.get("stk_cd", "")
            name = it.get("stk_nm", "")
            if code in seen_codes:
                continue
            if is_etf_like(name):
                continue  # ETF/ETN 제외

            amount_eok = round(parse_number(it.get("trde_prica")) / 100, 1)  # 백만원 -> 억원
            if amount_eok < TRADE_VALUE_MIN_EOK:
                # 이미 거래대금 내림차순 정렬이라, 여기서부터는 뒤에 나올 항목도
                # 전부 기준 미만이므로 더 조회할 필요 없이 바로 종료합니다.
                return _finalize_ranked(result)

            seen_codes.add(code)
            result.append({"code": code, "name": name, "amount": amount_eok})
            if len(result) >= TRADE_VALUE_TOP_N:
                return _finalize_ranked(result)

        if resp_cont_yn != "Y" or not resp_next_key:
            break  # 더 이상 다음 페이지가 없음
        cont_yn, next_key = "Y", resp_next_key
        time.sleep(0.25)  # 초당 호출 제한(국내주식 초당 5회) 보호

    return _finalize_ranked(result)


def _find_stock_list(data):
    """
    ka90003 응답에서 종목 리스트로 보이는 필드를 자동으로 찾는다.
    (문서 사이트의 Response 예시가 이 TR만 계속 엉뚱한 값을 보여주고 있어서,
    정확한 키 이름 대신 '리스트 안에 stk_cd가 있는 dict들'을 찾는 방식으로 방어.)
    """
    # 1) 이름으로 추정되는 후보 키 먼저 시도
    candidate_keys = [
        "prm_netprps_upper", "prm_trde_upper", "prm_buy_upper",
        "prog_netprps_upper", "output", "output1",
    ]
    for k in candidate_keys:
        v = data.get(k)
        if isinstance(v, list) and v and isinstance(v[0], dict) and "stk_cd" in v[0]:
            return v
    # 2) 후보에 없으면, 응답 전체를 훑어서 stk_cd를 가진 리스트를 찾음
    for k, v in data.items():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "stk_cd" in v[0]:
            return v
    return None


def fetch_program_buy_top():
    """
    ka90003 프로그램순매수상위50요청 (URL/요청 파라미터는 공식 문서로 확정,
    응답 필드명은 문서 예시가 부정확해서 방어적으로 탐색).

    요청: trde_upper_tp(1:순매도상위,2:순매수상위) amt_qty_tp(1:금액,2:수량)
          mrkt_tp(P00101:코스피,P10102:코스닥) stex_tp(1:KRX,2:NXT,3:통합)
    -> 코스피/코스닥 둘 다 조회해서 합친 뒤, 금액 기준 상위 20개만 반환.

    반환: [{code, name, amount, rank(1~20)}, ...]
    """
    result = []
    seen_codes = set()

    for mrkt_tp in ("P00101", "P10102"):  # 코스피, 코스닥
        try:
            data, _, _ = call_tr(PROGRAM_PATH, "ka90003", {
                "trde_upper_tp": "2",   # 순매수상위
                "amt_qty_tp": "1",      # 금액 기준
                "mrkt_tp": mrkt_tp,
                "stex_tp": "1",
            })
        except Exception as e:
            print(f"[watcher] ka90003({mrkt_tp}) 호출 실패: {e}")
            continue

        items = _find_stock_list(data)
        if items is None:
            print(f"[watcher] ka90003 응답 구조 확인 필요 — 받은 키: {list(data.keys())}")
            continue

        for it in items:
            code = it.get("stk_cd", "")
            name = it.get("stk_nm", "")
            if not code or code in seen_codes:
                continue
            if is_etf_like(name):
                continue
            # 순매수금액으로 보이는 필드를 이름 후보들에서 찾음 (단위 불확실 -> 그대로 사용)
            amount = parse_number(
                it.get("netprps_amt") or it.get("prm_netprps_amt") or
                it.get("netprps") or it.get("amt") or 0
            )
            seen_codes.add(code)
            result.append({"code": code, "name": name, "amount": amount})

    result.sort(key=lambda x: x["amount"], reverse=True)
    result = result[:TRADE_VALUE_TOP_N]
    for i, item in enumerate(result):
        item["rank"] = i + 1
    return result


def build_snapshot():
    sectors_raw = fetch_theme_list()[:TOP_N_SECTORS]
    now_str = datetime.datetime.now().strftime("%H:%M")
    sectors = []
    for sec in sectors_raw:
        try:
            stocks = fetch_theme_stocks(sec["code"])[:TOP_N_STOCKS_PER_SECTOR]
        except Exception as e:
            print(f"[watcher] {sec['name']} 종목 조회 실패, 이름만 표시: {e}")
            stocks = []
        if not stocks:
            stocks = [{"name": n, "price": 0, "chgPct": None, "amount": 0}
                      for n in sec["mainStocks"][:TOP_N_STOCKS_PER_SECTOR]]
        for s in stocks:
            s["time"] = now_str
        sectors.append({
            "name": sec["name"],
            "avgPct": sec["avgPct"],
            "periodPct": sec["periodPct"],
            "risingCount": sec["risingCount"],
            "fallCount": sec["fallCount"],
            "flatCount": sec["flatCount"],
            "stocks": stocks,
        })

    try:
        trade_value_top = fetch_trade_value_top()
    except Exception as e:
        print(f"[watcher] 거래대금상위(ka10032) 조회 실패: {e}")
        trade_value_top = []

    try:
        program_buy_top = fetch_program_buy_top()
    except Exception as e:
        print(f"[watcher] 프로그램순매수상위(ka90003) 조회 실패: {e}")
        program_buy_top = []

    return {
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sectors": sectors,
        "trade_value_top": trade_value_top,
        "program_buy_top": program_buy_top,
    }


def main():
    if not APPKEY or not SECRETKEY:
        raise SystemExit("KIWOOM_APPKEY / KIWOOM_SECRETKEY 환경변수(.env)를 설정하세요.")

    print(f"[watcher] {ENV} 환경, {POLL_SECONDS}초 간격으로 data.json 갱신 시작")
    while True:
        try:
            snapshot = build_snapshot()
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            print(f"[watcher] {snapshot['updated_at']} 갱신 완료 "
                  f"({len(snapshot['sectors'])}개 테마)")
        except Exception as e:
            print(f"[watcher] 오류: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()

