#!/usr/bin/env python3
"""
tripla の client_session (TRIPLA_CLIENT_SESSION クッキー) を
ヘッドレスブラウザで取得し、ローカルの config.json と
GitHub Secret CLIENT_SESSION を更新する半自動スクリプト。

前提:
    pip install playwright
    playwright install chromium
    gh CLI がログイン済み (gh auth status で確認)

使い方:
    python refresh_session.py            # config.json と GitHub Secret を更新
    python refresh_session.py --print    # 取得した値を表示するだけ
"""

import json
import os
import subprocess
import sys

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
GITHUB_REPO = "shiftrole/hotel-watch"


def fetch_client_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(BOOKING_URL, wait_until="load", timeout=60000)
        page.wait_for_timeout(3000)  # ウィジェットJSがクッキーを立てるのを待つ
        token = None
        for cookie in context.cookies():
            if cookie["name"] == COOKIE_NAME:
                token = cookie["value"]
        browser.close()
        return token


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


def update_github_secret(token):
    # gh secret set は stdin から値を読む（コマンド履歴に残らない）
    result = subprocess.run(
        ["gh", "secret", "set", "CLIENT_SESSION", "-R", GITHUB_REPO],
        input=token,
        text=True,
    )
    return result.returncode == 0


def main():
    token = fetch_client_session()
    if not token:
        print(f"{COOKIE_NAME} クッキーを取得できませんでした。", file=sys.stderr)
        sys.exit(1)

    print(f"取得: {token[:24]}... ({len(token)} 文字)")

    if "--print" in sys.argv:
        print(token)
        return

    if update_local_config(token):
        print("config.json を更新しました。")

    if update_github_secret(token):
        print("GitHub Secret CLIENT_SESSION を更新しました。")
    else:
        print("gh secret set に失敗しました。gh auth status を確認してください。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
