# -*- coding: utf-8 -*-
"""Java 管理器 + 启动命令组装
- 按需获取 Java：先探测系统已安装（注册表 / JAVA_HOME / 常见目录），
  没有则自动下载对应 JDK 到 %LOCALAPPDATA%\\KMCL\\jdk（仅首次），不再内置
- 根据游戏版本的 javaVersion 要求自动匹配对应 JDK
- 完整组装启动命令（classpath 全部 libraries + natives + assets 参数）
"""
import os
import re
import json
import shutil
import zipfile
import urllib.request


def _ensure_fml_lzma(mc_root, version_data, libs):
    """老 FML（≤1.12.2）的 PatchingTransformer 依赖 LZMA.LzmaInputStream。

    Cleanroom 等自足格式 json 缺 Mojang 库 lzma:lzma:0.0.1（官方 Forge 1.12.2 库清单
    自带），classpath 无 LZMA 类时 PatchingTransformer.transform 抛
    NoClassDefFoundError: LZMA/LzmaInputStream。规则：老 FML 主类场景且 classpath
    无 LZMA 类时，自动补 lzma-0.0.1.jar（Mojang 官方库，5.7KB，仅含 LZMA 包）。
    """
    # 放宽：Cleanroom（top.outlands.foundation.boot.Foundation）也是 FML 内核，
    # 其 PatchingTransformer 同样依赖 LZMA；纯原版主类（client.main.Main /
    # launchwrapper.Launch）不引 LZMA，不需要补。
    _mc = (version_data.get("mainClass") or "").lower()
    if _mc in ("net.minecraft.client.main.main", "net.minecraft.launchwrapper.launch"):
        return
    if not any(k in _mc for k in ("fml", "outlands", "foundation", "cleanroom")):
        return
    for lp in libs:
        try:
            with zipfile.ZipFile(lp) as z:
                if "LZMA/LzmaInputStream.class" in z.namelist():
                    return
        except Exception:
            continue
    rel = "lzma/lzma/0.0.1/lzma-0.0.1.jar"
    dst = os.path.join(mc_root, "libraries", rel)
    if not os.path.isfile(dst):
        urls = [
            "https://libraries.minecraft.net/" + rel,
            "https://bmclapi2.bangbang93.com/libraries/" + rel,
        ]
        ok = False
        for u in urls:
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                req = urllib.request.Request(u, headers={"User-Agent": "KMCL-Community/1.0"})
                with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
                    shutil.copyfileobj(r, f)
                if os.path.isfile(dst) and os.path.getsize(dst) > 1000:
                    ok = True
                    break
            except Exception:
                try:
                    if os.path.isfile(dst):
                        os.remove(dst)
                except Exception:
                    pass
        if not ok:
            return
    libs.append(dst)


def _ensure_fml_vecmath(mc_root, version_data, libs):
    """老 FML（≤1.12.2）的 Minecraft 代码硬依赖 javax.vecmath（java3d:vecmath:1.5.2）。

    Cleanroom 等自足格式 json 未声明该库（原版 1.12.2 官方 json 也未显式列出，
    vecmath 实际由 Mojang 库 java3d:vecmath:1.5.2 提供，老 Forge 库清单自带）。
    classpath 无 vecmath 类时 Minecraft.<init> 抛
    NoClassDefFoundError: javax/vecmath/Tuple4f。规则：老 FML 主类场景且 classpath
    无 vecmath 时，自动补 vecmath-1.5.2.jar（Mojang 官方库）。
    """
    _mc = (version_data.get("mainClass") or "").lower()
    if _mc in ("net.minecraft.client.main.main", "net.minecraft.launchwrapper.launch"):
        return
    if not any(k in _mc for k in ("fml", "outlands", "foundation", "cleanroom")):
        return
    for lp in libs:
        try:
            with zipfile.ZipFile(lp) as z:
                if "javax/vecmath/Tuple4f.class" in z.namelist():
                    return
        except Exception:
            continue
    rel = "java3d/vecmath/1.5.2/vecmath-1.5.2.jar"
    dst = os.path.join(mc_root, "libraries", rel)
    if not os.path.isfile(dst):
        urls = [
            "https://libraries.minecraft.net/" + rel,
            "https://bmclapi2.bangbang93.com/libraries/" + rel,
        ]
        ok = False
        for u in urls:
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                req = urllib.request.Request(u, headers={"User-Agent": "KMCL-Community/1.0"})
                with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
                    shutil.copyfileobj(r, f)
                if os.path.isfile(dst) and os.path.getsize(dst) > 1000:
                    ok = True
                    break
            except Exception:
                try:
                    if os.path.isfile(dst):
                        os.remove(dst)
                except Exception:
                    pass
        if not ok:
            return
    libs.append(dst)


def _ensure_launcher_profiles(mc_root):
    """老 FML（≤1.12.2）FMLLaunchHandler.setupHome 要求游戏根存在 launcher_profiles.json，
    缺失时抛 "An error occurred trying to configure the Minecraft home"。
    自动补默认文件（幂等，对新版本无影响）。"""
    dst = os.path.join(mc_root, "launcher_profiles.json")
    if os.path.isfile(dst):
        return
    try:
        os.makedirs(mc_root, exist_ok=True)
        payload = {
            "profiles": {"(Default)": {"name": "(Default)", "lastVersionId": ""}},
            "selectedProfile": "(Default)",
            "clientToken": "kmcl-community",
        }
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass


def find_builtin_javas(base_dir):
    """扫描启动器内部的 JDK 目录，返回 {大版本号: java.exe/javaw.exe 绝对路径}。
    优先使用 javaw.exe（无控制台窗口），fallback 到 java.exe。
    兼容两种布局：base_dir/runtime 和 base_dir 上级/runtime。
    """
    result = {}
    roots = []
    for b in [base_dir, os.path.dirname(base_dir)]:
        if b:
            roots.append(os.path.join(b, "runtime"))
    seen = set()
    for rt in roots:
        if rt in seen or not os.path.isdir(rt):
            continue
        seen.add(rt)
        try:
            entries = os.listdir(rt)
        except OSError:
            continue
        for d in entries:
            # 优先 javaw.exe（无控制台），没有则用 java.exe
            jexe = os.path.join(rt, d, "bin", "javaw.exe")
            if not os.path.isfile(jexe):
                jexe = os.path.join(rt, d, "bin", "java.exe")
            if not os.path.isfile(jexe):
                continue
            m = re.search(r"(\d+)", d)
            if m:
                major = int(m.group(1))
                # 有多个目录同名版本时，保留已找到的（不重复覆盖）
                result.setdefault(major, jexe)
    return result


def pick_java(available, required_major):
    """选择 JDK：精确匹配优先；没有则取 >= 要求的最低版本。

    两个硬规则（避免"选了也白选"的崩溃）：
    - 绝不选低于 required 的版本（如需要 Java 21 的 1.20.5+ 用 Java 20 必崩
      UnsupportedClassVersionError）；低于要求的场景交给 ensure_java 自动下载。
    - 要求 Java 8 的老版本（FML 老内核）绝不升级到高版本（1.7.10 等用 17/21 必崩），
      无 Java 8 时同样触发按需下载。
    """
    if required_major in available:
        return available[required_major]
    if required_major <= 8:
        return None
    higher = {k: v for k, v in available.items() if k >= required_major}
    if higher:
        return higher[min(higher)]
    return None


def required_java_major(version_data, version_id):
    """读取版本 json 要求的 Java 大版本；json 缺失时按版本号推断。

    推断需覆盖正式版以外的分类（全版本通用）：
    - 远古版 / 早期版本（rd-132211、c0.0.13a、Alpha v1.2.6、Beta 1.7.3、Infdev、Classic）
      → Java 8（老 LWJGL2 natives 不兼容新 Java）
    - 周快照（24w14a、25w14craftmine、21w19a）：按年份/周数推断
      24w 起（1.20.5+ 时代）→ 21；21w19a 起（1.17）→ 17；其余 → 8
    - 愚人节版（Minecraft 2.0、1.RV-Pre1、3D Shareware v1.34）→ Java 8
    - 预发布/候选（1.21.5-pre1、1.20.6-rc1）走常规版本号
    """
    jv = version_data.get("javaVersion")
    if jv and jv.get("majorVersion"):
        return int(jv["majorVersion"])
    vid = str(version_id or "")
    low = vid.lower()
    # 远古版 / 早期版本 → Java 8（含 Alpha/Beta 简写 a1.0.4、b1.8.1）
    if re.match(r"(rd-|c0\.|d0\.|a0\.|alpha|beta|infdev|classic|a\d+\.|b\d+\.)", low):
        return 8
    # 愚人节特殊版本 → Java 8
    if ("rv-pre" in low or low.startswith("3d shareware")
            or re.match(r"minecraft\s*2\.0", low)):
        return 8
    # 周快照（24w14a / 25w14craftmine / 21w19a）→ 按年份+周数
    mw = re.match(r"(\d{2})w(\d{2})[a-z]+", low)
    if mw:
        year, week = int(mw.group(1)), int(mw.group(2))
        if year >= 24:
            return 21          # 24w 起进入 1.20.5+（class 65）
        if year >= 22:
            return 17          # 22w/23w = 1.18.2~1.20 时代
        if year == 21:
            return 17 if week >= 19 else 8   # 21w19a 起是 1.17（class 61）
        return 8               # 21w 之前全部 Java 8
    # 常规版本号（正式版 / 预发布 / 候选）
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", vid)
    if not m:
        return 17
    major, minor = int(m.group(1)), int(m.group(2))
    patch = int(m.group(3) or 0)
    if major == 1:
        if minor <= 16:
            return 8
        if minor == 17:
            return 17
        if minor <= 20 and patch <= 4:
            return 17
        if minor >= 26:
            return 25            # 1.26+（26 系列大版本）→ Java 25
        # 1.20.5+ 官方要求 Java 21（20.5 起 class 版本 65）
        return 21
    if major == 2:
        return 8               # 愚人节 Minecraft 2.0（1.4 架构）
    # 未来大版本（快照/预览）：26+ 按 25 处理（主类编译版本检测会兜底修正）
    return 25 if major >= 26 else 21


# class 文件 major version -> 所需 Java 大版本（52=Java8 ... 69=Java25）
_CLASS_MAJOR_TO_JAVA = {
    45: 1, 46: 2, 47: 3, 48: 4, 49: 5, 50: 6, 51: 7, 52: 8, 53: 9,
    54: 10, 55: 11, 56: 12, 57: 13, 58: 14, 59: 15, 60: 16, 61: 17,
    62: 18, 63: 19, 64: 20, 65: 21, 66: 22, 67: 23, 68: 24, 69: 25,
}


def _read_class_major_in_jar(jar, cls_path):
    """在单个 jar 中定位 .class 并读取 class 文件 major version；找不到返回 None。"""
    try:
        import zipfile
        with zipfile.ZipFile(jar) as z:
            try:
                with z.open(cls_path) as f:
                    head = f.read(8)
            except KeyError:
                return None
        if len(head) < 8 or head[:4] != b"\xca\xfe\xba\xbe":
            return None
        return int.from_bytes(head[6:8], "big")
    except Exception:
        return None


def detect_main_class_java(mc_root, version_data, base_vid):
    """读取主类 .class 的编译版本，返回所需 Java 大版本；找不到返回 None。

    通用兜底：新版 Cleanroom 等自足加载器的主类用新 Java 编译（如 69=Java25），
    而版本 json 没有 javaVersion 字段、按版本号推断又会落到 Java8，导致
    "A JNI error has occurred / UnsupportedClassVersionError"。
    主类可能位于版本 jar 或 libraries 中的某个库 jar（如 Cleanroom 的
    top.outlands.foundation.boot.Foundation 在 loader 库），两处都找。

    结果按 (mc_root, 主类, 版本 jar 路径, jar mtime) 做内存缓存：
    启动器运行期间版本文件不变，重复启动无需重新扫描数千个库 jar
    （每次打开 jar 中央目录约 0.2~1ms，几百个 jar 会白白吃掉数秒启动时间）。
    """
    main_class = version_data.get("mainClass") or "net.minecraft.client.main.Main"
    jar_vid = version_data.get("jar") or base_vid
    jar = os.path.join(mc_root, "versions", jar_vid, jar_vid + ".jar")
    _mtime = 0
    try:
        if os.path.isfile(jar):
            _mtime = int(os.path.getmtime(jar))
    except OSError:
        pass
    _key = (mc_root, main_class, jar, _mtime)
    if _key in _MAIN_CLASS_CACHE:
        return _MAIN_CLASS_CACHE[_key]
    result = _detect_main_class_java_uncached(mc_root, version_data, base_vid)
    _MAIN_CLASS_CACHE[_key] = result
    return result


_MAIN_CLASS_CACHE = {}


def _detect_main_class_java_uncached(mc_root, version_data, base_vid):
    main_class = version_data.get("mainClass") or "net.minecraft.client.main.Main"
    cls_path = main_class.replace(".", "/") + ".class"
    jar_vid = version_data.get("jar") or base_vid
    jar = os.path.join(mc_root, "versions", jar_vid, jar_vid + ".jar")
    if os.path.isfile(jar):
        major = _read_class_major_in_jar(jar, cls_path)
        if major:
            return _CLASS_MAJOR_TO_JAVA.get(major)
    # 主类在库 jar 中：遍历 libraries 目录查找（只打开 jar 的 central directory，较快）
    libs_root = os.path.join(mc_root, "libraries")
    found = None
    if os.path.isdir(libs_root):
        for dp, _, fns in os.walk(libs_root):
            for fn in fns:
                if not fn.endswith(".jar"):
                    continue
                mm = _read_class_major_in_jar(os.path.join(dp, fn), cls_path)
                if mm:
                    found = mm
                    break
            if found:
                break
    return _CLASS_MAJOR_TO_JAVA.get(found) if found else None


def resolve_java_major(mc_root, version_id, version_data, base_vid):
    """综合版本 json 要求与版本 jar 主类编译版本，返回最终所需 Java 大版本。

    取两者最大值：编译版本是硬性下限（低于它必然 UnsupportedClassVersionError），
    json 的 javaVersion / 版本号推断是常规要求。全版本通用，不针对单个加载器。
    """
    req = required_java_major(version_data, version_id)
    det = detect_main_class_java(mc_root, version_data, base_vid)
    if det:
        req = max(req, det)
    return req


def _rule_ok(rules, features=None):
    """评估 library / argument 的加载规则（只看 windows；features 按传入的启用集匹配）。

    Mojang 规则语义：逐个评估，最后一个匹配当前环境（OS/arch/features）的规则
    决定 allow 或 disallow；不匹配的规则直接跳过、不影响结果。
    修复：此前 OS 不匹配（如 macos 专属参数）被误判为 allow，导致
    -XstartOnFirstThread 等 macOS 参数混入 Windows 启动命令。
    """
    features = features or {}
    if not rules:
        return True
    # 标准规则语义：带 rules 的条目默认不应用；只有匹配当前环境（OS/arch/features）
    # 的规则才会更新决定（最后一条匹配者生效）。避免 macOS 专属参数混入 Windows。
    decided = False
    for r in rules:
        feats = r.get("features")
        os_info = r.get("os")
        if feats is not None:
            # features 规则：所有声明的 feature 值与启用集一致才算匹配
            matched = all(bool(features.get(k, False)) == bool(v)
                          for k, v in feats.items())
            if matched:
                decided = (r.get("action") == "allow")
            continue
        if os_info is None:
            decided = (r.get("action") == "allow")
            continue
        name = os_info.get("name")
        if name != "windows":
            # 其他 OS 的规则在 Windows 上不匹配，跳过
            continue
        arch = os_info.get("arch")
        if arch and arch != "x86_64":
            continue
        decided = (r.get("action") == "allow")
    return decided


def _sync_natives_layout(natives_dir, jvm_args):
    """新版启动器（1.20.5+ / 快照）的 JVM 参数会把 natives 分流到子目录：
    -Djava.library.path=${natives_directory}/java
    -Dorg.lwjgl.system.SharedLibraryExtractPath=${natives_directory}/lwjgl
    -Djna.tmpdir=${natives_directory}/jna
    -Dio.netty.native.workdir=${natives_directory}/netty
    把 natives 根目录已解压的 DLL 同步复制到所有被引用的子目录。
    """
    if not os.path.isdir(natives_dir):
        return
    dlls = [f for f in os.listdir(natives_dir)
            if f.lower().endswith((".dll", ".so", ".dylib"))
            and os.path.isfile(os.path.join(natives_dir, f))]
    if not dlls:
        return
    subdirs = set()
    base_norm = os.path.normpath(natives_dir)
    for a in jvm_args:
        if isinstance(a, str) and a.startswith("-D") and "=" in a:
            val = a.split("=", 1)[1]
            # 值指向 natives 目录下子目录（如 .../natives/java）
            p = os.path.normpath(val)
            if p.startswith(base_norm + os.sep):
                subdirs.add(p)
    for sub in subdirs:
        os.makedirs(sub, exist_ok=True)
        for d in dlls:
            dst = os.path.join(sub, d)
            if not os.path.exists(dst):
                try:
                    shutil.copy2(os.path.join(natives_dir, d), dst)
                except OSError:
                    pass


def maven_lib_path(name):
    """把 maven 坐标 group:artifact:version[:classifier][:ext] 转为库相对路径。"""
    parts = (name or "").split(":")
    if len(parts) < 3:
        return None
    g, a, v = parts[0], parts[1], parts[2]
    cls = parts[3] if len(parts) > 3 else ""
    ext = parts[4] if len(parts) > 4 else "jar"
    jar = a + "-" + v + (("-" + cls) if cls else "") + "." + ext
    return "{}/{}/{}/{}".format(
        g.replace(".", "/"), a, v, jar).replace("\\", "/")


def load_version_chain(mc_root, version_id):
    """加载版本 JSON 并合并 inheritsFrom 继承链（Fabric/Forge/NeoForge）。

    返回 (merged_data, base_version_id)：base 是最底层原版版本 id。
    合并规则（子版本覆盖/追加父版本）：
    - libraries: 父 + 子
    - arguments.jvm / game: 父 + 子
    - mainClass/type/jar/minecraftArguments: 子覆盖父
    - assetIndex/assets/logging/javaVersion: 父的为准（子声明了才覆盖）
    """
    chain = []
    vid = version_id
    seen = set()
    while True:
        if vid in seen:
            break
        seen.add(vid)
        vjson = os.path.join(mc_root, "versions", vid, vid + ".json")
        with open(vjson, encoding="utf-8") as f:
            chain.append((vid, json.load(f)))
        parent = chain[-1][1].get("inheritsFrom")
        if not parent:
            break
        vid = parent

    base_vid = chain[-1][0]
    merged = dict(chain[-1][1])
    for vid, data in reversed(chain[:-1]):
        m = dict(merged)
        m["id"] = data.get("id", vid)
        for k in ("mainClass", "type", "jar", "releaseTime"):
            if k in data:
                m[k] = data[k]
        # libraries / arguments 追加
        m["libraries"] = list(merged.get("libraries", [])) + list(data.get("libraries", []))
        args = {}
        for sec in ("jvm", "game"):
            pa = (merged.get("arguments") or {}).get(sec) or []
            ca = (data.get("arguments") or {}).get(sec) or []
            if pa or ca:
                args[sec] = list(pa) + list(ca)
        if args:
            m["arguments"] = args
        if data.get("minecraftArguments"):
            m["minecraftArguments"] = data["minecraftArguments"]
        # 继承字段：父为准，子声明才覆盖
        for k in ("assetIndex", "assets", "logging", "javaVersion", "downloads"):
            if k in data:
                m[k] = data[k]
            elif k in merged:
                m[k] = merged[k]
        merged = m
    return merged, base_vid


def _ensure_default_language(game_dir):
    """默认中文：Minecraft 的语言存在游戏目录 options.txt 的 lang 键里，
    新装版本没有该文件时默认为英文。此处把「英文默认」换成「中文默认」：
    - options.txt 不存在 -> 创建并写入 lang:zh_cn
    - 无 lang 键        -> 追加 lang:zh_cn
    - lang 为 en_us     -> 改为 zh_cn（用户手动选择的其它语言保持不变）
    值统一小写（与设置页「游戏内语言」写入格式一致，Minecraft 语言包文件名全小写）。
    """
    try:
        opt = os.path.join(game_dir, "options.txt")
        txt = None
        if os.path.isfile(opt):
            with open(opt, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
        if txt is None:
            os.makedirs(game_dir, exist_ok=True)
            with open(opt, "w", encoding="utf-8") as f:
                f.write("lang:zh_cn\n")
            return
        out = []
        found = False
        for ln in txt.splitlines():
            if ln.startswith("lang:"):
                found = True
                val = ln.split(":", 1)[1].strip().lower()
                if val in ("", "en_us"):
                    out.append("lang:zh_cn")
                else:
                    out.append(ln)
            else:
                out.append(ln)
        if not found:
            out.append("lang:zh_cn")
        new = "\n".join(out) + "\n"
        if new != txt:
            with open(opt, "w", encoding="utf-8") as f:
                f.write(new)
    except Exception:
        pass  # 语言写入失败不影响启动


def _legacy_java_fixer_needed(merged, version_id):
    """老 Forge（FML ≤ 7.2，即 MC ≤ 1.7.2）在 Java 8+ 下启动必崩：
    FMLInjectionAndSortingTweaker 构造时动态往 Launch.tweakClasses 注册新 tweak，
    launchwrapper 1.9 的迭代器 remove 抛 ConcurrentModificationException（Java 7 不检查、Java 8 严格检查）。
    官方唯一通用解法是 LegacyJavaFixer（mods/legacyjavafixer-1.0.jar，Forge 官方发布）。
    """
    if merged.get("mainClass") != "net.minecraft.launchwrapper.Launch":
        return False
    ma = merged.get("minecraftArguments") or ""
    if "--tweakClass" not in ma:
        return False
    m = re.match(r"^(\d+\.\d+(?:\.\d+)?)", version_id)
    if not m:
        return False
    try:
        t = tuple(int(x) for x in m.group(1).split("."))
    except Exception:
        return False
    return t <= (1, 7, 2)


LEGACY_FIXER_URLS = (
    "https://dist.creeper.host/FTB2/maven/net/minecraftforge/lex/legacyjavafixer/1.0/legacyjavafixer-1.0.jar",
    "https://files.minecraftforge.net/LegacyJavaFixer/legacyjavafixer-1.0.jar",
)


def ensure_legacy_java_fixer(mc_root, merged, version_id):
    """老 Forge（MC ≤ 1.7.2）启动前自动部署 LegacyJavaFixer 到 mods 文件夹；
    已存在且有效（>5KB）则跳过。下载失败不阻塞启动（首次可能无网络）。
    """
    if not _legacy_java_fixer_needed(merged, version_id):
        return
    mods = os.path.join(mc_root, "mods")
    try:
        os.makedirs(mods, exist_ok=True)
    except Exception:
        return
    dst = os.path.join(mods, "legacyjavafixer-1.0.jar")
    if os.path.isfile(dst) and os.path.getsize(dst) > 5000:
        return
    for url in LEGACY_FIXER_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KMCL-Community/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            if len(data) > 5000 and data[:2] == b"PK":
                with open(dst, "wb") as f:
                    f.write(data)
                return
        except Exception:
            continue


def _jar_is_vanilla(path):
    """判断 jar 是否为原版 Minecraft 核心（含 Minecraft 类）。
    1.7.2+ 含 net/minecraft/client/main/Main.class 等；1.5.x/1.6.x 纯混淆名，
    用条目数兜底（原版 ~1500+，老 Forge universal 只有 ~300-900 条 FML 类）。"""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except Exception:
        return False
    if any(n in names for n in (
        "net/minecraft/client/main/Main.class",
        "net/minecraft/server/MinecraftServer.class",
        "net/minecraft/src/Minecraft.class",
        "net/minecraft/client/Minecraft.class",
    )):
        return True
    return len(names) >= 1200


_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_BMCLAPI = "https://bmclapi2.bangbang93.com"


def _fetch_vanilla_json(mc_version):
    """从官方 manifest 取指定原版版本的版本 json（BMCLAPI 镜像兜底）。"""
    try:
        with urllib.request.urlopen(urllib.request.Request(
                _MANIFEST_URL, headers={"User-Agent": "KMCL-Community/1.0"}), timeout=60) as r:
            manifest = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    url = None
    for v in manifest.get("versions", []):
        if v.get("id") == mc_version and v.get("type") == "release":
            url = v.get("url")
            break
    if not url:
        return None
    cands = [url]
    for old in ("https://launchermeta.mojang.com/", "http://launchermeta.mojang.com/"):
        if url.startswith(old):
            cands.append(_BMCLAPI + url[len(old):])
            break
    for u in cands:
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    u, headers={"User-Agent": "KMCL-Community/1.0"}), timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
    return None


def ensure_legacy_vanilla_jar(mc_root, version_id):
    """老 Forge（≤1.7.2 自足格式）版本 jar 必须是【原版核心 jar】副本：
    老 universal jar 只含 FML 类，FML ClassPatchManager 从版本 jar 读原版类失败会 NPE。
    幂等：版本 jar 已是原版则跳过；原版核心缺失时从官方/镜像下载。"""
    vdir = os.path.join(mc_root, "versions", version_id)
    dst = os.path.join(vdir, version_id + ".jar")
    if os.path.isfile(dst) and _jar_is_vanilla(dst):
        return
    m = re.match(r"^(\d+\.\d+(?:\.\d+)?)", version_id)
    if not m:
        return
    mc = m.group(1)
    vmc_dir = os.path.join(mc_root, "versions", mc)
    vjar = os.path.join(vmc_dir, mc + ".jar")
    if not (os.path.isfile(vjar) and _jar_is_vanilla(vjar)):
        vjson_path = os.path.join(vmc_dir, mc + ".json")
        vdata = None
        if os.path.isfile(vjson_path):
            try:
                with open(vjson_path, encoding="utf-8") as f:
                    vdata = json.load(f)
            except Exception:
                vdata = None
        if not vdata:
            vdata = _fetch_vanilla_json(mc)
            if not vdata:
                return
            try:
                os.makedirs(vmc_dir, exist_ok=True)
                with open(vjson_path, "w", encoding="utf-8") as f:
                    json.dump(vdata, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        url = (vdata.get("downloads") or {}).get("client", {}).get("url")
        if not url:
            return
        cands = [url]
        for old in ("https://launchermeta.mojang.com/", "http://launchermeta.mojang.com/",
                    "https://piston-data.mojang.com/"):
            if url.startswith(old):
                cands.append(_BMCLAPI + url[len(old):])
                break
        got = False
        for u in cands:
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        u, headers={"User-Agent": "KMCL-Community/1.0"}), timeout=300) as r:
                    data_b = r.read()
                if len(data_b) > 1000000:
                    with open(vjar, "wb") as f:
                        f.write(data_b)
                    got = True
                    break
            except Exception:
                continue
        if not got or not os.path.isfile(vjar):
            return
    try:
        os.makedirs(vdir, exist_ok=True)
        shutil.copy2(vjar, dst)
    except Exception:
        pass


def _ensure_vanilla_core(mc_root, version_id):
    """自动补齐原版核心（inheritsFrom 基础版本缺失时启动前下载）：
    版本 json + client jar，BMCLAPI 镜像优先。下载失败抛异常（带病启动必崩，不如报错）。
    """
    vdir = os.path.join(mc_root, "versions", version_id)
    vjson = os.path.join(vdir, version_id + ".json")
    if not os.path.isfile(vjson):
        os.makedirs(vdir, exist_ok=True)
        from repair_game import mirror_candidates
        # 版本清单（piston-meta）找该版本的 json URL
        with urllib.request.urlopen(urllib.request.Request(
                "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
                headers={"User-Agent": "KMCL-Community/1.0"}), timeout=60) as r:
            man = json.loads(r.read().decode("utf-8"))
        url = None
        for v in man.get("versions", []):
            if v.get("id") == version_id:
                url = v.get("url")
                break
        if not url:
            raise RuntimeError("版本不存在: %s" % version_id)
        got = False
        for u in mirror_candidates(url):
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        u, headers={"User-Agent": "KMCL-Community/1.0"}), timeout=60) as r:
                    data_b = r.read()
                if data_b.startswith(b"{"):
                    with open(vjson, "wb") as f:
                        f.write(data_b)
                    got = True
                    break
            except Exception:
                continue
        if not got:
            raise RuntimeError("下载版本 json 失败: %s" % version_id)
    # client jar
    with open(vjson, encoding="utf-8") as f:
        data = json.load(f)
    jar_path = os.path.join(vdir, version_id + ".jar")
    if not os.path.isfile(jar_path):
        from repair_game import mirror_candidates
        dl = data.get("downloads", {}).get("client")
        if not dl or not dl.get("url"):
            raise RuntimeError("版本 json 无 client 下载项: %s" % version_id)
        got = False
        for u in mirror_candidates(dl["url"]):
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        u, headers={"User-Agent": "KMCL-Community/1.0"}), timeout=300) as r:
                    data_b = r.read()
                if len(data_b) > 1000000:
                    with open(jar_path, "wb") as f:
                        f.write(data_b)
                    got = True
                    break
            except Exception:
                continue
        if not got or not os.path.isfile(jar_path):
            raise RuntimeError("下载原版 jar 失败: %s" % version_id)


def _ensure_version_chain_cores(mc_root, version_id):
    """沿 inheritsFrom 链检查：基础原版核心（json/jar）缺失时自动补齐。
    加载器（Forge/Fabric/NeoForge）版本只需 json 本身在；原版基础版本
    （如 1.7.10 之于 1.7.10-Forge...）缺失会直接让启动崩，这里兜底补齐。"""
    seen = set()
    vid = version_id
    while vid and vid not in seen:
        seen.add(vid)
        vjson = os.path.join(mc_root, "versions", vid, vid + ".json")
        if not os.path.isfile(vjson):
            break  # 当前链断了，从这一层往下都是缺失的原版核心
        try:
            with open(vjson, encoding="utf-8") as f:
                parent = json.load(f).get("inheritsFrom")
        except Exception:
            break
        if not parent:
            return
        # 检查父级 json 是否存在（jar 可能还没下载）
        pjson = os.path.join(mc_root, "versions", parent, parent + ".json")
        if not os.path.isfile(pjson):
            _ensure_vanilla_core(mc_root, parent)
        vid = parent


def build_launch_command(java_exe, version_id, mc_root, username,
                         jvm_extra=None, game_extra=None,
                         access_token=None, uuid=None, user_type=None,
                         quickplay_server=None, game_dir=None,
                         jvm_agent=None, user_properties=None):
    """组装 Minecraft 启动命令，返回 subprocess 参数列表。

    java_exe : java.exe 绝对路径
    version_id : 版本名（如 1.20.1）
    mc_root   : .minecraft 目录
    username  : 玩家名
    jvm_extra : 额外 JVM 参数（list[str]），如 ["-Xmx2G"]
    game_extra: 额外游戏参数（list[str]）
    access_token / uuid / user_type : 正版登录凭证（微软正版时传入）；None 则离线模式
    quickplay_server : "ip:端口"，1.20+ 启动时自动连接该服务器（Quick Play）
    game_dir  : 版本隔离时的游戏工作目录（存档/模组/资源包都放这里）；
                None 则直接使用 mc_root
    jvm_agent : JVM agent 字符串（如 "-javaagent:C:/.../authlib-injector.jar=https://littleskin.cn/api/yggdrasil"），
                会被加到 jvm_args 最前。LittleSkin 等第三方登录需要。
    user_properties : --userProperties 的 JSON 字符串（旧版皮肤注入用）。None 则用 "{}"。
    """
    # 版本链上缺失的原版核心（inheritsFrom 基础版本）启动前自动补齐：
    # 装加载器后原版目录为空也能直接启动，无需玩家先手动装原版
    _ensure_version_chain_cores(mc_root, version_id)
    # 老 FML 的 setupHome 需要 launcher_profiles.json（幂等）
    _ensure_launcher_profiles(mc_root)
    # 合并 inheritsFrom 继承链（Fabric/Forge/NeoForge 安装的版本）
    data, base_vid = load_version_chain(mc_root, version_id)
    base_vdir = os.path.join(mc_root, "versions", base_vid)
    # 老 Forge（FML ≤ 7.2，MC ≤ 1.7.2）在 Java 8 下必崩 ConcurrentModificationException：
    # 启动前确保 mods/legacyjavafixer-1.0.jar 存在（Forge 官方 LegacyJavaFixer 修复）
    ensure_legacy_java_fixer(mc_root, data, version_id)

    # ---- classpath：版本 jar + 全部可用 libraries（排除 natives，按路径去重）----
    _LOG_GROUPS = {"org.apache.logging.log4j", "org.slf4j"}

    def _ver_nums(v):
        return [int(x) for x in re.findall(r"\d+", v or "")]

    def _ver_cmp(a, b):
        na, nb = _ver_nums(a), _ver_nums(b)
        for x, y in zip(na, nb):
            if x != y:
                return 1 if x > y else -1
        return len(na) - len(nb)

    _mc = (data.get("mainClass") or "").lower()
    _cleanroom = any(k in _mc for k in ("outlands", "foundation", "cleanroom"))
    # LWJGL3 内核（org.lwjgl:lwjgl:3.x 或 Cleanroom）：natives jar 必须留在 classpath，
    # 由 LWJGL3 的 SharedLibraryLoader 自动从 jar 解压加载 dll；老 LWJGL2 才需要
    # 排除 natives 并单独解压到 -Djava.library.path 目录。
    is_lwjgl3 = _cleanroom or any(
        (l.get("name") or "").startswith("org.lwjgl:lwjgl:3")
        for l in data.get("libraries", [])
        if _rule_ok(l.get("rules"))
    )
    lib_entries = []
    seen_lib = set()
    for lib in data.get("libraries", []):
        if not _rule_ok(lib.get("rules")):
            continue
        if ":natives-" in lib.get("name", "") and not is_lwjgl3:
            continue
        art = lib.get("downloads", {}).get("artifact", {})
        path = art.get("path") or maven_lib_path(lib.get("name", ""))
        if not path:
            continue
        lp = os.path.join(mc_root, "libraries", path)
        nkey = os.path.normcase(os.path.normpath(lp))
        if nkey in seen_lib:
            continue
        if os.path.isfile(lp):
            seen_lib.add(nkey)
            lib_entries.append((lib.get("name", ""), lp))
    # 基础库家族同 artifact 多版本时保留最新（log4j 2.26 与 MC 老版本自带 2.8.1 冲突时，
    # 老版本会被优先加载导致 NoSuchMethodError；gson/guava/netty/commons 同理）。
    # 这些库新版本对旧 API 完全向后兼容，以新替旧属通用治理；asm/fastutil 等版本敏感的
    # 库保持原样，避免破坏老 coremod 依赖。
    _SAFE_LATEST_GROUPS = {
        "org.apache.logging.log4j", "org.slf4j",
        "com.google.code.gson", "com.google.guava",
        "io.netty", "org.apache.commons",
        "commons-io", "commons-codec", "commons-logging",
        # JNA 5.x 向后兼容 4.x（Native.load(String, Class) 等新签名只有 5.x 有），
        # 原版老 json 自带 jna 4.4.0，Cleanroom 等加载器依赖 5.x，取新避免
        # NoSuchMethodError（com.sun.jna.Native.load）。
        "net.java.dev.jna",
    }
    dedup = {}
    for name, lp in lib_entries:
        parts = (name or "").split(":")
        if len(parts) >= 3 and parts[0] in _SAFE_LATEST_GROUPS:
            key = parts[0] + ":" + parts[1]
            # JNA 老包名 net.java.dev.jna:platform 与新版 jna-platform 是同一组类
            # （com.sun.jna.platform.*），按同一 artifact 取最新，避免旧 3.4.0 的
            # Guid$GUID 等缺新构造函数（NoSuchMethodError）。
            if parts[0] == "net.java.dev.jna" and parts[1] in ("platform", "jna-platform"):
                key = "net.java.dev.jna:jna-platform"
            if key not in dedup or _ver_cmp(parts[2], dedup[key][0]) > 0:
                dedup[key] = (parts[2], lp)
        else:
            dedup.setdefault("@" + lp, ("", lp))
    libs = [v[1] for v in dedup.values()]
    _ensure_fml_lzma(mc_root, data, libs)
    _ensure_fml_vecmath(mc_root, data, libs)
    # Cleanroom（LWJGL3 内核）：官方 build.gradle 明确 exclude group 'org.lwjgl.lwjgl'，
    # 版本 jar 的 Minecraft 类已被 patch 改写为 LWJGL3 API。移除原版 LWJGL2 库，
    # 避免 org.lwjgl.Sys 在 Java 25 上加载旧 dll 崩溃（NoSuchMethodError: getPointer）。
    _mc = (data.get("mainClass") or "").lower()
    if any(k in _mc for k in ("outlands", "foundation", "cleanroom")):
        # LWJGL2 maven 路径为 org/lwjgl/lwjgl/lwjgl|_util|-platform/（group org.lwjgl.lwjgl）；
        # LWJGL3 是 org/lwjgl/lwjgl/3.4.1/（group org.lwjgl），三节 lwjgl 前缀才匹配 LWJGL2
        _lwjgl2_marker = "org/lwjgl/lwjgl/lwjgl"
        libs = [lp for lp in libs if _lwjgl2_marker not in lp.replace("\\", "/")]
    # 版本 jar 用继承链底层（原版）的；子版本可声明 "jar" 指定
    jar_vid = data.get("jar") or base_vid
    jar = os.path.join(mc_root, "versions", jar_vid, jar_vid + ".jar")
    # 老 Forge（≤1.7.2 自足格式）：版本 jar 必须是原版核心（universal 不含 Minecraft 类，
    # FML ClassPatchManager 读不到原版类会 NPE）。缺失/错误时自动补原版核心（幂等）。
    if _legacy_java_fixer_needed(data, version_id):
        ensure_legacy_vanilla_jar(mc_root, version_id)

    # 检测 BootstrapLauncher 模块启动模式（Forge 1.16+ / NeoForge）：jvm 含 -p 与 ALL-MODULE-PATH。
    # 此模式下 minecraft 由 modlauncher 从 libraries 的 client-slim/srg/extra 构建为模块，
    # 原版 client jar 绝不能进 classpath，否则会被模块化并与 minecraft 模块 split package
    # （ResolutionException: Module minecraft contains package ..., module _x._x._x exports ...）
    flat_jvm = []
    for _it in (data.get("arguments") or {}).get("jvm", []):
        if isinstance(_it, str):
            flat_jvm.append(_it)
        elif isinstance(_it, dict):
            _v = _it.get("value")
            if isinstance(_v, str):
                flat_jvm.append(_v)
            elif isinstance(_v, list):
                flat_jvm.extend(x for x in _v if isinstance(x, str))
    bootstrap_mode = ("-p" in flat_jvm or "--module-path" in flat_jvm) and "ALL-MODULE-PATH" in flat_jvm

    if not bootstrap_mode and not os.path.isfile(jar):
        raise FileNotFoundError(f"找不到版本 jar：{jar}")
    classpath = os.pathsep.join(libs if bootstrap_mode else ([jar] + libs))

    # natives 目录也用原版版本的（加载器版本目录里没有解压好的 DLL）
    natives_dir = os.path.join(base_vdir, "natives")
    assets_root = os.path.join(mc_root, "assets")
    asset_index = data.get("assetIndex", {}).get("id", "legacy")
    main_class = data.get("mainClass", "net.minecraft.client.main.Main")
    version_type = data.get("type", "release")

    subs = {
        "${natives_directory}": natives_dir,
        "${library_directory}": os.path.join(mc_root, "libraries"),
        "${classpath_separator}": os.pathsep,
        "${launcher_name}": "KmclLauncher",
        "${launcher_version}": "1.0",
        "${classpath}": classpath,
        "${auth_player_name}": username,
        "${version_name}": version_id,
        "${game_directory}": game_dir or mc_root,
        "${assets_root}": assets_root,
        "${game_assets}": assets_root,
        "${assets_index_name}": asset_index,
        "${auth_uuid}": uuid or "00000000-0000-0000-0000-000000000000",
        "${auth_access_token}": access_token or "0",
        "${user_type}": user_type or "legacy",
        "${version_type}": version_type,
        "${resolution_width}": "854",
        "${resolution_height}": "480",
        # Quick Play 占位：未使用时用哨兵值成对删除旗标，避免留下无值的 --quickPlayXxx
        "${quickPlayPath}": "\x00",
        "${quickPlaySingleplayer}": "\x00",
        "${quickPlayRealms}": "\x00",
        "${quickPlayMultiplayer}": quickplay_server or "\x00",
        "${clientid}": "0",
        "${auth_xuid}": "0",
        "${user_properties}": user_properties or "{}",
    }
    # 联机自动连接时向版本 JSON 声明 quick play feature
    rule_features = {"is_quick_play_multiplayer": True} if quickplay_server else None

    def resolve_items(item):
        """把版本 JSON 的 argument 项展开为字符串列表（支持 str/list/dict 嵌套）。"""
        if isinstance(item, str):
            s = item
            for k, v in subs.items():
                s = s.replace(k, v)
            return [s] if s != "" else []
        if isinstance(item, dict):
            if _rule_ok(item.get("rules"), rule_features):
                return resolve_items(item.get("value", ""))
            return []
        if isinstance(item, list):
            out = []
            for x in item:
                out.extend(resolve_items(x))
            return out
        return []

    # ---- JVM 参数 ----
    jvm_args = []
    args_data = data.get("arguments")
    if args_data and args_data.get("jvm"):
        for item in args_data["jvm"]:
            jvm_args.extend(resolve_items(item))
    # 确保有 -cp/-classpath（有的 json 没有显式 classpath 参数）
    if not any(a in ("-cp", "-classpath") for a in jvm_args):
        jvm_args += ["-cp", classpath]
    # 版本 json 自带的堆内存参数（-Xmx/-Xms/-XX:MaxHeapSize）必须移除：
    # Java 命令行重复参数「后者生效」，json 的堆参数排在我们注入的界面内存设置之后，
    # 会反向覆盖玩家在启动器里设的内存，造成"设了没用"。堆内存唯一来源 = 界面设置。
    jvm_args = [a for a in jvm_args
                if not (isinstance(a, str) and
                        (a.startswith("-Xmx") or a.startswith("-Xms")
                         or a.startswith("-XX:MaxHeapSize")))]
    if jvm_extra:
        jvm_args = jvm_extra + jvm_args
    # 老版本 json 无 jvm 参数定义（1.12.2 及以前）：仅当最终命令完全没有堆设置时
    # 才补默认值；绝不能无条件追加 -Xmx，否则它会排在用户参数之后，
    # 被 Java「后值覆盖」规则反向压制，导致界面内存设置失效。
    if not any(str(a).startswith(("-Xmx", "-XX:MaxHeapSize")) for a in jvm_args):
        jvm_args = ["-Xmx2G"] + jvm_args
    # authlib-injector 等 JVM agent 必须作为 JVM 参数传入（放在最前）
    if jvm_agent:
        jvm_args = [jvm_agent] + jvm_args

    # ---- 新版 natives 子目录布局同步（java.library.path=/java 等）----
    if os.path.isdir(natives_dir):
        _sync_natives_layout(natives_dir, jvm_args)

    # ---- 老版本（1.12.2 及更早，json 无 arguments.jvm）补必需 JVM 参数 ----
    # 官方启动器 / HMCL 对老版本固定补 -Djava.library.path（LWJGL2 靠它找 lwjgl64.dll）
    # 与 -Dminecraft.launcher.brand/version；新版 json 自带（占位符已替换），不会重复。
    if not any(str(a).startswith("-Djava.library.path=") for a in jvm_args):
        jvm_args.append("-Djava.library.path=%s" % natives_dir)
    if not any(str(a).startswith("-Dminecraft.launcher.brand=") for a in jvm_args):
        jvm_args.append("-Dminecraft.launcher.brand=KmclLauncher")
    if not any(str(a).startswith("-Dminecraft.launcher.version=") for a in jvm_args):
        jvm_args.append("-Dminecraft.launcher.version=1.0")
    # 老 Forge（MC ≤ 1.7.2）FML 7.x 的 sanity check 在 Java8+ 误判版本 jar 的
    # Mojang 签名（ClientBrandRetriever "appears to be corrupt"）并拒绝启动：
    # "For your safety, FML will not launch minecraft... add the flag
    #  -Dfml.ignoreInvalidMinecraftCertificates=true"。官方 EAQ / HMCL 老版本惯例
    # 均自动加该 flag 跳过校验继续启动（否则日志只有阻断行、游戏永远起不来）。
    if _legacy_java_fixer_needed(data, version_id):
        if not any(str(a).startswith("-Dfml.ignoreInvalidMinecraftCertificates") for a in jvm_args):
            jvm_args.append("-Dfml.ignoreInvalidMinecraftCertificates=true")

    # ---- 游戏参数 ----
    game_args = []
    if args_data and args_data.get("game"):
        for item in args_data["game"]:
            game_args.extend(resolve_items(item))
    elif data.get("minecraftArguments"):
        for tok in data["minecraftArguments"].split():
            game_args.extend(resolve_items(tok))
    # ---- 清理未使用的 Quick Play 占位（哨兵值与前面的 --quickPlayXxx 成对删除）----
    cleaned = []
    for a in game_args:
        if a == "\x00":
            if cleaned and str(cleaned[-1]).startswith("--quickPlay"):
                cleaned.pop()
            continue
        cleaned.append(a)
    game_args = cleaned
    if game_extra:
        game_args += game_extra

    # 默认中文：启动前确保游戏目录 options.txt 语言为 zh_CN
    _ensure_default_language(game_dir or mc_root)

    return [java_exe] + jvm_args + [main_class] + game_args


# =====================================================================
# 按需 Java：优先用系统已安装的 JDK；没有则自动下载到用户目录（%LOCALAPPDATA%\KMCL\jdk）
# =====================================================================

def _java_major_of_dir(jdir):
    """从 JDK 目录的 release 文件解析大版本（如 1.8.0_442 -> 8，17.0.13 -> 17）。"""
    rel = os.path.join(jdir, "release")
    if os.path.isfile(rel):
        try:
            with open(rel, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
            m = re.search(r'JAVA_VERSION="([^"]+)"', txt)
            if m:
                v = m.group(1)
                mm = re.match(r"(\d+)", v)
                if mm:
                    major = int(mm.group(1))
                    if major == 1:
                        parts = v.split(".")
                        if len(parts) >= 2 and parts[1].isdigit():
                            return int(parts[1])
                    return major
        except Exception:
            pass
    return None


def find_system_javas():
    """扫描系统已安装的 Java（安装目录 + 注册表 + JAVA_HOME + 常见安装目录）。

    返回 {大版本: java.exe 绝对路径}。不 spawn 进程，读 release 文件判定版本。

    优先扫描启动器安装目录（%ProgramFiles%\\KMCL\\jdk）：无论启动器重装到哪个
    位置，只要 JDK 装进了系统目录就一定能被发现（该路径与启动器自身位置无关）。
    """
    found = {}
    try:
        import winreg
    except ImportError:
        winreg = None
    # 1) 启动器按需安装的 JDK（%ProgramFiles%\KMCL\jdk 或回退用户目录）——最高优先
    try:
        store = _jdk_store_root()
        if os.path.isdir(store):
            for d in os.listdir(store):
                exe = os.path.join(store, d, "bin", "java.exe")
                if os.path.isfile(exe):
                    mj = _java_major_of_dir(os.path.join(store, d))
                    if mj:
                        found.setdefault(mj, exe)
    except Exception:
        pass
    # 2) 注册表 HKCU / HKLM 的 JavaSoft\JDK（新版 JDK 安装器写入）
    if winreg:
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                k = winreg.OpenKey(hive, r"SOFTWARE\JavaSoft\JDK")
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(k, i)
                        i += 1
                    except OSError:
                        break
                    mm = re.match(r"(\d+)", name)
                    if not mm:
                        continue
                    try:
                        sub = winreg.OpenKey(k, name)
                        home, _ = winreg.QueryValueEx(sub, "JavaHome")
                    except OSError:
                        continue
                    exe = os.path.join(home, "bin", "java.exe")
                    if os.path.isfile(exe):
                        found.setdefault(int(mm.group(1)), exe)
            except OSError:
                pass
    # 3) JAVA_HOME 环境变量
    jh = os.environ.get("JAVA_HOME", "")
    if jh:
        exe = os.path.join(jh, "bin", "java.exe")
        if os.path.isfile(exe):
            mj = _java_major_of_dir(jh)
            if mj:
                found.setdefault(mj, exe)
    # 3) 常见安装目录（Java / Eclipse Adoptium / Microsoft / Zulu / Corretto）
    pf_dirs = [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]
    for base in pf_dirs:
        if not base:
            continue
        for parent in ("Java", "Eclipse Adoptium", "Microsoft", "Zulu", "Amazon Corretto"):
            p = os.path.join(base, parent)
            if not os.path.isdir(p):
                continue
            try:
                entries = os.listdir(p)
            except OSError:
                continue
            for d in entries:
                exe = os.path.join(p, d, "bin", "java.exe")
                if os.path.isfile(exe):
                    mj = _java_major_of_dir(os.path.join(p, d))
                    if mj:
                        found.setdefault(mj, exe)
    return found


def _adoptium_assets(major):
    """查 Adoptium API 拿最新 JDK（windows x64 hotspot）资产列表。"""
    api = ("https://api.adoptium.net/v3/assets/latest/%d/hotspot"
           "?os=windows&arch=x64&image_type=jdk" % major)
    req = urllib.request.Request(api, headers={"User-Agent": "KMCL-Community/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _tuna_jdk_url(major):
    """直接从清华镜像目录列表解析最新 JDK zip 下载地址（不依赖 Adoptium API）。

    目录结构：https://mirrors.tuna.tsinghua.edu.cn/Adoptium/{major}/jdk/x64/windows/
    文件名如 OpenJDK17U-jdk_x64_windows_hotspot_17.0.13_11.zip（按版本号解析取最新）。
    """
    base = "https://mirrors.tuna.tsinghua.edu.cn/Adoptium/%d/jdk/x64/windows/" % major
    req = urllib.request.Request(base, headers={"User-Agent": "KMCL-Community/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    names = re.findall(r'OpenJDK\d+U-jdk_x64_windows_hotspot_[^"<>\s]+\.zip', html)
    if not names:
        return None

    def _ver_key(name):
        # 8u504b01 -> (8,504,1)；17.0.20.1_1 -> (17,0,20,1,1)
        m = re.search(r"hotspot_([^/]+)\.zip$", name)
        if not m:
            return (0,)
        return tuple(int(x) for x in re.findall(r"\d+", m.group(1)))

    best = max(names, key=_ver_key)
    return base + best


def jdk_download_urls(major):
    """JDK {major} 下载地址候选：只走清华镜像（用户指定），官方源一律不用。

    - 首选：清华镜像目录列表直接解析最新 zip（不依赖国外 API/下载源）
    - 兜底：Adoptium API 仅查文件名元数据（小请求），仍拼清华镜像地址
    """
    urls = []
    try:
        t = _tuna_jdk_url(major)
        if t:
            urls.append(t)
    except Exception:
        pass
    if not urls:
        try:
            assets = _adoptium_assets(major)
            for a in assets:
                pkg = (a.get("binary") or {}).get("package") or {}
                name = pkg.get("name") or ""
                if name.endswith(".zip"):
                    urls.append("https://mirrors.tuna.tsinghua.edu.cn/Adoptium/%d/jdk/x64/windows/%s"
                                % (major, name))
                    break
        except Exception:
            pass
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _jdk_store_root():
    """JDK 安装位置：系统目录 %ProgramFiles%\\KMCL\\jdk（写入系统注册表）。

    写入 Program Files 需要管理员权限；无权限时自动回退用户目录
    %LOCALAPPDATA%\\KMCL\\jdk（同样写入用户级注册表，系统检测仍能识别）。
    """
    for base in (os.environ.get("ProgramFiles", ""),
                 os.environ.get("ProgramFiles(x86)", "")):
        if not base:
            continue
        cand = os.path.join(base, "KMCL", "jdk")
        try:
            os.makedirs(cand, exist_ok=True)
            probe = os.path.join(cand, ".w")
            with open(probe, "w") as f:
                f.write("1")
            os.remove(probe)
            return cand
        except Exception:
            continue
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "KMCL", "jdk")


def _register_jdk(major, home):
    """把下载的 JDK 注册到系统 JavaSoft\\JDK（HKLM 优先，失败用 HKCU）。

    与官方 JDK 安装器写同一位置，注册后系统的 Java 检测
    （启动器注册表扫描 / 其它工具）都能识别为"已安装 Java"。
    """
    try:
        import winreg
    except ImportError:
        return False
    key_path = r"SOFTWARE\JavaSoft\JDK" + "\\" + str(major)
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            k = winreg.CreateKeyEx(hive, key_path, 0,
                                   winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY)
            winreg.SetValueEx(k, "JavaHome", 0, winreg.REG_SZ, home)
            winreg.SetValueEx(k, "RuntimeLib", 0, winreg.REG_SZ,
                              os.path.join(home, "bin", "server", "jvm.dll"))
            k.Close()
            return True
        except Exception:
            continue
    return False


def _stored_jdk_exe(major):
    """在安装目录下找已下载的 JDK{major}（目录名带版本号，如 jdk-25.0.4.1+1）。"""
    store = _jdk_store_root()
    if not os.path.isdir(store):
        return None
    try:
        entries = os.listdir(store)
    except OSError:
        return None
    for d in entries:
        exe = os.path.join(store, d, "bin", "java.exe")
        if os.path.isfile(exe) and _java_major_of_dir(os.path.join(store, d)) == major:
            return exe
    return None


def ensure_java(required_major, base_dir, progress=None, cancel=None):
    """按需获取指定大版本的 java.exe（启动/安装加载器共用）。

    顺序：
      1. 系统已安装（注册表 / JAVA_HOME / 常见目录 / 已下载安装的 JDK）且大版本满足要求
      2. 都没有 -> 自动下载对应 JDK 到系统目录（%ProgramFiles%\\KMCL\\jdk），
         解压后注册到系统 JavaSoft\\JDK，仅首次下载，之后系统检测直接复用。

    progress 回调：progress("文本…") 阶段提示；progress(done, total) 下载进度。
    cancel 可调用对象：返回 True 则中止下载。
    返回 java.exe 绝对路径。
    """
    avail = find_system_javas()
    builtin = find_builtin_javas(base_dir)
    for k, v in builtin.items():
        avail.setdefault(k, v)
    if avail:
        chosen = pick_java(avail, required_major)
        if chosen and os.path.isfile(chosen):
            return chosen
    # 需要下载
    if progress:
        progress("未检测到系统 Java %d，正在自动下载到系统并注册（仅首次）…" % required_major)
    store = _jdk_store_root()
    stored = _stored_jdk_exe(required_major)
    if stored:
        return stored
    urls = jdk_download_urls(required_major)
    if not urls:
        raise RuntimeError("无法获取 JDK %d 下载地址，请检查网络后重试" % required_major)
    os.makedirs(store, exist_ok=True)
    zip_path = os.path.join(store, "jdk%d.zip" % required_major)
    got = False
    last_err = None
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "KMCL-Community/1.0"})
            with urllib.request.urlopen(req, timeout=600) as r:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                with open(zip_path, "wb") as f:
                    while True:
                        if cancel and cancel():
                            raise RuntimeError("已取消下载")
                        chunk = r.read(262144)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            got = True
            break
        except Exception as e:
            last_err = e
            try:
                if os.path.isfile(zip_path):
                    os.remove(zip_path)
            except Exception:
                pass
            continue
    if not got:
        raise RuntimeError("JDK %d 下载失败：%s" % (required_major, last_err or "网络错误"))
    # 解压（zip 顶层是 jdk-8u442-b06 / jdk-17.0.13+11 之类单目录，找 bin/java.exe）
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(store)
    except Exception as e:
        raise RuntimeError("JDK %d 解压失败：%s" % (required_major, e))
    finally:
        try:
            os.remove(zip_path)
        except Exception:
            pass
    found = None
    try:
        entries = os.listdir(store)
    except OSError:
        entries = []
    for d in entries:
        cand = os.path.join(store, d, "bin", "java.exe")
        if os.path.isfile(cand):
            found = cand
            break
    if not found:
        raise RuntimeError("JDK %d 解压后未找到 java.exe" % required_major)
    # 统一目录名为固定格式 jdk{major}（如 jdk25），方便识别与后续复用：
    # 无论 zip 内顶层目录叫什么版本号，都改名为 jdk25
    std_dir = os.path.join(store, "jdk%d" % required_major)
    src_dir = os.path.dirname(os.path.dirname(found))
    if os.path.normpath(src_dir) != os.path.normpath(std_dir):
        if os.path.isdir(std_dir):
            try:
                shutil.rmtree(std_dir)
            except OSError:
                pass
        try:
            os.rename(src_dir, std_dir)
            found = os.path.join(std_dir, "bin", "java.exe")
        except OSError:
            pass  # 改名失败不影响使用，保留原目录名
    # 注册到系统 JavaSoft\JDK（HKLM 优先，无管理员权限则 HKCU），
    # 之后系统 Java 检测直接命中，无需重复下载
    _register_jdk(required_major, os.path.dirname(os.path.dirname(found)))
    return found
