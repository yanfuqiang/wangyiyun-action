import base64
import hashlib
import json
import sys
from typing import Any, Dict, Iterable, List

import requests
from Crypto.Cipher import AES


API_TIMEOUT = 20
AES_IV = b"0102030405060708"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
    "Accept-Encoding": "gzip, deflate",
}

LOGIN_URL = "https://music.163.com/weapi/login/cellphone"
DAILY_TASK_URL = "https://music.163.com/weapi/point/dailyTask"
RECOMMEND_URL = "https://music.163.com/weapi/v1/discovery/recommend/resource"
PLAYLIST_URL = "https://music.163.com/weapi/v3/playlist/detail"
WEBLOG_URL = "https://music.163.com/weapi/feedback/weblog"


def encrypt(key: str, text: str) -> str:
    """Encrypt a request body using the legacy NetEase Web API scheme."""
    raw = text.encode("utf-8")
    padding = 16 - (len(raw) % 16)
    raw += bytes([padding]) * padding
    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, AES_IV)
    return base64.b64encode(cipher.encrypt(raw)).decode("ascii")


def md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def protect(text: str) -> Dict[str, str]:
    return {
        "params": encrypt(
            "TA3YiYCfY2dDJQgg",
            encrypt("0CoJUm6Qyw8W8jud", text),
        ),
        "encSecKey": (
            "84ca47bca10bad09a6b04c5c927ef077d9b9f1e37098aa3eac6ea70eb59df0aa28b691b7e75e4f1f9831754919ea784c8f74fbfadf2898b0be17849fd656060162857830e241aba44991601f137624094c114ea8d17bce815b0cd4e5b8e2fbaba978c6d1d14dc3d1faf852bdd28818031ccdaaa13a6018e1024e2aae98844210"
        ),
    }


def post_json(session: requests.Session, url: str, payload: Any) -> Dict[str, Any]:
    response = session.post(
        url,
        data=protect(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        timeout=API_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("网易云接口返回了非对象 JSON")
    return body


def csrf_token(session: requests.Session) -> str:
    token = session.cookies.get("__csrf")
    if not token:
        raise RuntimeError("登录成功，但响应中没有 __csrf Cookie")
    return token


def build_play_logs(
    session: requests.Session, recommendations: Iterable[Dict[str, Any]], token: str
) -> List[Dict[str, Any]]:
    logs: List[Dict[str, Any]] = []
    for recommendation in recommendations:
        playlist_id = recommendation.get("id")
        if not playlist_id:
            continue
        playlist = post_json(
            session,
            f"{PLAYLIST_URL}?csrf_token={token}",
            {"id": playlist_id, "n": 1000, "csrf_token": token},
        )
        track_ids = playlist.get("playlist", {}).get("trackIds", [])
        for track in track_ids:
            track_id = track.get("id") if isinstance(track, dict) else None
            if not track_id:
                continue
            logs.append(
                {
                    "action": "play",
                    "json": {
                        "download": 0,
                        "end": "playend",
                        "id": track_id,
                        "sourceId": "",
                        "time": "240",
                        "type": "song",
                        "wifi": 0,
                    },
                }
            )
            if len(logs) >= 310:
                return logs
    return logs


def run(phone: str, password: str) -> int:
    if not phone or not password:
        raise ValueError("手机号和密码不能为空")

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    login = post_json(
        session,
        LOGIN_URL,
        {
            "phone": phone,
            "countrycode": "86",
            "password": md5_hex(password),
            "rememberLogin": "true",
        },
    )
    if login.get("code") != 200:
        raise RuntimeError(f"登录失败，错误码：{login.get('code')}，{login.get('msg', '')}")
    print("登录成功")

    token = csrf_token(session)
    daily = post_json(session, DAILY_TASK_URL, {"type": 0})
    if daily.get("code") == 200:
        print(f"签到成功，获得 {daily.get('point', 0)} 点")
    elif daily.get("code") == -2:
        print("今天已经签到")
    else:
        print(f"签到失败：{daily.get('msg', daily.get('code'))}")

    recommendations_body = post_json(
        session, RECOMMEND_URL, {"csrf_token": token}
    )
    recommendations = recommendations_body.get("recommend")
    if not isinstance(recommendations, list):
        raise RuntimeError("推荐歌单接口没有返回 recommend 列表")

    logs = build_play_logs(session, recommendations, token)
    if not logs:
        raise RuntimeError("没有找到可提交的歌曲")

    result = post_json(session, WEBLOG_URL, {"logs": json.dumps(logs)})
    if result.get("code") != 200:
        raise RuntimeError(f"播放记录提交失败，错误码：{result.get('code')}，{result.get('message', '')}")
    print(f"播放记录提交成功，共 {len(logs)} 首")
    return 0


def main() -> int:
    phone = sys.stdin.readline().rstrip("\r\n").strip()
    password = sys.stdin.readline().rstrip("\r\n")
    try:
        return run(phone, password)
    except (requests.RequestException, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
