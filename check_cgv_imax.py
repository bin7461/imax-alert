"""
CGV IMAX 예매 오픈 감지 봇
--------------------------------
특정 영화의 IMAX 예매 정보를 CGV 예매 API에서 주기적으로 조회하고,
새로운 상영일(PLAY_YMD)이 추가되면(=예매가 오픈되면) Dooray Incoming Webhook으로
알림을 보낸다.

필요 환경변수 (GitHub Actions Secrets/Variables로 주입):
  CGV_REQUEST_PAYLOAD : CGV 예매 페이지 개발자도구 Network 탭에서 복사한 요청 JSON (문자열, 한 줄)
  DOORAY_WEBHOOK_URL  : Dooray Incoming Webhook URL
  MOVIE_NAME          : (선택) 알림 메시지에 표시할 영화 이름. 기본값 "관심 영화"

상태 저장:
  data/state.json 에 마지막으로 확인한 상영일 목록을 저장한다.
  GitHub Actions workflow가 실행 후 이 파일을 저장소에 커밋해야 다음 실행에서도
  "새로 열린 날짜"만 골라 알림을 보낼 수 있다.
"""

import json
import os
import re
import sys
from pathlib import Path

import requests

CGV_URL = "http://ticket.cgv.co.kr/CGV2011/RIA/CJ000.aspx/CJ_TICKET_SCHEDULE_TOTAL_PLAY_YMD"
STATE_PATH = Path("data/state.json")

REQUEST_HEADERS = {
    "Content-Type": "application/json; charset=UTF-8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "http://ticket.cgv.co.kr/",
}


def load_payload() -> dict:
    """GitHub Secret으로 넘어온 CGV 요청 payload(JSON 문자열)를 파싱한다."""
    raw = os.environ.get("CGV_REQUEST_PAYLOAD")
    if not raw:
        sys.exit("환경변수 CGV_REQUEST_PAYLOAD 가 설정되어 있지 않습니다.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"CGV_REQUEST_PAYLOAD JSON 파싱 실패: {e}")


def load_state() -> dict:
    if STATE_PATH.exists():
        with STATE_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    return {"play_ymd": []}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_play_days(payload: dict):
    """CGV API를 호출해 상영일(PLAY_YMD)과 표시용 날짜(FORMAT_DATE) 목록을 반환한다."""
    resp = requests.post(CGV_URL, json=payload, headers=REQUEST_HEADERS, timeout=15)
    resp.raise_for_status()

    body = resp.text
    # ASP.NET PageMethods는 보통 {"d": "<xml 문자열>"} 형태로 응답을 감싼다.
    try:
        data = resp.json()
        if isinstance(data, dict) and "d" in data:
            body = data["d"]
    except ValueError:
        pass

    play_ymd = list(dict.fromkeys(re.findall(r"<PLAY_YMD>(\d+)</PLAY_YMD>", body)))
    format_date = list(dict.fromkeys(re.findall(r"<FORMAT_DATE>([^<]+)</FORMAT_DATE>", body)))
    return play_ymd, format_date


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
    movie_name = os.environ.get("MOVIE_NAME", "관심 영화")
    payload = load_payload()
    state = load_state()
    prev_days = set(state.get("play_ymd", []))

    play_ymd, format_date = fetch_play_days(payload)
    new_days = [d for d in play_ymd if d not in prev_days]

    if new_days:
        pretty = "\n".join(f"- {d}" for d in format_date) or "\n".join(f"- {d}" for d in new_days)
        message = (
            f"\U0001F3AC [{movie_name}] IMAX 예매가 새로 열렸습니다!\n"
            f"{pretty}\n\n"
            f"지금 바로 예매하세요 \U0001F449 http://ticket.cgv.co.kr"
        )
        send_dooray(message)
        print(f"새 예매일 감지, 알림 전송 완료: {new_days}")
    else:
        print("변경 사항 없음 (예매 오픈된 새 날짜가 없습니다).")

    state["play_ymd"] = play_ymd
    save_state(state)


if __name__ == "__main__":
    main()
