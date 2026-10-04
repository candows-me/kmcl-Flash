# -*- coding: utf-8 -*-
"""KMCL 社区维护版 - 资源中文名映射表（离线，无网络依赖）。

搜索/列表条目渲染时把 Modrinth 英文资源名翻译为社区通用中文名：
  条目格式 = 英文名 + 大小 + 中文名（如 "Sodium  3.1 MB  钠"）
未命中映射的资源保持英文原名显示（可随时在此补充）。

key 统一用 Modrinth slug（小写英文标识，如 "sodium"）。
value = (中文名, 中文简介)；简介留空则回退英文描述。
"""

MOD_ZH = {
    # ---- 性能优化 ----
    "sodium": ("钠", "高性能渲染引擎，大幅提升帧率"),
    "iris": ("虹", "基于钠的高性能光影加载器"),
    "lithium": ("锂", "通用逻辑性能优化，降低卡顿"),
    "phosphor": ("磷", "光照引擎优化，提升光照计算速度"),
    "ferritecore": ("铁氧体核心", "大幅降低内存占用"),
    "krypton": ("氪", "网络协议栈优化，降低带宽占用"),
    "lazydfu": ("懒DFU", "延迟加载数据修复器，加快启动"),
    "starlight": ("星光", "新一代光照引擎，性能更强"),
    "canary": ("金丝雀", "实体AI与寻路性能优化"),
    "very-many-players": ("海量玩家", "多人服务器卡顿专项优化"),
    "modernfix": ("现代修复", "全方面修复性能与内存问题"),
    "memoryleakfix": ("内存泄漏修复", "修复多处内存泄漏"),
    "smoothboot": ("平滑启动", "均衡启动与资源占用"),
    "cull-leaves": ("树叶剔除", "剔除多余树叶渲染"),
    "entityculling": ("实体剔除", "剔除视野外实体渲染"),
    "fastanim": ("快速动画", "加速实体动画计算"),
    "enhancedblockentities": ("增强方块实体", "更高效的箱子/告示牌渲染"),
    "dynamic-fps": ("动态帧率", "窗口失焦自动降低帧率"),
    "immediatelyfast": ("立刻快", "即时渲染性能优化"),
    "noisium": ("噪声优化", "世界生成性能优化"),
    "hydrogen": ("氢", "内存优化（旧版）"),
    "exordium": ("序章", "界面渲染降采样，提升帧率"),
    "embeddium": ("铟", "钠的 Forge 移植（旧）"),
    "oculus": ("眼", "Forge 光影加载器（旧）"),
    "rubidium": ("铷", "Forge 版钠移植（旧）"),
    "magnesium": ("镁", "旧版渲染优化"),
    "fastfurnace": ("快速熔炉", "加速熔炉逻辑"),
    "fastworkbench": ("快速工作台", "加速工作台逻辑"),
    "satin": ("缎面", "Fabric 渲染库前置"),

    # ---- 前置库 / API ----
    "fabric-api": ("织物API", "Fabric 模组核心前置"),
    "quilt-loader": ("被子加载器", "Quilt 加载器"),
    "quilted-fabric-api": ("织物API（Quilt版）", "Quilt 版 Fabric API"),
    "cloth-config": ("布料配置", "配置界面前置库"),
    "modmenu": ("模组菜单", "管理查看已安装模组"),
    "architectury": ("建筑师API", "跨加载器开发前置"),
    "balm": ("香脂", "跨加载器前置库"),
    "owo-lib": ("嗷呜库", "UI 与工具前置库"),
    "yacl": ("又一个配置库", "现代配置界面前置"),
    "iceberg": ("冰山", "前置库"),
    "fusion": ("融合", "连接纹理前置"),
    "midnightlib": ("午夜库", "配置前置库"),
    "trinkets": ("饰品", "饰品栏前置"),
    "curios": ("好奇API", "饰品栏前置（Forge）"),
    "cardinal-components": ("主要组件", "数据同步组件前置"),
    "patchouli": ("帕秋莉手册", "模组指南书框架"),
    "forge-config-api-port": ("配置API移植", "Forge 配置 API 的 Fabric 移植"),
    "connector": ("辛尼加连接器", "在 Fabric 运行部分 Forge 模组"),

    # ---- 物品 / 界面 ----
    "jei": ("JEI物品管理器", "物品合成配方查询"),
    "just-enough-items": ("JEI物品管理器", "物品合成配方查询"),
    "roughly-enough-items": ("REI物品管理器", "物品配方查询"),
    "emi": ("EMI物品管理器", "新一代物品配方查询"),
    "jade": ("玉", "查看方块信息与进度"),
    "wthit": ("这是啥", "查看方块信息"),
    "appleskin": ("苹果皮", "显示饥饿值与饱和度"),
    "neat": ("简洁血量条", "实体头顶血量条"),
    "mouse-tweaks": ("鼠标手势", "便捷拖拽物品"),
    "controlling": ("按键冲突控制", "一键查找并解决按键冲突"),
    "inventory-profiles-next": ("物品栏整理", "一键整理/转移物品"),
    "toast-control": ("提示控制", "管理成就/提示弹窗"),
    "betterf3": ("更好的F3", "F3 调试界面美化分组"),
    "dark-loading-screen": ("深色加载界面", "深色加载背景"),
    "no-chat-reports": ("移除聊天举报", "禁用聊天举报功能"),
    "chat-heads": ("聊天头像", "聊天消息显示玩家头像"),
    "damage-indicators": ("伤害指示器", "显示伤害数值"),

    # ---- 地图 / 世界 ----
    "xaeros-minimap": ("Xaero小地图", "经典小地图模组"),
    "xaeros-world-map": ("Xaero世界地图", "世界大地图"),
    "journeymap": ("旅行地图", "多功能地图，支持网页查看"),
    "map-atlases": ("地图集", "可制作合成的地图册"),

    # ---- 科技 / 大型模组 ----
    "create": ("机械动力", "机械建造与自动化科技"),
    "create-fabric": ("机械动力（Fabric）", "机械建造与自动化科技"),
    "applied-energistics-2": ("应用能源2", "物品存储与自动化网络"),
    "ae2": ("应用能源2", "物品存储与自动化网络"),
    "mekanism": ("通用机械", "大型科技/能源模组"),
    "thermal-foundation": ("热力基础", "热力系列基础"),
    "thermal-expansion": ("热力膨胀", "机器与自动化"),
    "immersive-engineering": ("沉浸工程", "多方块工业机器"),
    "industrial-foregoing": ("工业先锋", "自动化工业机器"),
    "draconic-evolution": ("龙之研究", "顶级装备与能量存储"),
    "projecte": ("等价交换", "EMC 物质转换系统"),
    "tinkers-construct": ("匠魂", "自定义工具铸造系统"),
    "mantle": ("地幔", "匠魂系列前置库"),
    "botania": ("植物魔法", "自然魔法主题模组"),
    "blood-magic": ("血魔法", "血祭魔法体系"),
    "ender-io": ("末影接口", "管道与传送科技"),
    "big-reactors": ("大型反应堆", "多方块核反应堆"),
    "nuclearcraft": ("核工艺", "核能与辐射科技"),
    "gregtech": ("格雷科技", "硬核工业科技"),
    "refined-storage": ("精致存储", "数字物品存储网络"),

    # ---- 农业 / 食物 ----
    "farmers-delight": ("农夫乐事", "美食烹饪与农业"),
    "croptopia": ("作物盛景", "大量新作物与食物"),
    "sereneseasons": ("静谧季节", "四季变换系统"),
    "simplefarming": ("简单农业", "轻量农业扩展"),

    # ---- 冒险 / 世界生成 ----
    "terralith": ("大地之旅", "全新地形与生物群系"),
    "biomes-o-plenty": ("缤纷生物群系", "大量新生物群系"),
    "oh-the-biomes-weve-gone": ("哦这离去的生物群系", "新生物群系扩展"),
    "dungeons-arise": ("地牢崛起", "丰富的新地牢结构"),
    "yungs-api": ("杨的API", "地牢增强系列前置"),
    "yungs-better-mineshafts": ("更好的矿洞", "更精良的废弃矿洞"),
    "yungs-better-strongholds": ("更好的要塞", "更精良的末地要塞"),
    "yungs-better-dungeons": ("更好的地牢", "更精良的地牢"),
    "yungs-better-desert-temples": ("更好的沙漠神殿", "更精良的沙漠神殿"),
    "alexs-mobs": ("亚历克斯的生物", "丰富有趣的野生生物"),
    "alexs-caves": ("亚历克斯的洞穴", "全新地下洞穴生态"),
    "quark": ("夸克", "大量细节与内容增强"),
    "supplementaries": ("补给", "实用细节装饰增强"),
    "chipped": ("碎裂", "方块建材变体扩展"),
    "handcrafted": ("手工", "手工家具与装饰"),

    # ---- 装饰 / 建筑 ----
    "macaws-bridges": ("麦克的桥", "精美桥梁方块"),
    "macaws-doors": ("麦克的门", "多样门样式"),
    "macaws-furniture": ("麦克的家具", "丰富家具套装"),
    "macaws-roofs": ("麦克的屋顶", "屋顶建材系列"),
    "macaws-trapdoors": ("麦克的活板门", "多样活板门"),
    "macaws-windows": ("麦克的窗户", "多样窗户"),
    "macaws-fences-and-walls": ("麦克的栅栏与墙", "栅栏墙系列"),
    "macaws-lights-and-lamps": ("麦克的灯具", "灯饰系列"),
    "macaws-paths-and-pavings": ("麦克的小径与铺装", "道路铺装系列"),
    "macaws-paintings": ("麦克的画", "装饰画作"),
    "decorative-blocks": ("装饰方块", "装饰建材扩展"),
    "framed-blocks": ("边框方块", "边框建材"),
    "carpet-stairs": ("地毯楼梯", "地毯楼梯变体"),
    "create-decorative-additions": ("机械动力装饰附加", "机械动力风格装饰"),
    "dramatic-doors": ("戏剧之门", "高门与独特门款"),

    # ---- 魔法 ----
    "irons-spells-n-spellbooks": ("铁之咒术", "法术战斗与咒术书"),
    "ars-nouveau": ("新生魔艺", "施法魔艺系统"),
    "hexcasting": ("六边形咒术", "程序化施法"),

    # ---- 音效 / 视听 ----
    "ambient-sounds": ("环境音效", "丰富的环境声音"),
    "presence-footsteps": ("脚步声", "更真实的脚步音效"),
    "sound-physics-remastered": ("声音物理", "声音随距离/遮挡变化"),

    # ---- 服务器 / 联机 ----
    "spark": ("火花", "性能分析器，定位卡顿"),
    "viaversion": ("跨版本", "不同版本客户端互通"),
    "viafabric": ("ViaFabric", "Fabric 跨版本互通"),
    "geyser": ("间歇泉", "基岩版接入 Java 服务器"),
    "floodgate": ("防洪闸", "基岩版玩家登录验证"),
    "simple-voice-chat": ("简易语音聊天", "游戏内语音通话"),

    # ---- 光影 ----
    "complementary-reimagined": ("互补光影·重制", "均衡画质与性能的光影"),
    "complementary-unbound": ("互补光影·无界", "互补系列高配光影"),
    "bsl-shaders": ("BSL光影", "经典高画质光影"),
    "seus-renewed": ("SEUS光影·焕新", "SEUS 系列重制光影"),
    "seus-v11": ("SEUS PTGI v11", "光追级光影"),
    "seus-v10": ("SEUS v10", "经典 SEUS 光影"),
    "solas-shader": ("索拉斯光影", "清新风格光影"),
    "photon-shader": ("光子光影", "写实光子光影"),
    "kappa-shader": ("Kappa光影", "轻量高效光影"),
    "chocapic13-shaders": ("Chocapic13光影", "经典老牌光影"),
    "iterationt": ("迭代T光影", "风格化光影"),
    "makeups-ultra-fast-shaders": ("极速化妆光影", "极致轻量快速光影"),
    "vanilla-plus-shaders": ("原版增强光影", "保留原版观感的光影"),
    "projectluma": ("光", "高质量现代光影"),
    "nostalgia-shaders": ("怀旧光影", "复古风格光影"),
    "rethinking-voxels": ("体素再思考", "独特体素风光影"),
    "bliss-shaders": ("极乐光影", "明亮柔和光影"),

    # ---- 资源包 ----
    "faithful": ("忠实", "经典高清材质包"),
    "fresh-animations": ("鲜活动画", "更生动的原版动画"),
    "3d-default": ("3D默认材质", "方块立体化材质"),
    "default-dark-mode": ("默认深色模式", "原版深色 UI 资源包"),

    # ---- 整合包 ----
    "fabulously-optimized": ("华丽优化", "热门 Fabric 性能优化整合包"),
    "simply-optimized": ("简洁优化", "轻量性能优化整合包"),
    "adrenaline": ("肾上腺素", "高性能竞技向整合包"),
    "all-the-mods-9": ("全能模组9", "大型综合模组包"),
    "all-the-mods-10": ("全能模组10", "大型综合模组包"),
    "vault-hunters-3rd-edition": ("寻宝猎手第三版", "地牢寻宝主题整合包"),
    "rlcraft": ("真实生存", "高难度硬核生存整合包"),
    "stoneblock-3": ("石头世界3", "空岛挖石开局整合包"),
    "create-astral": ("机械动力·星体", "机械动力主题科技整合包"),
    "divine-journey-2": ("神圣之旅2", "大型任务整合包"),
    "dawncraft": ("黎明工艺", "冒险与任务整合包"),
    "better-mc": ("更好的我的世界", "原版增强整合包"),
}


def zh_name(slug, title=""):
    """取中文名；未命中返回英文标题（或 slug）。"""
    hit = MOD_ZH.get(slug)
    if hit:
        return hit[0]
    return title or slug or "?"


def zh_desc(slug, fallback=""):
    """取中文简介；未命中返回英文描述。"""
    hit = MOD_ZH.get(slug)
    if hit and hit[1]:
        return hit[1]
    return fallback or ""


def _has_cjk(s):
    """是否包含中日韩统一表意文字（简/繁中文）。"""
    return any('\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf'
               for ch in s)


def zh_to_search_query(query):
    """中文关键词 -> 可传给 Modrinth 的英文搜索词。

    规则：
    1. 不含中文：原样返回（Modrinth 原生按标题/描述搜索英文）。
    2. 含中文：先精确匹配中文名，命中直接返回其 slug；
       否则做包含匹配（中文名含关键词，或关键词含中文名），
       多个候选时取中文名最短的 slug（最贴近用户输入）。
    3. 无任何映射：原样返回（个别资源标题本身含中文，仍有机会命中）。
    """
    q = (query or "").strip()
    if not q or not _has_cjk(q):
        return q
    cands = []  # (中文名长度, slug)
    for slug, (zh, _desc) in MOD_ZH.items():
        if not zh:
            continue
        if zh == q:
            return slug
        if q in zh or zh in q:
            cands.append((len(zh), slug))
    if cands:
        cands.sort(key=lambda x: x[0])
        return cands[0][1]
    return q


def fmt_size(n):
    """字节数 -> 可读大小（"3.1 MB"）；空/0 返回空串。"""
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d B" % int(n)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return ""
