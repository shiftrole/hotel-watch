#!/usr/bin/env python3
"""
tripla の client_session (TRIPLA_CLIENT_SESSION クッキー) を
ヘッドレスブラウザで取得する。

- 予約ページはログイン不要で開くだけでこのクッキーを新規発行する。
- その値が hotel_watch.py の client-session ヘッダーに必要な文字列そのもの。

前提:
    pip install -r requirements-refresh.txt
    playwright install chromium

使い方:
    python refresh_session.py            # ローカルの config.json を新しい値に更新
    python refresh_session.py --print    # 取得した値だけを標準出力に出す(CI用)
"""

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

# ログイン不要でクッキーが発行される予約ページ。日付は何でもよい。
BOOKING_URL = (
    "https://reserve.daiwaroynet.jp/booking/recommender"
    "?code=973ac83f8f52bc2c4e31f7ae854f65ab"
    "&checkin=2026%2F09%2F19&checkout=2026%2F09%2F21"
    "&type=rooms&is_day_use=false&order=recommended"
    "&is_including_occupied=false&rooms=%5B%7B%22adults%22%3A2%7D%5D"
    "&parentUrl=https%3A%2F%2Fwww.daiwaroynet.jp&mcp_currency=JPY"
)
COOKIE_NAME = "TRIPLA_CLIENT_SESSION"


def fetch_client_session(timeout_sec=30):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(BOOKING_URL, wait_until="load", timeout=60000)
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                for cookie in context.cookies():
                    if cookie["name"] == COOKIE_NAME and cookie["value"]:
                        return cookie["value"]
                page.wait_for_timeout(1000)
            return None
        finally:
            browser.close()


def update_local_config(token):
    if not os.path.exists(CONFIG_FILE):
        return False
    with open(CONFIG_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["client_session"] = token
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return True


def main():
    print_only = "--print" in sys.argv

    token = fetch_client_session()
    if not token:
        print(f"{COOKIE_NAME} クッキーを取得できませんでした。", file=sys.stderr)
        sys.exit(1)

    if print_only:
        # 標準出力にはトークンだけ（CI が $GITHUB_ENV に取り込む）
        print(token)
        return

    print(f"取得: {token[:24]}... ({len(token)} 文字)", file=sys.stderr)
    if update_local_config(token):
        print("config.json を更新しました。", file=sys.stderr)


if __name__ == "__main__":
    main()
