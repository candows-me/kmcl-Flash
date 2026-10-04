# -*- coding: utf-8 -*-
"""微软正版登录 - Authorization Code Flow（授权码流程）
使用旧版 Minecraft 启动器 client_id + 旧版桌面回调地址。
流程：构造授权 URL → 打开浏览器 → 用户登录授权 → 从浏览器地址栏复制 code → 粘贴回启动器 → 换 token → Xbox Live → XSTS → Minecraft
"""
import json
import time
import re
import urllib.request
import urllib.parse
import webbrowser

CLIENT_ID = "00000000402b5328"   # 旧版 Minecraft 启动器 client_id
REDIRECT_URI = "https://login.live.com/oauth20_desktop.srf"  # 旧版桌面应用回调地址
SCOPE = "XboxLive.signin offline_access"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"


def get_auth_url():
    """构造微软授权 URL，供 UI 打开浏览器。"""
    return (
        "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?"
        f"client_id={CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&scope={urllib.parse.quote(SCOPE)}"
        "&response_mode=query"
        "&prompt=select_account"
    )


def open_browser():
    """打开浏览器到微软授权页面。"""
    webbrowser.open(get_auth_url())


def extract_code_from_url(url):
    """从浏览器地址栏的 URL 中提取 authorization code。
    支持完整 URL（https://login.live.com/oauth20_desktop.srf?code=xxx）或直接粘贴 code。
    """
    if not url:
        return None
    url = url.strip()
    # 直接是 code（没有 URL 特征）
    if "=" not in url and "://" not in url and len(url) > 10:
        return url
    # 从 URL 查询参数提取 code
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            return params["code"][0]
    except Exception:
        pass
    # 正则兜底
    m = re.search(r'[?&]code=([^&]+)', url)
    if m:
        return m.group(1)
    return None


def _post_json(url, data, headers=None):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_form(url, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _xbox_auth(ms_access_token):
    """Xbox Live → XSTS → Minecraft，返回 Minecraft access_token 和 expires_in"""
    # Xbox Live
    xbl = _post_json("https://user.auth.xboxlive.com/user/authenticate", {
        "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com", "RpsTicket": f"d={ms_access_token}"},
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    })
    xbl_token = xbl["Token"]
    xui = ((xbl.get("DisplayClaims") or {}).get("xui")) or []
    if not xui or not xui[0].get("uhs"):
        raise RuntimeError("该微软账号没有 Xbox Live 档案（常见于儿童/未初始化账号），请先在 xbox.com 完成一次登录后再试")
    user_hash = xui[0]["uhs"]

    # XSTS
    xsts = _post_json("https://xsts.auth.xboxlive.com/xsts/authorize", {
        "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType": "JWT",
    })
    xsts_token = xsts["Token"]

    # Minecraft 登录
    mc = _post_json("https://api.minecraftservices.com/authentication/login_with_xbox", {
        "identityToken": f"XBL3.0 x={user_hash};{xsts_token}",
    })
    return mc["access_token"], int(mc.get("expires_in", 86400))


def login_with_code(code):
    """用 authorization code 完成完整登录流程，返回 {access_token, refresh_token, uuid, name, expires_at, type}"""
    if not code:
        raise RuntimeError("授权码为空")
    # 1. 用 code 换微软 access_token
    ms = _post_form(TOKEN_URL, {
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
        "scope": SCOPE,
    })
    ms_access = ms["access_token"]
    ms_refresh = ms.get("refresh_token", "")

    # 2. Xbox → Minecraft
    mc_access, expires_in = _xbox_auth(ms_access)

    # 3. 玩家档案
    profile = _get_json("https://api.minecraftservices.com/minecraft/profile",
                        headers={"Authorization": f"Bearer {mc_access}"})

    return {
        "access_token": mc_access,
        "refresh_token": ms_refresh,
        "uuid": profile["id"],
        "name": profile["name"],
        "expires_at": int(time.time()) + expires_in,
        "type": "microsoft",
    }


def login_microsoft():
    """完整登录流程：打开浏览器 → 返回 auth_url（UI 层负责获取 code 并调用 login_with_code）。
    保留此函数名兼容旧调用，但实际逻辑拆分到 get_auth_url + login_with_code。
    """
    open_browser()
    return get_auth_url()


def refresh_microsoft(refresh_token):
    """用 refresh_token 刷新 access_token，返回新的 {access_token, refresh_token, expires_at}"""
    if not refresh_token:
        return None
    try:
        ms = _post_form(TOKEN_URL, {
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": SCOPE,
        })
        ms_access = ms["access_token"]
        ms_refresh = ms.get("refresh_token", refresh_token)
        mc_access, expires_in = _xbox_auth(ms_access)
        return {
            "access_token": mc_access,
            "refresh_token": ms_refresh,
            "expires_at": int(time.time()) + expires_in,
        }
    except Exception:
        return None
