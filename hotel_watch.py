#!/usr/bin/env python3
"""
ダイワロイネットホテル(tripla予約エンジン)空室監視スクリプト

複数の候補日程を定期的にチェックし、「満室→空室あり」に変化したタイミングで
Slackに通知します。cron等で定期実行することを想定しています(例: 30分おき)。

使い方:
    1. pip install requests
    2. config.example.json を config.json にコピーして編集
    3. python hotel_watch.py  (手動で一度動作確認)
    4. cron等に登録して定期実行
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

# Windowsのコンソール(cp932)だと "¥" や絵文字で UnicodeEncodeError になるため、
# 標準出力/エラーを UTF-8 に固定する。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "state.json")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

API_URL_TEMPLATE = "https://concierge.tripla.ai/book/hotels/{hotel_id}/rooms"

DEFAULT_HEADERS_TEMPLATE = {
    "accept": "application/json",
    "content-type": "application/json",
    "origin": "https://reserve.daiwaroynet.jp",
    "referer": "https://reserve.daiwaroynet.jp/",
    "app-version": "tripla-booking-widget/1.0",
    "tripla-locale": "ja",
    "x-site-controller": "tl_lincon",
    "x-tripla-tier": "vip",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
}


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_rooms(hotel_id, checkin, checkout, adults, client_session):
    params = {
        "order": "recommended",
        "rooms[][adults]": adults,
        "rooms[][checkin_date]": checkin,
        "rooms[][checkout_date]": checkout,
        "rooms[][children]": 0,
        "is_day_use": "false",
        "is_including_occupied": "false",
        "bookable": "true",
        "type": "rooms",
        "mcp_locale": "ja-JP",
    }
    headers = dict(DEFAULT_HEADERS_TEMPLATE)
    headers["client-session"] = client_session

    url = API_URL_TEMPLATE.format(hotel_id=hotel_id)
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()


def notify_slack(webhook_url, message):
    resp = requests.post(webhook_url, json={"text": message}, timeout=10)
    resp.raise_for_status()


def filter_rooms(rooms, name_filter):
    """room_type_name に name_filter を含む部屋だけ返す。filter が空なら全件。"""
    if not name_filter:
        return rooms
    return [r for r in rooms if name_filter in r.get("room_type_name", "")]


def format_rooms_summary(rooms):
    lines = []
    for room in rooms:
        name = room.get("room_type_name", "(不明な部屋タイプ)")
        price = room.get("min_price")
        count = room.get("room_count")
        price_str = f"¥{price:,}〜" if price is not None else "-"
        lines.append(f"・{name} / {price_str} / 残室{count}")
    return "\n".join(lines) if lines else "(詳細取得できず)"


def build_booking_url(hotel_code, checkin, checkout, adults):
    return (
        "https://reserve.daiwaroynet.jp/booking/recommender"
        f"?code={hotel_code}"
        f"&checkin={checkin.replace('/', '%2F')}"
        f"&checkout={checkout.replace('/', '%2F')}"
        "&type=rooms&is_day_use=false&order=recommended"
        "&is_including_occupied=false"
        f"&rooms=%5B%7B%22adults%22%3A{adults}%7D%5D"
        "&parentUrl=https%3A%2F%2Fwww.daiwaroynet.jp&mcp_currency=JPY"
    )


def main():
    config = load_json(CONFIG_FILE, None)
    if config is None:
        print(
            "config.json が見つかりません。config.example.json を参考に作成してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    state = load_json(STATE_FILE, {})

    hotel_id = config["hotel_id"]
    hotel_code = config.get("hotel_code", "")
    # 部屋名にこの文字列を含む部屋だけを判定・通知の対象にする(例: "禁煙")。空なら全部屋。
    room_name_filter = config.get("room_name_filter", "")
    # CI(GitHub Actions)などでは秘匿値を環境変数から渡す。あれば config.json より優先。
    client_session = os.environ.get("CLIENT_SESSION") or config["client_session"]
    slack_webhook_url = os.environ.get("SLACK_WEBHOOK_URL") or config["slack_webhook_url"]

    any_error = False

    for target in config["targets"]:
        checkin = target["checkin_date"]
        checkout = target["checkout_date"]
        adults = target.get("adults", 2)
        key = f"{hotel_id}:{checkin}:{checkout}:{adults}"

        try:
            data = fetch_rooms(hotel_id, checkin, checkout, adults, client_session)
        except requests.HTTPError as e:
            print(f"[ERROR] {key}: {e}", file=sys.stderr)
            any_error = True
            continue
        except requests.RequestException as e:
            print(f"[ERROR] {key}: {e}", file=sys.stderr)
            any_error = True
            continue

        rooms = filter_rooms(data.get("rooms", []), room_name_filter)
        was_available = state.get(key, {}).get("available", False)
        is_available = len(rooms) > 0

        if is_available and not was_available:
            summary = format_rooms_summary(rooms)
            url = build_booking_url(hotel_code, checkin, checkout, adults)
            label = f"空室が見つかりました（{room_name_filter}）" if room_name_filter else "空室が見つかりました"
            message = (
                f":bell: *{label}*\n"
                f"{checkin} 〜 {checkout} (大人{adults}名)\n"
                f"{summary}\n"
                f"{url}"
            )
            print(message)
            try:
                notify_slack(slack_webhook_url, message)
            except requests.RequestException as e:
                print(f"[ERROR] Slack通知失敗: {e}", file=sys.stderr)
        elif not is_available and was_available:
            print(f"[INFO] {key}: 満室に戻りました")
        else:
            print(f"[INFO] {key}: 変化なし (空室あり={is_available})")

        state[key] = {
            "available": is_available,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    save_json(STATE_FILE, state)

    if any_error:
        print(
            "\n一部リクエストが失敗しました。client_session の有効期限切れの可能性があります。"
            "DevToolsで新しい値を取得し config.json を更新してください。",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
