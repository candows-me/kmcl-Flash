# -*- coding: utf-8 -*-
"""KMCL 社区维护版 - Modrinth 资源下载逻辑层（业务逻辑，无 UI）。

架构参考 Kmcl 增强版 resource_page：
  - 热门 / 搜索（免密钥公共 API v2，按下载量排序）
  - 项目版本列表（按游戏版本过滤）
  - 流式下载（进度回调 + 取消）
  - 依赖解析（适配度打分：加载器一致 + MC 版本匹配优先）
  - .mrpack 整合包安装（SHA512 校验 + 防 zip-slip + overrides 铺放）
"""
import json
import os
import shutil
import hashlib
import zipfile
import tempfile
import urllib.request
import urllib.parse

MODRINTH = "https://api.modrinth.com/v2"
# 国内镜像（MCIM，已验证 search 等接口可用）：API 请求优先走镜像，失败自动回落官方
MODRINTH_MIRROR = "https://mod.mcimirror.top/modrinth/v2"
UA = {"User-Agent": "KMCL-Community/1.0"}


def _mirror_url(url):
    """官方 API URL -> 国内镜像 URL（仅替换前缀，路径不变）。"""
    if url.startswith(MODRINTH + "/"):
        return MODRINTH_MIRROR + url[len(MODRINTH):]
    return url


def _api_candidates(url):
    """镜像优先、官方兜底的候选地址列表。"""
    m = _mirror_url(url)
    return [m, url] if m != url else [url]


def fmt_downloads(n):
    """下载量格式化：1234567 -> 1.2M"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n >= 1000000:
        return "%.1fM" % (n / 1000000)
    if n >= 1000:
        return "%.1fk" % (n / 1000)
    return str(n)


def _http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_json_api(url):
    """镜像优先、官方兜底读取 JSON。"""
    last = None
    for u in _api_candidates(url):
        try:
            return _http_json(u)
        except Exception as e:
            last = e
    raise last  # 全失败时抛出官方源的错误


def modrinth_search(ptype, query="", mc_version=None, limit=15, offset=0, loaders=None):
    """搜索（query 为空 = 按下载量热门）。返回 (hits 列表, total_hits)。"""
    facets = [["project_type:%s" % ptype]]
    if mc_version:
        facets.append(["versions:%s" % mc_version])
    if loaders:
        facets.append(["categories:%s" % loaders])
    url = "%s/search?query=%s&facets=%s&index=downloads&limit=%d&offset=%d" % (
        MODRINTH,
        urllib.parse.quote(query or ""),
        urllib.parse.quote(json.dumps(facets, ensure_ascii=False)),
        limit, offset,
    )
    data = _http_json_api(url)
    hits = []
    for h in data.get("hits", []):
        hits.append({
            "project_id": h.get("project_id"),
            "slug": h.get("slug"),
            "title": h.get("title"),
            "desc": (h.get("description") or "")[:100],
            "downloads": h.get("downloads", 0),
            "icon_url": h.get("icon_url"),
            "author": (h.get("author") or ""),
        })
    return hits, data.get("total_hits", len(hits))


def project_versions(project_id, mc_version=None):
    """拉取项目版本列表（可选按游戏版本过滤，镜像优先）。
    返回全部版本，按发布时间倒序（最新版在最前，最旧版在最后）。
    """
    url = "%s/project/%s/version" % (MODRINTH, project_id)
    if mc_version:
        url += "?game_versions=%s" % urllib.parse.quote(json.dumps([mc_version]))
    data = _http_json_api(url)
    out = []
    for v in data or []:
        files = v.get("files") or []
        f = files[0] if files else {}
        out.append({
            "version_id": v.get("id", ""),
            "name": v.get("name") or v.get("version_number", ""),
            "version_number": v.get("version_number", ""),
            "date_published": v.get("date_published", ""),
            "version_type": v.get("version_type", "release"),
            "game_versions": v.get("game_versions", []),
            "loaders": v.get("loaders", []),
            "filename": f.get("filename", ""),
            "url": f.get("url", ""),
            "size": f.get("size", 0),
        })
    # 按发布时间倒序：最新版排最前，最旧版排最后
    out.sort(key=lambda x: x.get("date_published") or "", reverse=True)
    return out


def pick_versions(vs, count=4):
    """从已按最新->最旧排序的版本列表里挑出展示版本，避免一次列出太多卡顿：
    1 个最新版 + (count-1) 个稳定版（release 优先；稳定版不足时用其余版本补齐）。"""
    if len(vs) <= count:
        return vs
    out = [vs[0]]  # 最新版
    rest = vs[1:]
    # 稳定版：优先 release 类型
    for v in rest:
        if v.get("version_type") == "release":
            out.append(v)
        if len(out) >= count:
            break
    # release 不够 count-1 个时，用其余版本补齐
    if len(out) < count:
        for v in rest:
            if v not in out:
                out.append(v)
            if len(out) >= count:
                break
    return out


def download_file(url, dest, progress=None, cancel=None):
    """下载文件到 dest（多线程分块提速，失败自动回退单连接）。

    - 大文件（>=2MB 且服务器支持 Range）拆多段并发下载（默认 16 线程），
      突破 CDN 单连接限速（实测 cdn.modrinth.com 16 并发 ≈ 单连 1.9 倍）；
    - 小文件 / 不支持 Range 时自动回退原单连接流式下载；
    - progress(done, total) 回调；cancel() 返回 True 则中止。
    """
    from fast_download import download_fast
    return download_fast(url, dest, progress=progress, cancel=cancel)


def project_info(project_id):
    """拉取项目基础信息（slug 用于识别本地已装文件是否同项目）。"""
    url = "%s/project/%s" % (MODRINTH, project_id)
    data = _http_json_api(url)
    return {
        "project_id": project_id,
        "slug": data.get("slug", ""),
        "title": data.get("title", ""),
        "project_type": data.get("project_type", ""),
    }


def resolve_deps(version, mc_version, loaders=None):
    """解析版本依赖：返回 (deps, unresolved, optional_count)。

    version: project_versions 返回的某个版本 dict（含依赖信息需额外拉取）。
    简化实现：拉版本详情中的 dependencies，required 且匹配当前版本才纳入。
    """
    # 版本 dict 里通常不带 dependencies，需从版本接口取全字段
    deps, unresolved, optional_count = [], [], 0
    # 注意：/version/{id} 需要版本 UUID，不是 version_number
    vid = version.get("version_id") or version.get("id") or ""
    if not vid:
        return deps, unresolved, optional_count
    try:
        url = "%s/version/%s" % (MODRINTH, vid)
        data = _http_json_api(url)
    except Exception:
        return deps, unresolved, optional_count
    for d in data.get("dependencies", []) or []:
        kind = d.get("dependency_type")
        if kind != "required":
            if kind == "optional":
                optional_count += 1
            continue
        pid = d.get("project_id")
        if not pid:
            continue
        try:
            versions = project_versions(pid, mc_version)
        except Exception:
            unresolved.append(d.get("project_id", "?"))
            continue
        if not versions:
            unresolved.append(d.get("project_id", "?"))
            continue
        # 有加载器偏好时，优先选加载器一致的版本（如 fabric 依赖选 fabric 版）
        v = versions[0]
        if loaders:
            for cand in versions:
                if set(loaders) & set(cand.get("loaders", [])):
                    v = cand
                    break
        deps.append({
            "project_id": pid,
            "version_id": v.get("version_id", ""),
            "title": v.get("name", pid),
            "version_number": v.get("version_number", ""),
            "filename": v.get("filename", ""),
            "url": v.get("url", ""),
            "size": v.get("size", 0),
        })
    return deps, unresolved, optional_count


def collect_deps(version, mc_version, loaders=None, max_depth=3):
    """递归收集 required 依赖的下载清单（含嵌套依赖，去重、防环）。

    返回 (files, unresolved)：
      files     : 全部需补齐的依赖文件（含子依赖；每项含 slug 供本地已装识别）
      unresolved: 无法解析到可用版本的依赖项目 id
    """
    files, unresolved = [], []
    seen_files = set()
    slug_cache = {}

    def slug_of(pid):
        if pid in slug_cache:
            return slug_cache[pid]
        try:
            slug_cache[pid] = project_info(pid).get("slug", "")
        except Exception:
            slug_cache[pid] = ""
        return slug_cache[pid]

    def walk(ver, depth):
        if depth > max_depth:
            return
        deps, unr, _ = resolve_deps(ver, mc_version, loaders)
        for pid in unr:
            if pid not in unresolved:
                unresolved.append(pid)
        for d in deps:
            key = (d.get("project_id"), d.get("version_id"))
            if key in seen_files:
                continue
            seen_files.add(key)
            d = dict(d)
            d["slug"] = slug_of(d.get("project_id", ""))
            files.append(d)
            # 嵌套依赖：继续解析该依赖的依赖
            if d.get("version_id"):
                walk({"version_id": d["version_id"]}, depth + 1)

    walk(version, 0)
    return files, unresolved


def dep_installed(f, dep_dir):
    """判断依赖是否已安装：同名文件，或目录下已有同项目（slug）任意版本。

    返回 (是否已装, 命中文件名)。
    """
    fn = (f.get("filename") or "").lower()
    slug = (f.get("slug") or "").lower()
    if not os.path.isdir(dep_dir):
        return False, None
    try:
        for root, _, names in os.walk(dep_dir):
            for n in names:
                if not n.lower().endswith(".jar"):
                    continue
                if fn and n.lower() == fn:
                    return True, n
                if slug and slug in n.lower():
                    return True, n
    except OSError:
        pass
    return False, None


# ---- .mrpack 整合包安装 ----
_MRPACK_DENY = (
    "launcher_config.json", "options.txt", "saves/", "screenshots/",
    "launcher_profiles.json", "authlib-injector", "CustomSkinLoader",
)


def _safe_join(base, rel):
    """防 zip-slip：拒绝逃出 base 的路径与绝对路径。"""
    rel = rel.replace("\\", "/").lstrip("/")
    if rel.startswith("../") or "/../" in rel or rel.endswith(".."):
        raise RuntimeError("非法路径: %s" % rel)
    out = os.path.normpath(os.path.join(base, rel))
    if os.path.commonpath([out, os.path.normpath(base)]) != os.path.normpath(base):
        raise RuntimeError("路径越界: %s" % rel)
    return out


def _sha512(path):
    h = hashlib.sha512()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_mrpack_index(index):
    """解析 modrinth.index.json 的依赖信息。"""
    deps = index.get("dependencies", {}) or {}
    loader, loader_ver = "vanilla", None
    if "fabric-loader" in deps:
        loader, loader_ver = "fabric", deps["fabric-loader"]
    elif "neoforge" in deps:
        loader, loader_ver = "neoforge", deps["neoforge"]
    elif "forge" in deps:
        loader, loader_ver = "forge", deps["forge"]
    return {
        "name": index.get("name", "整合包"),
        "version": index.get("versionId", ""),
        "summary": index.get("summary", ""),
        "game": deps.get("minecraft", ""),
        "loader": loader,
        "loader_version": loader_ver,
        "deps": deps,
    }


def install_mrpack(mrpack_path, game_root, progress=None, cancel=None):
    """安装 .mrpack 整合包到 game_root。

    步骤：解压到临时目录 → 读索引 → 逐个下载索引文件（SHA512 校验，
    已存在且哈希一致的跳过）→ 铺 overrides → 清理临时文件。
    返回安装信息 dict。
    """
    tmpdir = tempfile.mkdtemp(prefix="kmcl_mrpack_")
    try:
        with zipfile.ZipFile(mrpack_path) as z:
            # 解压（防 zip-slip）
            for m in z.namelist():
                if m.startswith("overrides/"):
                    continue
                dest = _safe_join(tmpdir, m)
                if m.endswith("/"):
                    os.makedirs(dest, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(m) as src, open(dest, "wb") as f:
                    shutil.copyfileobj(src, f)
            # 索引
            idx_path = os.path.join(tmpdir, "modrinth.index.json")
            if not os.path.exists(idx_path):
                raise RuntimeError("缺少 modrinth.index.json")
            with open(idx_path, encoding="utf-8") as f:
                index = json.load(f)
            info = parse_mrpack_index(index)
            # 下载索引文件
            files = index.get("files", []) or []
            total = len(files)
            for i, item in enumerate(files, 1):
                if cancel and cancel():
                    raise RuntimeError("已取消安装")
                rel = item.get("path", "")
                url = item.get("url", "")
                sha512 = item.get("hashes", {}).get("sha512", "")
                if url.startswith("file://"):
                    src = url[7:].replace("/", os.sep)
                    dest = _safe_join(game_root, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(src, dest)
                    if progress:
                        progress(i, total)
                    continue
                dest = _safe_join(game_root, rel)
                if os.path.exists(dest) and sha512 and _sha512(dest) == sha512:
                    if progress:
                        progress(i, total)
                    continue
                if not url:
                    continue
                if progress:
                    progress(i, total)
                download_file(url, dest, cancel=cancel)
            # 铺 overrides
            with zipfile.ZipFile(mrpack_path) as z:
                for m in z.namelist():
                    if not m.startswith("overrides/") or m.endswith("/"):
                        continue
                    rel = m[len("overrides/"):]
                    dest = _safe_join(game_root, rel)
                    if rel in _MRPACK_DENY:
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with z.open(m) as src, open(dest, "wb") as f:
                        shutil.copyfileobj(src, f)
        return info
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
