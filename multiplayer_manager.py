# -*- coding: utf-8 -*-
"""Kmcl 局域网联机核心模块。

工作原理（真·局域网联机）：
1. 房主在 Minecraft 里 ESC → 「对局域网开放」，游戏会监听一个端口（如 54321）。
2. 房主在启动器「联机」页输入该端口创建房间 → 生成 6 位联机码。
   启动器在 UDP 54201 端口上应答发现请求，并周期性向局域网广播房间信息。
3. 朋友（同一网络）输入联机码 → 启动器广播查找该房间 → 找到后握手加入，
   并每 4 秒发送心跳 → 房主界面实时显示谁加入了房间。
4. 朋友把 地址(ip:端口) 填进 Minecraft「多人游戏 → 直接连接」（或用
   启动器的「启动游戏并连接」，1.20+ 走 Quick Play 自动连）即可联机。

协议：UDP JSON 数据报，{"m": "KMCL1", "t": 类型, ...}
    find  → 房间应答 room（仅 code 匹配才应答）
    join  → 房主回 ok / bad，并登记成员
    hb    → 心跳（房主 12 秒没收到就判定离线）
    leave → 离开房间
    room  → 房主周期广播（加入者的「附近房间」列表被动接收）
"""
import os
import re
import json
import time
import socket
import random
import string
import threading

KMCL_UDP_PORT = 54201          # 联机协议端口（发现 + 成员管理）
MAGIC = "KMCL1"
ANNOUNCE_INTERVAL = 3.0        # 房间广播间隔（秒）
MEMBER_TIMEOUT = 12.0          # 成员超时（秒）
HEARTBEAT_INTERVAL = 4.0       # 心跳间隔（秒）

# 去掉易混淆字符（0/O、1/I/L）的联机码字母表
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def gen_room_code():
    """生成 6 位联机码，如 A3F9K2。"""
    return "".join(random.SystemRandom().choice(_CODE_ALPHABET) for _ in range(6))


def get_lan_ip():
    """取本机局域网 IP（UDP connect 探测法，不发数据）。失败返回 127.0.0.1。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return "127.0.0.1"


def check_game_port(port, timeout=1.0):
    """检测本机某端口是否有游戏在监听（TCP 可连接即认为在监听）。"""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def detect_lan_port(mc_root):
    """从游戏日志 latest.log 里自动检测「对局域网开放」得到的端口号。

    匹配（从最新行往前找，命中即返回）：
      Local game hosted on port 54321   (1.19.4+)
      Starting LAN server on port 54321 (旧版)
      ... serving on *:54321
    找不到返回 None。
    """
    log = os.path.join(mc_root or "", "logs", "latest.log")
    try:
        if not os.path.isfile(log):
            return None
        with open(log, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 65536))
            text = f.read().decode("utf-8", "replace")
        pats = [
            r"hosted on port (\d{4,5})",
            r"LAN server on port (\d{4,5})",
            r"serving on (?:/[\d.]+|\*):(\d{4,5})",
        ]
        for line in reversed(text.splitlines()):
            for p in pats:
                m = re.search(p, line)
                if m:
                    return int(m.group(1))
    except Exception:
        pass
    return None


def _broadcast_addrs():
    """发送目标：全网广播 + 本机回环（保证同机双开也能发现）。"""
    return [("255.255.255.255", KMCL_UDP_PORT), ("127.0.0.1", KMCL_UDP_PORT)]


# Windows 专用：关闭 UDP CONNRESET。
# 不关闭的话，向「没人监听的端口」发数据后（如广播/本机回环），
# 回来的 ICMP 端口不可达会让下一次 recvfrom 抛 WSAECONNRESET(10054)，导致线程中断。
SIO_UDP_CONNRESET = -1744830452  # 0x9800000C


def new_udp_sock(broadcast=True):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if broadcast:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.ioctl(SIO_UDP_CONNRESET, False)
    except Exception:
        pass  # 非 Windows 平台没有该选项
    return s


# ============================================================
# 房主端
# ============================================================
class HostRoom:
    """局域网房间：应答发现请求、登记成员、周期广播。"""

    def __init__(self):
        self.code = ""
        self.host_name = ""      # 房主游戏内昵称
        self.game_port = 0
        self.lan_ip = get_lan_ip()
        self._sock = None
        self._lock = threading.Lock()
        self._members = {}       # (name_lower, ip) -> {name, ip, joined, last_seen}
        self._stop = threading.Event()
        self._threads = []

    # ---- 生命周期 ----
    def start(self, game_port, host_name, code=None):
        """创建房间。端口被占用抛 OSError。"""
        self.stop()
        self.game_port = int(game_port)
        self.host_name = host_name or "Host"
        self.code = (code or gen_room_code()).upper()
        self._stop.clear()
        self._members.clear()
        self.lan_ip = get_lan_ip()

        self._sock = new_udp_sock()
        self._sock.bind(("0.0.0.0", KMCL_UDP_PORT))

        t1 = threading.Thread(target=self._reader_loop, daemon=True)
        t2 = threading.Thread(target=self._announce_loop, daemon=True)
        self._threads = [t1, t2]
        t1.start()
        t2.start()

    def stop(self):
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        self._threads = []

    @property
    def running(self):
        return self._sock is not None and not self._stop.is_set()

    # ---- 信息 ----
    def info(self, for_ip=None):
        return {
            "m": MAGIC, "t": "room",
            "code": self.code,
            "host_name": self.host_name,
            "host_ip": self.lan_ip,
            "game_port": self.game_port,
            "members": len(self.members()),
            "ts": time.time(),
        }

    def members(self):
        """成员快照：[{name, ip, joined, last_seen}]，已剔除超时成员。"""
        now = time.time()
        with self._lock:
            stale = [k for k, v in self._members.items()
                     if now - v["last_seen"] > MEMBER_TIMEOUT]
            for k in stale:
                del self._members[k]
            return [
                {
                    "name": v["name"], "ip": v["ip"],
                    "joined": v["joined"], "last_seen": v["last_seen"],
                }
                for v in self._members.values()
            ]

    # ---- 后台线程 ----
    def _reader_loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(4096)
            except OSError:
                # 瞬时网络错误（如 ICMP 回包）不退出线程；socket 已关则结束
                if self._stop.is_set() or self._sock is None:
                    break
                time.sleep(0.05)
                continue
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            if msg.get("m") != MAGIC:
                continue
            t = msg.get("t")
            if t == "find":
                q = str(msg.get("code", "")).upper()
                if q == self.code or q == "*":  # "*" = 附近房间扫描
                    self._send(self.info(), addr)
            elif t == "join":
                if str(msg.get("code", "")).upper() != self.code:
                    self._send({"m": MAGIC, "t": "bad"}, addr)
                else:
                    self._add_member(str(msg.get("name", "")).strip(), addr[0])
                    self._send({"m": MAGIC, "t": "ok",
                                "game_port": self.game_port,
                                "host_ip": self.lan_ip,
                                "code": self.code}, addr)
            elif t == "hb":
                name = str(msg.get("name", "")).strip()
                with self._lock:
                    key = (name.lower(), addr[0])
                    if key in self._members:
                        self._members[key]["last_seen"] = time.time()
            elif t == "leave":
                name = str(msg.get("name", "")).strip()
                with self._lock:
                    self._members.pop((name.lower(), addr[0]), None)

    def _announce_loop(self):
        while not self._stop.is_set():
            self._reap()
            info = self.info()
            for dest in _broadcast_addrs():
                self._send(info, dest)
            self._stop.wait(ANNOUNCE_INTERVAL)

    def _reap(self):
        now = time.time()
        with self._lock:
            stale = [k for k, v in self._members.items()
                     if now - v["last_seen"] > MEMBER_TIMEOUT]
            for k in stale:
                del self._members[k]

    def _add_member(self, name, ip):
        if not name:
            name = "Player"
        with self._lock:
            key = (name.lower(), ip)
            if key not in self._members:
                self._members[key] = {
                    "name": name, "ip": ip,
                    "joined": time.time(), "last_seen": time.time(),
                }
            else:
                self._members[key]["last_seen"] = time.time()

    def _send(self, obj, dest):
        if not self._sock:
            return
        try:
            self._sock.sendto(json.dumps(obj).encode("utf-8"), dest)
        except Exception:
            pass


# ============================================================
# 加入者端
# ============================================================
def find_room(code, timeout=3.0):
    """按联机码查找房间（广播 + 本机直查），返回房间信息 dict 或 None。"""
    code = (code or "").strip().upper()
    if not code:
        return None
    sock = new_udp_sock()
    sock.settimeout(0.4)
    req = json.dumps({"m": MAGIC, "t": "find", "code": code}).encode("utf-8")
    deadline = time.time() + timeout
    result = None
    try:
        while time.time() < deadline and result is None:
            for dest in _broadcast_addrs():
                try:
                    sock.sendto(req, dest)
                except Exception:
                    pass
            end = min(deadline, time.time() + 0.4)
            while time.time() < end:
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    break
                except OSError:
                    break
                try:
                    msg = json.loads(data.decode("utf-8"))
                except Exception:
                    continue
                if (msg.get("m") == MAGIC and msg.get("t") == "room"
                        and str(msg.get("code", "")).upper() == code):
                    result = msg
                    break
    finally:
        sock.close()
    return result


def browse_rooms(timeout=2.5):
    """扫描局域网内正在运行的房间（向全网广播 find *，收集房主应答）。"""
    sock = new_udp_sock()
    sock.settimeout(0.4)
    req = json.dumps({"m": MAGIC, "t": "find", "code": "*"}).encode("utf-8")
    rooms = {}
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            for dest in _broadcast_addrs():
                try:
                    sock.sendto(req, dest)
                except Exception:
                    pass
            end = min(deadline, time.time() + 0.4)
            while time.time() < end:
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    break
                except OSError:
                    break
                try:
                    msg = json.loads(data.decode("utf-8"))
                except Exception:
                    continue
                if (msg.get("m") == MAGIC and msg.get("t") == "room"
                        and msg.get("code")):
                    rooms[msg["code"]] = {
                        "code": msg["code"],
                        "host_name": msg.get("host_name", ""),
                        "host_ip": msg.get("host_ip", addr[0]),
                        "game_port": msg.get("game_port", 0),
                        "members": msg.get("members", 0),
                    }
    finally:
        sock.close()
    return rooms


class RoomClient:
    """已加入房间的客户端：维持心跳、可离开。"""

    def __init__(self):
        self.room = {}
        self.name = ""
        self.joined_at = 0
        self._host_addr = None
        self._stop = threading.Event()
        self._thread = None

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    def connect(self, room, name):
        """向房间发送加入握手。成功返回 True。"""
        self.leave()
        name = (name or "").strip() or "Player"
        host_ip = room.get("host_ip", "")
        if not host_ip:
            return False
        self.room = room
        self.name = name
        self.joined_at = time.time()
        self._host_addr = (host_ip, KMCL_UDP_PORT)
        self._stop.clear()
        # 加入握手（带重试）
        ok = False
        for _ in range(3):
            reply = self._request({"m": MAGIC, "t": "join",
                                   "code": room.get("code", ""), "name": name})
            if reply and reply.get("t") == "ok":
                ok = True
                break
            if reply and reply.get("t") == "bad":
                return False
            if not self._stop.is_set():
                time.sleep(0.3)
        if not ok:
            return False
        self._thread = threading.Thread(target=self._hb_loop, daemon=True)
        self._thread.start()
        return True

    def leave(self):
        if self._host_addr and self.room:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.sendto(json.dumps(
                    {"m": MAGIC, "t": "leave",
                     "code": self.room.get("code", ""), "name": self.name}
                ).encode("utf-8"), self._host_addr)
                s.close()
            except Exception:
                pass
        self._stop.set()
        self._thread = None
        self._host_addr = None
        self.room = {}

    def server_address(self):
        if not self.room:
            return ""
        return f"{self.room.get('host_ip', '')}:{self.room.get('game_port', '')}"

    # ---- 内部 ----
    def _hb_loop(self):
        while not self._stop.wait(HEARTBEAT_INTERVAL):
            try:
                s = new_udp_sock(broadcast=False)
                s.sendto(json.dumps(
                    {"m": MAGIC, "t": "hb",
                     "code": self.room.get("code", ""), "name": self.name}
                ).encode("utf-8"), self._host_addr)
                s.close()
            except Exception:
                pass

    def _request(self, obj, timeout=1.0):
        try:
            s = new_udp_sock(broadcast=False)
            s.settimeout(timeout)
            try:
                s.sendto(json.dumps(obj).encode("utf-8"), self._host_addr)
                data, _ = s.recvfrom(4096)
                return json.loads(data.decode("utf-8"))
            finally:
                s.close()
        except Exception:
            return None
