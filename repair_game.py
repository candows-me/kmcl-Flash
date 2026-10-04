# -*- coding: utf-8 -*-
"""补全游戏依赖：libraries + natives + assets 缺失项（只下载缺失文件，SHA1 校验）
镜像顺序：BMCLAPI 国内加速 → Mojang 官方源
"""
import os
import sys
import json
import time
import shutil
import hashlib
import zipfile
import urllib.request
import urllib.parse
import concurrent.futures

MC = os.path.join(os.path.expanduser("~"), ".minecraft")  # 默认目录；collect_tasks 可用 mc_root 参数覆盖
UA = {"User-Agent": "KmclLauncher/1.0"}
OFFICIAL_LIBS = "https://libraries.minecraft.net"
OFFICIAL_ASSETS = "https://resources.download.minecraft.net"
BMCLAPI = "https://bmclapi2.bangbang93.com"

VERSIONS = ["1.20.1", "26.3-pre-2"]
MAX_WORKERS = 64

# ---- 国内镜像映射（BMCLAPI，路径规则已按官方文档核实）----
# 官方前缀 -> 镜像前缀。dl_one / mirror_candidates 统一按此转换。
_MIRROR_PREFIXES = (
    ("https://piston-meta.mojang.com/",        BMCLAPI + "/"),
    ("http://piston-meta.mojang.com/",         BMCLAPI + "/"),
    ("https://launchermeta.mojang.com/",       BMCLAPI + "/"),
    ("https://launcher.mojang.com/",           BMCLAPI + "/"),
    ("https://piston-data.mojang.com/",        BMCLAPI + "/"),
    ("http://resources.download.minecraft.net/",  BMCLAPI + "/assets/"),
    ("https://resources.download.minecraft.net/", BMCLAPI + "/assets/"),
    ("http://libraries.minecraft.net/",        BMCLAPI + "/maven/"),
    ("https://libraries.minecraft.net/",       BMCLAPI + "/maven/"),
    ("https://maven.fabricmc.net/",            BMCLAPI + "/maven/"),
    ("https://meta.fabricmc.net/",             BMCLAPI + "/fabric-meta/"),
    ("https://maven.quiltmc.org/repository/release/", BMCLAPI + "/maven/"),
    ("https://meta.quiltmc.org/",              BMCLAPI + "/quilt-meta/"),
    ("https://files.minecraftforge.net/maven//", BMCLAPI + "/maven/"),
    ("https://maven.minecraftforge.net/",      BMCLAPI + "/maven/"),
    ("https://maven.neoforged.net/releases/",  BMCLAPI + "/maven/"),
    ("https://authlib-injector.yushi.moe/",    BMCLAPI + "/mirrors/authlib-injector/"),
)


def mirror_candidates(url):
    """把官方资源 URL 转成候选下载列表：国内镜像优先，官方源兜底。

    非映射域名的 URL 原样返回单元素列表。
    /maven/ 前缀的仓库额外追加 maven central 兜底：BMCLAPI /maven/ 对部分库
    （如 org.lwjgl 3.x natives-windows）返回 403，maven central 有全量 lwjgl 3.x。
    """
    if not url:
        return []
    for src, dst in _MIRROR_PREFIXES:
        if url.startswith(src):
            cands = [dst + url[len(src):], url]
            if "/maven/" in dst:
                cands.append("https://repo1.maven.org/maven2/" + url[len(src):])
            return cands
    if "/maven/" in url:
        return [url, "https://repo1.maven.org/maven2/" + url.split("/maven/", 1)[1]]
    return [url]


# ---- 测速选源（原版 client jar 专用）----
def speedtest_url(url, sample=262144, timeout=12):
    """对单个 URL 做真实下载测速：拉取 sample 字节，返回 (url, 速率B/s, 是否成功)。"""
    t0 = time.time()
    got = 0
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            while got < sample:
                c = r.read(min(65536, sample - got))
                if not c:
                    break
                got += len(c)
        return (url, got / max(time.time() - t0, 0.001), True)
    except Exception:
        return (url, 0, False)


def pick_fastest(urls, sample=262144, timeout=12):
    """并行测速多个 URL，返回最快的 URL；全部失败返回 None。

    只用于下载前选择更快的源，不影响下载校验（下载仍走 dl_one 的 sha1 校验）。
    """
    if not urls:
        return None
    if len(urls) == 1:
        return urls[0]
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(urls))) as ex:
        results = [f.result() for f in (ex.submit(speedtest_url, u, sample, timeout) for u in urls)]
    ok = [r for r in results if r[2]]
    if not ok:
        return None
    ok.sort(key=lambda r: r[1], reverse=True)
    return ok[0][0]


def rule_ok(rules):
    """评估库加载规则（只关心 windows）。

    标准语义（HMCL / Mojang 规范）：rules 为空 → 适用所有平台；
    rules 非空 → 只有至少一条规则匹配当前平台才适用，否则不适用。
    例：allow osx 在 Windows 上不适用；allow windows 适用；
        disallow osx + allow(默认) 在 Windows 上适用。
    """
    if not rules:
        return True
    matched = False
    for r in rules:
        os_info = r.get("os")
        if os_info is None or os_info.get("name") == "windows":
            matched = True
            if r.get("action") == "disallow":
                return False
    return matched


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(65536), b""):
            h.update(blk)
    return h.hexdigest()


def need_download(dest, size, sha1_):
    if not os.path.exists(dest):
        return True
    if size and abs(os.path.getsize(dest) - size) > 2:
        return True
    # 快速路径：assets/objects 下按 sha1 命名的文件（文件名==校验值），大小一致即可信，
    # 跳过全量读盘 sha1——快照索引有 4000+ 个对象，逐文件校验在机械盘上要卡几十秒。
    if sha1_ and os.path.basename(dest) == sha1_ and (
            os.sep + "assets" + os.sep + "objects" + os.sep in dest):
        return False
    if sha1_:
        try:
            if sha1(dest) != sha1_:
                return True
        except Exception:
            return True
    return False


def dl_one(task):
    """下载单个文件，返回 (ok, dest, msg)。镜像优先、官方兜底。
    单源 45s 内必须持续吐出数据（socket timeout=30 管单次阻塞，整体 deadline 管慢速吐数据），
    否则视为黑洞源放弃并换下一个候选——防止 CDN 挂起导致下载永远卡在 99%。
    assets 资源文件（官方 resources.download.minecraft.net）实测官方源快于 BMCLAPI，
    且 BMCLAPI 对部分冷文件 404——因此 assets 任务候选顺序改为官方优先、镜像兜底。
    单源 deadline 20s：慢速/黑洞源（assets 冷文件常见）更快放弃并换下一候选，
    避免大量超时文件堆积拖垮整体下载。"""
    url, dest, size, sha1_ = task
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".part"
        last_err = ""
        cands = mirror_candidates(url)
        if "resources.download.minecraft.net" in url or (
                os.sep + "assets" + os.sep + "objects" + os.sep in dest):
            cands = [u for u in cands if "bmclapi" not in u] + [u for u in cands if "bmclapi" in u]
        elif url.startswith(BMCLAPI + "/assets/"):
            # 双源并行：BMCLAPI 组 assets 404 时官方兜底
            cands.append(OFFICIAL_ASSETS + url[len(BMCLAPI):])
        for u in cands:
            try:
                req = urllib.request.Request(u, headers=UA)
                with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
                    # 超时按文件大小自适应：小文件快速放弃（防黑洞源堆积），
                    # 大文件（慢速源如官方 0.33MB/s）给足时间，避免误杀。
                    deadline = time.time() + max(20, min(120, (size or 1048576) // 262144))
                    while True:
                        if time.time() > deadline:
                            raise TimeoutError("源 %s 下载超时（45s）" % u)
                        c = r.read(65536)
                        if not c:
                            break
                        f.write(c)
                if sha1_ and sha1(tmp) != sha1_:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    last_err = "SHA1 不匹配"
                    continue
                os.replace(tmp, dest)
                return (True, dest, "")
            except Exception as e:
                last_err = str(e)
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                continue
        return (False, dest, last_err)
    except Exception as e:
        return (False, dest, str(e))


_host_mode_cache = {}          # hostname -> (mode, ts)；mode: "parallel"/"single"
_HOST_MODE_TTL = 30 * 60       # 探测结果缓存 30 分钟


def probe_host_mode(url, sample=1048576, timeout=8):
    """探测某 host 是否适合多连接并发下载（结果按 host 缓存 30 分钟）。

    单连接与 4 连接各拉取约 1MB 对比：并发提速 >=1.3 倍判定为 CDN 型
    ("parallel"，适合分块)；否则为限速型 ("single"，分块反而更慢，应单连接)。
    """
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or url
    except Exception:
        host = url
    now = time.time()
    hit = _host_mode_cache.get(host)
    if hit and now - hit[1] < _HOST_MODE_TTL:
        return hit[0]

    def one_speed():
        t0 = time.time()
        got = 0
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                while got < sample:
                    c = r.read(65536)
                    if not c:
                        break
                    got += len(c)
            return got / max(time.time() - t0, 0.001)
        except Exception:
            return 0.0

    def four_speed():
        got = [0] * 4
        def worker(i):
            t0 = time.time()
            try:
                req = urllib.request.Request(url, headers=dict(
                    UA, **{"Range": "bytes=%d-%d" % (i * sample, (i + 1) * sample - 1)}))
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    while time.time() - t0 < timeout:
                        c = r.read(65536)
                        if not c:
                            break
                        got[i] += len(c)
            except Exception:
                pass
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            fs = [ex.submit(worker, i) for i in range(4)]
            concurrent.futures.wait(fs, timeout=timeout + 5)
        return sum(got) / max(time.time() - t0, 0.001)

    s1 = one_speed()
    s4 = four_speed()
    mode = "parallel" if (s1 > 0 and s4 >= s1 * 1.3) else "single"
    _host_mode_cache[host] = (mode, time.time())
    print("[KMCL] 源模式探测 %s: 单连接%.2fMB/s 四并发%.2fMB/s -> %s" % (
        host, s1 / 1048576.0, s4 / 1048576.0, mode), flush=True)
    return mode


def dl_chunked(url, dest, size, sha1_, workers=24, min_size=8 * 1024 * 1024, progress=None):
    """大文件多线程分块下载（HTTP Range 并发），提速原版核心 jar 等大文件。

    - 仅当已知大小 >= min_size 且服务器支持 Range 时启用；否则直接回退 dl_one。
    - 分块前会探测当前 host 的“并发友好度”：并发提速明显的 CDN（官方
      piston-data/launcher.mojang、maven central 等）走分块；并发反而降速的
      限速型镜像（如 BMCLAPI）自动回退单连接 dl_one。探测结果按 host 缓存。
    - 按块并发拉取，合并后做 SHA1 校验；任一块失败/校验失败自动回退整包单连接下载。
    - progress: 可选回调 progress(done_bytes, total_bytes)，用于 UI 显示大文件进度。
    - 返回 (ok, dest, msg)，语义与 dl_one 一致。
    """
    if not size or size < min_size:
        return dl_one((url, dest, size, sha1_))
    tmp = dest + ".chunks"
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        # 探测 Range 支持（206 = 支持分块；200/403 等直接走整包）
        req = urllib.request.Request(url, headers=dict(UA, **{"Range": "bytes=0-1023"}))
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 206:
                return dl_one((url, dest, size, sha1_))
        # 并发友好度探测：限速型镜像（并发越多越慢）直接回退单连接
        if probe_host_mode(url) == "single":
            return dl_one((url, dest, size, sha1_))
        n = min(workers, max(2, size // (2 * 1024 * 1024)))   # 每块至少 2MB
        chunk = (size + n - 1) // n
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)

        def fetch(i):
            start, end = i * chunk, min((i + 1) * chunk, size)
            part = os.path.join(tmp, "c%04d" % i)
            try:
                req = urllib.request.Request(
                    url, headers=dict(UA, **{"Range": "bytes=%d-%d" % (start, end - 1)}))
                with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
                    if r.status != 206:
                        raise RuntimeError("Range 不支持")
                    deadline = time.time() + 90
                    while True:
                        if time.time() > deadline:
                            raise TimeoutError("分块下载超时")
                        c = r.read(65536)
                        if not c:
                            break
                        f.write(c)
                if os.path.getsize(part) != end - start:
                    raise RuntimeError("分块大小不符")
                return True
            except Exception:
                try:
                    os.remove(part)
                except OSError:
                    pass
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
            results = list(ex.map(fetch, range(n)))
        if not all(results):
            shutil.rmtree(tmp, ignore_errors=True)
            return dl_one((url, dest, size, sha1_))
        # 合并分块
        merged = dest + ".part"
        with open(merged, "wb") as out:
            for i in range(n):
                with open(os.path.join(tmp, "c%04d" % i), "rb") as f:
                    while True:
                        c = f.read(65536)
                        if not c:
                            break
                        out.write(c)
                if progress:
                    progress(min((i + 1) * chunk, size), size)
        shutil.rmtree(tmp, ignore_errors=True)
        if sha1_ and sha1(merged) != sha1_:
            try:
                os.remove(merged)
            except OSError:
                pass
            return dl_one((url, dest, size, sha1_))
        os.replace(merged, dest)
        return (True, dest, "")
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return dl_one((url, dest, size, sha1_))


def dl_task(t):
    """下载单个任务（与 dl_one 同签名/同返回）：大文件自动 Range 分块，小文件走 dl_one。

    所有版本下载路径统一入口：原版核心 jar、加载器依赖补齐、启动自动补齐、
    游戏修复等一律经由此函数，保证大文件（>=8MB）全部走多线程分块提速。
    大文件分块同样走镜像候选（BMCLAPI 优先、官方兜底），避免绕开镜像源。
    """
    url, dest, size, sha1_ = t
    if size and size >= 8 * 1024 * 1024:
        cands = mirror_candidates(url)
        # 大文件分块：官方源（CDN 型并发友好）优先，镜像兜底（限速型自动单连接）
        cands = [u for u in cands if "bmclapi" not in u] + [u for u in cands if "bmclapi" in u]
        last = ""
        for u in cands:
            ok, _, msg = dl_chunked(u, dest, size, sha1_)
            if ok:
                return (True, dest, "")
            last = msg
        return (False, dest, last or "所有源均失败")
    return dl_one(t)


def _mvn_relpath(name):
    """maven 坐标 group:artifact:version[:classifier][:ext] -> 相对 libraries 的路径。"""
    parts = (name or "").split(":")
    if len(parts) < 3:
        return None
    g, a, v = parts[0], parts[1], parts[2]
    cls = parts[3] if len(parts) > 3 else ""
    ext = parts[4] if len(parts) > 4 else "jar"
    jar = a + "-" + v + (("-" + cls) if cls else "") + "." + ext
    return "%s/%s/%s/%s" % (g.replace(".", "/"), a, v, jar)


def _native_short_name(name, classifier=""):
    """maven 坐标 -> natives jar 本地文件名（带 classifier 标记防同名覆盖）。"""
    parts = (name or "").split(":")
    if len(parts) < 3:
        return (name or "native").replace(":", "_")
    base = "%s_%s-%s" % (parts[0], parts[1], parts[2])
    cls = classifier or (parts[3] if len(parts) > 3 else "")
    return base + ("-" + cls if cls else "")


def collect_tasks(vid, mc_root=None):
    """收集版本需要的全部下载任务，支持 inheritsFrom 继承链（mc_root 覆盖模块级 MC 路径）。

    返回 (tasks, native_jars, base_vdir)：
      - client jar / natives 统一归位到继承链最底层（原版）目录；
      - libraries 合并全链（原版库 + 加载器库），兼容两种格式：
        官方 downloads.artifact（path/sha1/size）与 Fabric/Forge meta 的 name + url(仓库根)；
      - assets 索引取任一层声明（通常原版）。
    """
    MC_dir = mc_root or MC
    vdir = os.path.join(MC_dir, "versions", vid)
    vjson = os.path.join(vdir, vid + ".json")
    if not os.path.exists(vjson):
        return [], [], None

    # 读继承链：从当前版本到最底层原版
    chain = []          # [(vid, data), ...]，chain[-1] 为原版
    cur = vid
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        jp = os.path.join(MC_dir, "versions", cur, cur + ".json")
        if not os.path.exists(jp):
            break
        try:
            with open(jp, encoding="utf-8") as f:
                cur_data = json.load(f)
        except Exception:
            break
        chain.append((cur, cur_data))
        parent = cur_data.get("inheritsFrom")
        if not parent:
            break
        cur = parent

    base_vid, base_data = chain[-1]
    base_vdir = os.path.join(MC_dir, "versions", base_vid)
    tasks = []
    native_jars = []
    seen_native = set()

    # client jar（来自底层原版）→ 下载到原版目录（启动器从原版目录加载版本 jar）
    client = base_data.get("downloads", {}).get("client", {})
    if client.get("url"):
        tasks.append((client["url"], os.path.join(base_vdir, base_vid + ".jar"),
                      client.get("size", 0), client.get("sha1", "")))

    # 合并全链 libraries：底层（原版）在前，上层（加载器）追加
    libs = []
    for _, d in chain:
        libs.extend(d.get("libraries", []))
    for lib in libs:
        if not rule_ok(lib.get("rules")):
            continue
        dl = lib.get("downloads", {}) or {}
        art = dl.get("artifact", {}) or {}
        cls = dl.get("classifiers", {}) or {}
        lname = lib.get("name", "")
        # ① 老格式 classifiers：真正的 Windows 原生库在 natives-windows 分类包里。
        #    平台聚合包（lwjgl-platform / jinput-platform 等）主 jar 在仓库里根本不存在，
        #    直接下主 jar 必然 404，并导致启动自检永远"缺依赖"→ 无限自动补齐循环。
        nw = cls.get("natives-windows") or {}
        if nw.get("url"):
            _np = os.path.join(base_vdir, "natives",
                               _native_short_name(lname, "natives-windows") + ".jar")
            if os.path.normcase(os.path.normpath(_np)) not in seen_native:
                seen_native.add(os.path.normcase(os.path.normpath(_np)))
                native_jars.append((nw["url"], _np,
                                    nw.get("size", 0), nw.get("sha1", "")))
        # ② 老格式 natives：顶层 natives 字段 + 顶层 url 仓库根（LWJGL2 时代，1.12.2 及更早）。
        #    平台聚合包（lwjgl-platform / jinput-platform 等）的主 jar 在仓库里根本不存在，
        #    只有 -natives-windows 分类包存在；老格式 json 没有 downloads 字段，若按主 jar
        #    推导路径必然 404，并导致启动自检永远"缺依赖"→ 无限自动补齐循环。
        nat = lib.get("natives") or {}
        nw_old = nat.get("windows")
        if nw_old:
            repo = (lib.get("url") or OFFICIAL_LIBS).rstrip("/")
            rel = _mvn_relpath(lname)
            if rel and rel.endswith(".jar"):
                nrel = rel[:-4] + "-" + nw_old + ".jar"
                _np = os.path.join(base_vdir, "natives",
                                   _native_short_name(lname, nw_old) + ".jar")
                if os.path.normcase(os.path.normpath(_np)) not in seen_native:
                    seen_native.add(os.path.normcase(os.path.normpath(_np)))
                    native_jars.append((repo + "/" + nrel, _np, 0, ""))
        if not art.get("url") and (cls or nat):
            continue  # 聚合包：只取 natives，不生成主 jar 任务
        # ② 常规：官方 downloads.artifact / meta 的 name + url(仓库根)
        if art.get("url"):
            url, path = art["url"], art.get("path") or ""
            size, sha = art.get("size", 0), art.get("sha1", "")
        else:
            rel = _mvn_relpath(lname)
            if not rel:
                continue
            repo = (lib.get("url") or OFFICIAL_LIBS).rstrip("/")
            url, path = repo + "/" + rel, rel
            size, sha = 0, ""
        if not path:
            continue
        # 幽灵 artifact：官方老版本 json（1.8.9/1.12.2 的 lwjgl-platform 2.9.4 等）
        # 带一个 size<=64 字节的占位 artifact，仓库中根本不存在（下载必 404）。
        # 真实 jar 最小也 >1KB，size<=64 只可能是占位 → 跳过主 jar，避免无限补齐循环。
        if 0 < size <= 64:
            continue
        # natives 独立条目（新格式 name 带 :natives-xxx classifier）
        if ":natives-" in lname:
            if lname.endswith(":natives-windows"):
                # 只收 Windows x64 原生库 → 各自解压到原版 natives 目录
                native_jars.append((url,
                                    os.path.join(base_vdir, "natives",
                                                 _native_short_name(lname) + ".jar"),
                                    size, sha))
                # LWJGL3 内核（json 含 org.lwjgl:lwjgl:3.x）：natives jar 还必须落入
                # libraries/（maven 路径），由 classpath 引用、SharedLibraryLoader
                # 自动解压；否则 Cleanroom 等 LWJGL3 版本启动报 Failed to locate lwjgl.dll。
                if any(("org.lwjgl:lwjgl:3" in (l.get("name") or "")
                        for _, d in chain for l in d.get("libraries", []))):
                    tasks.append((url, os.path.join(MC_dir, "libraries", path),
                                  size, sha))
            # 其他平台（linux/macos/arm64）跳过，不下载
            continue
        tasks.append((url, os.path.join(MC_dir, "libraries", path),
                      size, sha))

    # assets 索引：取任一层声明（通常原版）
    ai = None
    for _, d in chain:
        if d.get("assetIndex", {}).get("url"):
            ai = d["assetIndex"]
            break
    if ai and ai.get("url"):
        aid = ai.get("id", "legacy")
        idx_path = os.path.join(MC_dir, "assets", "indexes", aid + ".json")
        # 索引缺失/损坏时先下载（dl_one 内部镜像优先、官方兜底）
        if need_download(idx_path, ai.get("size", 0), ai.get("sha1", "")):
            dl_one((ai["url"], idx_path, ai.get("size", 0), ai.get("sha1", "")))
        if os.path.exists(idx_path):
            try:
                with open(idx_path, encoding="utf-8") as f:
                    idx = json.load(f)
                _a_i = 0
                for obj in idx.get("objects", {}).values():
                    h = obj["hash"]
                    dest = os.path.join(MC_dir, "assets", "objects", h[:2], h)
                    # 双源并行：assets 任务一半走官方 resources（快、全），一半走 BMCLAPI
                    # （dl_one 内官方组候选顺序官方优先兜底 BMCLAPI；BMCLAPI 组原样），
                    # 池级并发下两个源同时下载不同文件，显著缩短全量资源下载时间。
                    if _a_i % 2 == 0:
                        base = OFFICIAL_ASSETS
                    else:
                        base = BMCLAPI + "/assets"
                    _a_i += 1
                    tasks.append((base + "/" + h[:2] + "/" + h,
                                  dest, obj.get("size", 0), h))
            except Exception as e:
                print(f"[assets] 索引读取失败: {e}")

    return tasks, native_jars, base_vdir


def extract_natives(njar, ndir):
    """解压 natives jar 到目录。
    LWJGL 3.4+ 的 natives 采用 windows/x64/ 前缀 + META-INF 结构，
    需要把原生库文件展平提取到目录根，供 java.library.path 加载。
    """
    with zipfile.ZipFile(njar) as z:
        for info in z.infolist():
            n = info.filename
            if n.endswith("/"):
                continue
            # 跳过 META-INF 下的非 windows 内容（module-info、sha1、git 等）
            if n.startswith("META-INF/") and "META-INF/windows" not in n:
                continue
            # 展平 windows/x64/ 前缀
            for prefix in ("META-INF/windows/x64/", "windows/x64/"):
                if n.startswith(prefix):
                    n = n[len(prefix):]
                    break
            base = os.path.basename(n)
            if not base or base.endswith((".class", ".sha1", ".git", ".txt", ".md", ".xml", ".MF", ".LIST")):
                continue
            out = os.path.join(ndir, base)
            if os.path.exists(out):
                continue
            with z.open(info) as src, open(out, "wb") as dst:
                while True:
                    c = src.read(65536)
                    if not c:
                        break
                    dst.write(c)


def main():
    for vid in VERSIONS:
        print(f"\n===== 版本 {vid} =====")
        tasks, native_jars, vdir = collect_tasks(vid)
        missing = [t for t in tasks if need_download(t[1], t[2], t[3])]
        print(f"任务总数 {len(tasks)}，缺失 {len(missing)} 个")

        ok_n = 0
        fail_n = 0
        if missing:
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                futures = {ex.submit(dl_task, t): t for t in missing}
                for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                    ok, dest, msg = fut.result()
                    name = os.path.basename(dest)
                    if ok:
                        ok_n += 1
                        print(f"  [{i}/{len(missing)}] OK   {name}")
                    else:
                        fail_n += 1
                        print(f"  [{i}/{len(missing)}] FAIL {name}  -> {msg}")

        # natives 下载 + 解压
        if vdir:
            ndir = os.path.join(vdir, "natives")
            os.makedirs(ndir, exist_ok=True)
            miss_n = [t for t in native_jars if need_download(t[1], t[2], t[3])]
            if miss_n:
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                    for fut in concurrent.futures.as_completed(
                            [ex.submit(dl_one, t) for t in miss_n]):
                        ok, dest, msg = fut.result()
                        print(f"  [natives] {'OK' if ok else 'FAIL'} {os.path.basename(dest)} {'' if ok else msg}")
            # 解压所有 natives jar（展平 windows/x64 结构）
            extracted = 0
            for nj in native_jars:
                if os.path.exists(nj[1]):
                    try:
                        extract_natives(nj[1], ndir)
                        extracted += 1
                    except Exception as e:
                        print(f"[natives] 解压失败 {os.path.basename(nj[1])}: {e}")
            nfiles = [f for f in os.listdir(ndir) if not f.endswith(".jar")] if os.path.isdir(ndir) else []
            print(f"[natives] 已处理 {extracted}/{len(native_jars)} 个原生库，DLL 等文件 {len(nfiles)} 个")

        print(f"结果：成功 {ok_n}，失败 {fail_n}")


if __name__ == "__main__":
    main()
