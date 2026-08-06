"""
CGV IMAX 예매 오픈 감지 봇 (devtools 캡처 불필요 버전)
--------------------------------------------------------
특정 상영관(극장 x 관 종류)에서 상영 중인 "모든 영화" 목록을 CGV 예매 API로 조회하고,
그 목록에 관심 영화가 "새로 등장"하면(=예매가 열리면) Dooray Incoming Webhook으로 알림을 보낸다.

기존 방식(브라우저 개발자도구로 영화별 요청 JSON을 매번 캡처)과 달리, 이 스크립트는
CGV 예매 API 요청 필드 중 REQSITE / ISNormal / ScreenRatingCd(관 종류) / 기타 옵션 필드가
영화와 무관하게 고정된(=재사용 가능한) 값이라는 점을 이용한다. 즉 "이 영화의 예매를 조회"가
아니라 "이 상영관에서 상영 중인 모든 영화 목록을 조회"하는 요청을 보내고, 그 목록에 관심
영화 이름이 새로 나타나는지만 감시한다. 그러면 영화가 바뀌어도(=매번 devtools를 다시 켤
필요 없이) 영화 이름(MOVIE_NAME)만 바꿔서 재사용할 수 있다.

이 요청 필드 값들은 CGV 예매 오픈 알림을 공개로 운영 중인 오픈소스 프로젝트
(https://github.com/0w0i0n0g0/cgv-open-push, AGPL-3.0)에서 공개된 값을 그대로 사용했다.
CGV와 사전 협의 없이 만들어졌으며, 인터넷에 공개된 요청 방식만 사용한다는 점도 동일하다.

필요 환경변수 (GitHub Actions Secrets/Variables로 주입):
  DOORAY_WEBHOOK_URL : Dooray Incoming Webhook URL (필수, Secret)
  MOVIE_NAME         : 감지할 영화 이름에 포함된 문자열 (필수, Variable). 예: "듄", "명탐정코난"
  THEATER            : 아래 THEATER_CODES에 있는 극장 키. 기본값 YONGSAN
  HALL_TYPE          : IMAX / 4DX / SCREENX 중 하나. 기본값 IMAX
  CUSTOM_THEATER_CD  : THEATER_CODES에 없는 극장을 쓰고 싶을 때, devtools로 한 번 캡처한
                       TheaterCd 값 하나만 넣으면 됨 (Secret). 설정 시 THEATER보다 우선한다.

상태 저장:
  data/state.json 에 마지막으로 확인된 "상영 중 영화 코드 목록"을 저장한다.
  GitHub Actions workflow가 실행 후 이 파일을 저장소에 커밋해야 다음 실행에서도
  "새로 나타난 영화"만 골라 알림을 보낼 수 있다.
"""

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

CGV_URL = "http://ticket.cgv.co.kr/CGV2011/RIA/CJ000.aspx/CJ_TICKET_SCHEDULE_TOTAL_PLAY_YMD"
STATE_PATH = Path("data/state.json")

REQUEST_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "Origin": "http://ticket.cgv.co.kr",
    "Referer": (
        "http://ticket.cgv.co.kr/Reservation/Reservation.aspx?MOVIE_CD=&MOVIE_CD_GROUP="
        "&PLAY_YMD=&THEATER_CD=&PLAY_NUM=&PLAY_START_TM=&AREA_CD=&SCREEN_CD=&THIRD_ITEM="
        "&SCREEN_RATING_CD="
    ),
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

# 극장과 무관하게 고정된(재사용 가능한) 값들.
# 출처: https://github.com/0w0i0n0g0/cgv-open-push (AGPL-3.0)
FIXED_FIELDS = {
    "REQSITE": "x02PG4EcdFrHKluSEQQh4A==",
    "ISNormal": "ECFppiyFz/nvSGsg7VwPQw==",   # 전체 조회
    "MovieGroupCd": "nG6tVgEQPGU2GvOIdnwTjg==",  # 빈 값 = 특정 영화로 필터링하지 않음(전체 영화)
    "MovieTypeCd": "nG6tVgEQPGU2GvOIdnwTjg==",
    "Subtitle_CD": "nG6tVgEQPGU2GvOIdnwTjg==",
    "SOUNDX_YN": "nG6tVgEQPGU2GvOIdnwTjg==",
    "Third_Attr_CD": "nG6tVgEQPGU2GvOIdnwTjg==",
    "Language": "zqWM417GS6dxQ7CIf65+iA==",
}

# 관 종류별 ScreenRatingCd (극장과 무관하게 고정)
HALL_TYPE_CODES = {
    "IMAX": "kXwoR3tnLM/+Tu0BILP3Qg==",
    "4DX": "9sxNW0kL/ZE3ioyEu1Em8w==",
    "SCREENX": "1WlMxB/T2xWstAhFsiNSfQ==",
}

# 주요 극장의 TheaterCd. 원하는 극장이 없으면 CUSTOM_THEATER_CD 환경변수로 직접 지정한다.
THEATER_CODES = {
    "YONGSAN": "LMP+XuzWskJLFG41YQ7HGA==",       # CGV 용산아이파크몰
    "YEOUIDO": "5f4GX7Z6gNcCnYik++dJcA==",        # CGV 여의도
    "CENTUM": "2jX4VAQPhAUY/gxvZBhDdQ==",         # CGV 센텀시티
    "SEOMYEON": "VCtDd13tWp85DXhl1ss+bw==",        # CGV 서면
    "YEONGDEUNGPO": "Y5qC4mHnqFvPnE5/3487AQ==",   # CGV 영등포
    "WANGSIMNI": "2ziBKjUqqpsaZ8ii0eHHyg==",       # CGV 왕십리
}


def build_payload() -> dict:
    theater_key = os.environ.get("THEATER", "YONGSAN").upper()
    custom_theater_cd = os.environ.get("CUSTOM_THEATER_CD")
    hall_type = os.environ.get("HALL_TYPE", "IMAX").upper()

    if hall_type not in HALL_TYPE_CODES:
        sys.exit(f"지원하지 않는 HALL_TYPE 입니다: {hall_type} (IMAX/4DX/SCREENX 중 선택)")

    if custom_theater_cd:
        theater_cd = custom_theater_cd
    elif theater_key in THEATER_CODES:
        theater_cd = THEATER_CODES[theater_key]
    else:
        sys.exit(
            f"THEATER_CODES에 없는 극장입니다: {theater_key}. "
            "CUSTOM_THEATER_CD 환경변수로 TheaterCd 값을 직접 지정하세요."
        )

    payload = dict(FIXED_FIELDS)
    payload["TheaterCd"] = theater_cd
    payload["ScreenRatingCd"] = HALL_TYPE_CODES[hall_type]
    return payload


def load_state() -> dict:
    if STATE_PATH.exists():
        with STATE_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    return {"movie_codes": []}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_schedule(payload: dict):
    """CGV API를 호출해 (상영 중 영화 목록, 상영일 목록)을 반환한다."""
    resp = requests.post(CGV_URL, json=payload, headers=REQUEST_HEADERS, timeout=15)
    resp.raise_for_status()

    # ASP.NET PageMethods 응답은 {"d": {"DATA": "<xml 문자열>", ...}} 형태로 감싸여 있다.
    data = json.loads(resp.content.decode("utf-8-sig"))
    xml_string = data["d"]["DATA"]
    root = ET.fromstring(xml_string)

    movies = []
    for movie in root.findall(".//Movies/CMovie"):
        name = (movie.findtext("GROUP_NM") or "").strip()
        code = (movie.findtext("GROUP_CD") or name)
        if name:
            movies.append({"code": code, "name": name})

    play_dates = [
        el.text.strip()
        for el in root.findall(".//PlayDays/CPlayDay/FORMAT_DATE")
        if el.text
    ]

    return movies, play_dates


def send_dooray(message: str) -> None:
    webhook_url = os.environ.get("DOORAY_WEBHOOK_URL")
    if not webhook_url:
        sys.exit("환경변수 DOORAY_WEBHOOK_URL 이 설정되어 있지 않습니다.")

    payload = {
        "botName": "CGV IMAX 예매 알리미",
        "botIconImage": "https://i.imgur.com/6EO3Uau.png",
        "text": message,
    }
    r = requests.post(webhook_url, json=payload, timeout=10)
    r.raise_for_status()


def main() -> None:
    target_keyword = os.environ.get("MOVIE_NAME")
    if not target_keyword:
        sys.exit("환경변수 MOVIE_NAME 이 설정되어 있지 않습니다. (감지할 영화 이름의 일부)")

    hall_type = os.environ.get("HALL_TYPE", "IMAX").upper()
    payload = build_payload()
    state = load_state()
    prev_codes = set(state.get("movie_codes", []))

    movies, play_dates = fetch_schedule(payload)
    current_codes = {m["code"] for m in movies}

    newly_appeared = [m for m in movies if m["code"] not in prev_codes]
    newly_matched = [m for m in newly_appeared if target_keyword in m["name"]]

    if newly_matched:
        names = ", ".join(dict.fromkeys(m["name"] for m in newly_matched))
        dates = "\n".join(f"- {d}" for d in play_dates) or "(상영일 정보 없음)"
        message = (
            f"\U0001F3AC [{names}] {hall_type} 예매가 새로 열렸습니다!\n"
            f"현재 조회되는 상영일:\n{dates}\n\n"
            f"지금 바로 예매하세요 \U0001F449 http://ticket.cgv.co.kr\n"
            f"(※ 상영일은 해당 상영관 전체 기준이며, 정확한 날짜는 CGV에서 직접 확인하세요.)"
        )
        send_dooray(message)
        print(f"새 영화 감지, 알림 전송 완료: {names}")
    else:
        print(f"변경 사항 없음. 현재 상영 중: {[m['name'] for m in movies]}")

    state["movie_codes"] = list(current_codes)
    save_state(state)


if __name__ == "__main__":
    main()
