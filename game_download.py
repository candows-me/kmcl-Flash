# -*- coding: utf-8 -*-
"""KMCL 社区维护版 - 游戏版本下载 + 模组加载器安装（业务逻辑，无 UI）。

架构参考 Kmcl 增强版 download_page：
  - Mojang 官方 version_manifest_v2.json 列出全部版本（正式版 / 愚人节 / 快照 / 远古版）
  - 原版下载：版本 json + 依赖库 + 原生库 + 资源文件（复用 repair_game 的 BMCLAPI 国内镜像）
  - Fabric：meta API 直接生成版本 profile（自足，含原版 client jar 条目）
  - Forge / NeoForge：官方 installer --installClient
"""
import os
import re
import json
import time
import shutil
import subprocess
import urllib.request
import urllib.parse
import concurrent.futures

import repair_game  # mirror_candidates：BMCLAPI 国内镜像前缀映射（单一事实源）

BMCLAPI = "https://bmclapi2.bangbang93.com"
MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FABRIC_META = "https://meta.fabricmc.net/v2"
FABRIC_META_MIRROR = BMCLAPI + "/fabric-meta/v2"
FORGE_PROMO = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
FORGE_PROMO_MIRROR = BMCLAPI + "/maven/net/minecraftforge/forge/promotions_slim.json"
FORGE_MAVEN = "https://maven.minecraftforge.net"
NEOFORGE_MAVEN = "https://maven.neoforged.net"
UA = {"User-Agent": "KMCL-Community/1.0"}

# ---- Legacy Fabric（老版本 Fabric 生态，1.3.2~1.13.2，规范参考 legacy-meta / HMCL）----
LEGACY_FABRIC_MAVEN = "https://maven.legacyfabric.net/"
LEGACY_FABRIC_LOADER_MAVEN = "https://maven.fabricmc.net/"          # loader 本体走官方（meta 规范 Reference.FABRIC_MAVEN_URL）
LEGACY_FABRIC_LWJGL2 = "2.9.4+legacyfabric.17"                     # 官方 LWJGL2 补丁版（ProfileHelper.LWJGLVersions）
LEGACY_FABRIC_FIXES_URL = ("https://raw.githubusercontent.com/Legacy-Fabric/multimc-instance-creator/"
                           "master/skel/.minecraft/mods/legacy-fixes-1.0.1.jar")

# ---- Quilt（Fabric 生态的社区 fork，1.19+，meta v3 官方直连）----
QUILT_META = "https://meta.quiltmc.org/v3"

LOADER_DESC = {
    "vanilla": "原版：纯净的官方 Minecraft，不加载任何模组。",
    "modloader": "ModLoader：远古时代（1.6.2 及更早）的经典加载器，老模组大多依赖它（RAR 归档需系统安装 7-Zip 或 WinRAR）。",
    "liteloader": "LiteLoader：轻量客户端加载器（1.5.2~1.12.2），小地图/状态栏等客户端模组首选，常与 Forge 共用。",
    "cleanroom": "Cleanroom：1.12.2 专用，Forge 的现代 fork（支持新版 Java / LWJGL3），追求性能与兼容性。",
    "fabric": "Fabric：轻量模组加载器，兼容几乎所有版本，安装快。",
    "legacyfabric": "Legacy Fabric：老版本（1.3.2~1.13.2）的 Fabric 生态加载器，官方持续维护，适配老 LWJGL2 环境。",
    "quilt": "Quilt：Fabric 生态的社区加载器（Quilt Loader），1.19+ 推荐给追求社区新特性的玩家。",
    "forge": "Forge：最经典的模组加载器，大型模组首选（走官方安装器）。",
    "neoforge": "NeoForge：Forge 的现代分支，1.20.1+ 推荐。",
}

# LiteLoader（Mumfrey）版本清单（1.5.2 ~ 1.12.2）。
# 数据快照自 HMCL 内置 assets/liteloader/versions.json（官方清单已停更，此为社区维护快照，
# 与 HMCL 发行版完全一致）。每条：MC 版本 -> (LiteLoader 版本, jar 直链, 依赖库 maven 名)。
# jar 直链均为官方源（dl.liteloader.com / repo.mumfrey.com，实测可达）；依赖库走 BMCLAPI 镜像。
LITELOADER_META = {
    "1.5.2":  ("1.5.2_01", "https://dl.liteloader.com/versions/com/mumfrey/liteloader/1.5.2/liteloader-1.5.2_01.jar",
               ["net.minecraft:launchwrapper:1.5", "net.sf.jopt-simple:jopt-simple:4.5", "org.ow2.asm:asm-all:4.1"]),
    "1.6.2":  ("1.6.2_04", "https://dl.liteloader.com/versions/com/mumfrey/liteloader/1.6.2/liteloader-1.6.2_04.jar",
               ["net.minecraft:launchwrapper:1.3"]),
    "1.6.4":  ("1.6.4_01", "https://dl.liteloader.com/versions/com/mumfrey/liteloader/1.6.4/liteloader-1.6.4_01.jar",
               ["net.minecraft:launchwrapper:1.8"]),
    "1.7.2":  ("1.7.2_05", "https://dl.liteloader.com/versions/com/mumfrey/liteloader/1.7.2/liteloader-1.7.2_05.jar",
               ["net.minecraft:launchwrapper:1.9", "org.ow2.asm:asm-all:4.1"]),
    "1.7.10": ("1.7.10_04", "https://dl.liteloader.com/versions/com/mumfrey/liteloader/1.7.10/liteloader-1.7.10_04.jar",
               ["net.minecraft:launchwrapper:1.11", "org.ow2.asm:asm-all:5.0.3"]),
    "1.8":    ("1.8", "https://dl.liteloader.com/versions/com/mumfrey/liteloader/1.8/liteloader-1.8.jar",
               ["net.minecraft:launchwrapper:1.11", "org.ow2.asm:asm-all:5.0.3"]),
    "1.8.9":  ("20260727.184607-11",
               "https://repo.mumfrey.com/content/repositories/snapshots/com/mumfrey/liteloader/1.8.9-SNAPSHOT/liteloader-1.8.9-20260727.184607-11-release.jar",
               ["net.minecraft:launchwrapper:1.11", "org.ow2.asm:asm-all:5.0.3"]),
    "1.9":    ("20160522.202455-18",
               "https://repo.mumfrey.com/content/repositories/snapshots/com/mumfrey/liteloader/1.9-SNAPSHOT/liteloader-1.9-20160522.202455-18-release.jar",
               ["net.minecraft:launchwrapper:1.11", "org.ow2.asm:asm-all:5.0.3"]),
    "1.9.4":  ("1.9.4", "https://dl.liteloader.com/repo/com/mumfrey/liteloader/1.9.4/liteloader-1.9.4.jar",
               ["net.minecraft:launchwrapper:1.12", "org.ow2.asm:asm-all:5.0.3"]),
    "1.10":   ("20160728.094226-5",
               "https://repo.mumfrey.com/content/repositories/snapshots/com/mumfrey/liteloader/1.10-SNAPSHOT/liteloader-1.10-20160728.094226-5-release.jar",
               ["net.minecraft:launchwrapper:1.12", "org.ow2.asm:asm-all:5.0.3"]),
    "1.10.2": ("1.10.2", "https://dl.liteloader.com/repo/com/mumfrey/liteloader/1.10.2/liteloader-1.10.2.jar",
               ["net.minecraft:launchwrapper:1.12", "org.ow2.asm:asm-all:5.0.3"]),
    "1.11":   ("20170814.110841-8",
               "https://repo.mumfrey.com/content/repositories/snapshots/com/mumfrey/liteloader/1.11-SNAPSHOT/liteloader-1.11-20170814.110841-8-release.jar",
               ["net.minecraft:launchwrapper:1.12", "org.ow2.asm:asm-all:5.0.3"]),
    "1.11.2": ("20170904.174310-11",
               "https://repo.mumfrey.com/content/repositories/snapshots/com/mumfrey/liteloader/1.11.2-SNAPSHOT/liteloader-1.11.2-20170904.174310-11-release.jar",
               ["net.minecraft:launchwrapper:1.12", "org.ow2.asm:asm-all:5.0.3"]),
    "1.12":   ("20170904.174625-9",
               "https://repo.mumfrey.com/content/repositories/snapshots/com/mumfrey/liteloader/1.12-SNAPSHOT/liteloader-1.12-20170904.174625-9-release.jar",
               ["net.minecraft:launchwrapper:1.12", "org.ow2.asm:asm-all:5.0.3"]),
    "1.12.1": ("20170904.174937-3",
               "https://repo.mumfrey.com/content/repositories/snapshots/com/mumfrey/liteloader/1.12.1-SNAPSHOT/liteloader-1.12.1-20170904.174937-3-release.jar",
               ["net.minecraft:launchwrapper:1.12", "org.ow2.asm:asm-all:5.0.3"]),
    "1.12.2": ("20171128.144431-4",
               "https://repo.mumfrey.com/content/repositories/snapshots/com/mumfrey/liteloader/1.12.2-SNAPSHOT/liteloader-1.12.2-20171128.144431-4-release.jar",
               ["net.minecraft:launchwrapper:1.12", "org.ow2.asm:asm-all:5.2"]),
}

# 第三方依赖库统一走 BMCLAPI maven 镜像（国内快，已实测存在）
LITELOADER_LIB_MIRROR = "https://bmclapi2.bangbang93.com/maven/"

# Rift（DimensionalDevelopment/Rift，1.13~1.13.2 轻量加载器，Forge 缺席 1.13 的过渡方案）
# 启动规范照搬官方 profile.json（版本 json 模板）：inheritsFrom 原版 + mainClass=launchwrapper.Launch
# + arguments.game 追加 --tweakClass org.dimdev.riftloader.launch.RiftLoaderClientTweaker。
# 下载源：Rift 本体走官方 GitHub Releases 直链；dimdev.org 官方 maven 已停用，
# mixin 0.7.11-SNAPSHOT 改从 sponge 仓库取同版本快照；asm/launchwrapper 走 BMCLAPI 镜像。
RIFT_VERSION = "1.0.4-106"
RIFT_JAR_URL = ("https://github.com/DimensionalDevelopment/Rift/releases/download/"
                "v1.0.4-106/Rift-1.0.4-106.jar")
RIFT_MIXIN_URL = ("https://repo.spongepowered.org/maven/org/spongepowered/mixin/0.7.11-SNAPSHOT/"
                  "mixin-0.7.11-20180703.121122-1.jar")
RIFT_TWEAKER = "org.dimdev.riftloader.launch.RiftLoaderClientTweaker"
RIFT_LIBS = [
    {
        "name": "org.dimdev:rift:" + RIFT_VERSION,
        "downloads": {"artifact": {
            "path": "org/dimdev/rift/%s/rift-%s.jar" % (RIFT_VERSION, RIFT_VERSION),
            "url": RIFT_JAR_URL}},
    },
    {
        "name": "org.dimdev:mixin:0.7.11-SNAPSHOT",
        "downloads": {"artifact": {
            "path": "org/dimdev/mixin/0.7.11-SNAPSHOT/mixin-0.7.11-SNAPSHOT.jar",
            "url": RIFT_MIXIN_URL}},
    },
    {
        "name": "org.ow2.asm:asm:6.2",
        "downloads": {"artifact": {
            "path": "org/ow2/asm/asm/6.2/asm-6.2.jar",
            "url": LITELOADER_LIB_MIRROR + "org/ow2/asm/asm/6.2/asm-6.2.jar"}},
    },
    {
        "name": "org.ow2.asm:asm-commons:6.2",
        "downloads": {"artifact": {
            "path": "org/ow2/asm/asm-commons/6.2/asm-commons-6.2.jar",
            "url": LITELOADER_LIB_MIRROR + "org/ow2/asm/asm-commons/6.2/asm-commons-6.2.jar"}},
    },
    {
        "name": "org.ow2.asm:asm-tree:6.2",
        "downloads": {"artifact": {
            "path": "org/ow2/asm/asm-tree/6.2/asm-tree-6.2.jar",
            "url": LITELOADER_LIB_MIRROR + "org/ow2/asm/asm-tree/6.2/asm-tree-6.2.jar"}},
    },
    {
        "name": "net.minecraft:launchwrapper:1.12",
        "downloads": {"artifact": {
            "path": "net/minecraft/launchwrapper/1.12/launchwrapper-1.12.jar",
            "url": LITELOADER_LIB_MIRROR + "net/minecraft/launchwrapper/1.12/launchwrapper-1.12.jar"}},
    },
]

# Cleanroom（CleanroomMC，1.12.2 专用：Forge 的现代 fork，支持 Java 25 / LWJGL3）
# 数据照搬官方 MMC 实例组件（patches/net.minecraftforge.json + org.lwjgl3.json），
# Maven Central / libraries.minecraft.net 源已替换为 BMCLAPI 镜像，只保留 Windows 原生库。
CLEANROOM_VERSION = "0.6.13-alpha"
CLEANROOM_MAIN = "top.outlands.foundation.boot.Foundation"
CLEANROOM_TWEAK = "net.minecraftforge.fml.common.launcher.FMLTweaker"
# Cleanroom 官方 wiki 必装配套 mod（缺省时游戏启动弹 "Fugue and Scalar are not installed"
# 警告，modpack 可能崩溃）。Fugue 走 Modrinth CDN，Scalar 走官方 GitHub Releases。
CLEANROOM_REQUIRED_MODS = [
    ("+Fugue-0.24.4.jar",
     "https://cdn.modrinth.com/data/vylTACsh/versions/Wy9kZZUW/%2BFugue-0.24.4.jar"),
    ("scalar-1.12.2-2.11.1.jar",
     "https://github.com/CleanroomMC/Scalar/releases/download/2.11.1/scalar-1.12.2-2.11.1.jar"),
]
# 原版 1.12.2 中需剔除的 LWJGL2 系库（Cleanroom 用 LWJGL3 + lwjglxx 桥替换，不剔会类冲突）
CLEANROOM_EXCLUDE = ("org.lwjgl:lwjgl", "net.java.jinput:")
CLEANROOM_LIBS = [
 {
  "name": "com.cleanroommc:cleanroom:0.6.13-alpha",
  "downloads": {
   "artifact": {
    "path": "com/cleanroommc/cleanroom/0.6.13-alpha/cleanroom-0.6.13-alpha.jar",
    "url": "https://repo.cleanroommc.com/releases/com/cleanroommc/cleanroom/0.6.13-alpha/cleanroom-0.6.13-alpha-universal.jar",
    "sha1": "8d59eda7065f26fc0c1bbd3a9fa9f272ff89917f",
    "size": 6505649
   }
  }
 },
 {
  "name": "com.cleanroommc:lwjglxx:1.1.22",
  "downloads": {
   "artifact": {
    "path": "com/cleanroommc/lwjglxx/1.1.22/lwjglxx-1.1.22.jar",
    "url": "https://repo.cleanroommc.com/releases/com/cleanroommc/lwjglxx/1.1.22/lwjglxx-1.1.22.jar",
    "sha1": "fddb2d027c3d3911327c6cb064c54b0b83c0813b",
    "size": 530287
   }
  }
 },
 {
  "name": "org.ow2.asm:asm:9.10.1",
  "downloads": {
   "artifact": {
    "path": "org/ow2/asm/asm/9.10.1/asm-9.10.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/ow2/asm/asm/9.10.1/asm-9.10.1.jar",
    "sha1": "ada2141c0cc52ee8f5c48cd5fa4ce0e794f22236",
    "size": 126151
   }
  }
 },
 {
  "name": "org.ow2.asm:asm-commons:9.10.1",
  "downloads": {
   "artifact": {
    "path": "org/ow2/asm/asm-commons/9.10.1/asm-commons-9.10.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/ow2/asm/asm-commons/9.10.1/asm-commons-9.10.1.jar",
    "sha1": "4229e4c55fd8e01c23f9fe9884075cc628aacc50",
    "size": 74840
   }
  }
 },
 {
  "name": "org.ow2.asm:asm-tree:9.10.1",
  "downloads": {
   "artifact": {
    "path": "org/ow2/asm/asm-tree/9.10.1/asm-tree-9.10.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/ow2/asm/asm-tree/9.10.1/asm-tree-9.10.1.jar",
    "sha1": "e244332a17564c1d1572449399a842de35881be2",
    "size": 51958
   }
  }
 },
 {
  "name": "org.ow2.asm:asm-util:9.10.1",
  "downloads": {
   "artifact": {
    "path": "org/ow2/asm/asm-util/9.10.1/asm-util-9.10.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/ow2/asm/asm-util/9.10.1/asm-util-9.10.1.jar",
    "sha1": "7bb9d450e8d4cbf9f9e04096c44bbfe7fba80b15",
    "size": 95628
   }
  }
 },
 {
  "name": "org.ow2.asm:asm-analysis:9.10.1",
  "downloads": {
   "artifact": {
    "path": "org/ow2/asm/asm-analysis/9.10.1/asm-analysis-9.10.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/ow2/asm/asm-analysis/9.10.1/asm-analysis-9.10.1.jar",
    "sha1": "8d49f14d51f632cb1d87c88d1ceaf50db0d8af1b",
    "size": 35140
   }
  }
 },
 {
  "name": "org.ow2.asm:asm-deprecated:7.1",
  "downloads": {
   "artifact": {
    "path": "org/ow2/asm/asm-deprecated/7.1/asm-deprecated-7.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/ow2/asm/asm-deprecated/7.1/asm-deprecated-7.1.jar",
    "sha1": "004ad3a41a931f2ef0aa8f8dc5d7c82090d744c1",
    "size": 9152
   }
  }
 },
 {
  "name": "top.outlands:foundation:0.19.11",
  "downloads": {
   "artifact": {
    "path": "top/outlands/foundation/0.19.11/foundation-0.19.11.jar",
    "url": "https://repo.cleanroommc.com/releases/top/outlands/foundation/0.19.11/foundation-0.19.11.jar",
    "sha1": "d09a565ce42656fcb975cde37f6df5187513e584",
    "size": 55607
   }
  }
 },
 {
  "name": "net.lenni0451:Reflect:1.6.4",
  "downloads": {
   "artifact": {
    "path": "net/lenni0451/Reflect/1.6.4/Reflect-1.6.4.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/net/lenni0451/Reflect/1.6.4/Reflect-1.6.4.jar",
    "sha1": "4e167252fee0377fe8e22b862cfa174519c82649",
    "size": 237639
   }
  }
 },
 {
  "name": "net.lenni0451.commons:unchecked:1.9.2",
  "downloads": {
   "artifact": {
    "path": "net/lenni0451/commons/unchecked/1.9.2/unchecked-1.9.2.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/net/lenni0451/commons/unchecked/1.9.2/unchecked-1.9.2.jar",
    "sha1": "21bc260b57ffdb90348f2e2b8c193308a2778861",
    "size": 9108
   }
  }
 },
 {
  "name": "org.javassist:javassist:3.30.2-GA",
  "downloads": {
   "artifact": {
    "path": "org/javassist/javassist/3.30.2-GA/javassist-3.30.2-GA.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/javassist/javassist/3.30.2-GA/javassist-3.30.2-GA.jar",
    "sha1": "284580b5e42dfa1b8267058566435d9e93fae7f7",
    "size": 794714
   }
  }
 },
 {
  "name": "com.ibm.icu:icu4j:78.3",
  "downloads": {
   "artifact": {
    "path": "com/ibm/icu/icu4j/78.3/icu4j-78.3.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/com/ibm/icu/icu4j/78.3/icu4j-78.3.jar",
    "sha1": "6a851a53bb1f25689fc418dcc8935b0d93580adf",
    "size": 15156073
   }
  }
 },
 {
  "name": "org.jline:jline:4.1.3",
  "downloads": {
   "artifact": {
    "path": "org/jline/jline/4.1.3/jline-4.1.3.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/jline/jline/4.1.3/jline-4.1.3.jar",
    "sha1": "82988d8680e9f2360c7a876273279026a50b5834",
    "size": 1635198
   }
  }
 },
 {
  "name": "org.jline:jline-native:4.1.3",
  "downloads": {
   "artifact": {
    "path": "org/jline/jline-native/4.1.3/jline-native-4.1.3.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/jline/jline-native/4.1.3/jline-native-4.1.3.jar",
    "sha1": "f8449379e67e4970efcdfdca7de648b71add4279",
    "size": 192165
   }
  }
 },
 {
  "name": "net.java.jinput:jinput:2.0.10",
  "downloads": {
   "artifact": {
    "path": "net/java/jinput/jinput/2.0.10/jinput-2.0.10.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/net/java/jinput/jinput/2.0.10/jinput-2.0.10.jar",
    "sha1": "d0a9613a26328720f8055d7b9921e1e5fa6db557",
    "size": 205492
   }
  }
 },
 {
  "name": "net.sf.trove4j:core:3.1.0",
  "downloads": {
   "artifact": {
    "path": "net/sf/trove4j/core/3.1.0/core-3.1.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/net/sf/trove4j/core/3.1.0/core-3.1.0.jar",
    "sha1": "5fd0207b685536b29dd65c86f4b3bf89befb885c",
    "size": 2560395
   }
  }
 },
 {
  "name": "net.sf.trove4j:experimental:3.1.0",
  "downloads": {
   "artifact": {
    "path": "net/sf/trove4j/experimental/3.1.0/experimental-3.1.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/net/sf/trove4j/experimental/3.1.0/experimental-3.1.0.jar",
    "sha1": "7ae04bc42178c53a30d602d0bbd77571cef4ceac",
    "size": 83341
   }
  }
 },
 {
  "name": "net.sf.jopt-simple:jopt-simple:5.0.4",
  "downloads": {
   "artifact": {
    "path": "net/sf/jopt-simple/jopt-simple/5.0.4/jopt-simple-5.0.4.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/net/sf/jopt-simple/jopt-simple/5.0.4/jopt-simple-5.0.4.jar",
    "sha1": "4fdac2fbe92dfad86aa6e9301736f6b4342a3f5c",
    "size": 78146
   }
  }
 },
 {
  "name": "com.github.oshi:oshi-core-ffm:7.3.2",
  "downloads": {
   "artifact": {
    "path": "com/github/oshi/oshi-core-ffm/7.3.2/oshi-core-ffm-7.3.2.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/com/github/oshi/oshi-core-ffm/7.3.2/oshi-core-ffm-7.3.2.jar",
    "sha1": "65733998074514d3300bfb189a0c3bd0d7a46a61",
    "size": 712720
   }
  }
 },
 {
  "name": "com.github.oshi:oshi-common:7.3.2",
  "downloads": {
   "artifact": {
    "path": "com/github/oshi/oshi-common/7.3.2/oshi-common-7.3.2.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/com/github/oshi/oshi-common/7.3.2/oshi-common-7.3.2.jar",
    "sha1": "52c1631d1e2aff7a78c582622dd05a2b8e78d472",
    "size": 888528
   }
  }
 },
 {
  "name": "net.java.dev.jna:jna:5.19.1",
  "downloads": {
   "artifact": {
    "path": "net/java/dev/jna/jna/5.19.1/jna-5.19.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/net/java/dev/jna/jna/5.19.1/jna-5.19.1.jar",
    "sha1": "ca303052cd617c1af2e2c8d344c98a706fb63143",
    "size": 1950853
   }
  }
 },
 {
  "name": "net.java.dev.jna:jna-platform:5.19.1",
  "downloads": {
   "artifact": {
    "path": "net/java/dev/jna/jna-platform/5.19.1/jna-platform-5.19.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/net/java/dev/jna/jna-platform/5.19.1/jna-platform-5.19.1.jar",
    "sha1": "d1e54d9231da5ca3fa730d52960deaa555475468",
    "size": 1416385
   }
  }
 },
 {
  "name": "it.unimi.dsi:fastutil:8.5.18",
  "downloads": {
   "artifact": {
    "path": "it/unimi/dsi/fastutil/8.5.18/fastutil-8.5.18.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/it/unimi/dsi/fastutil/8.5.18/fastutil-8.5.18.jar",
    "sha1": "a6cff377eecc19c2037bf31568a6d7106b50ba1f",
    "size": 23965563
   }
  }
 },
 {
  "name": "com.google.guava:guava:33.6.0-jre",
  "downloads": {
   "artifact": {
    "path": "com/google/guava/guava/33.6.0-jre/guava-33.6.0-jre.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/com/google/guava/guava/33.6.0-jre/guava-33.6.0-jre.jar",
    "sha1": "c376b13067cc99a5774403530953f7b05a91e218",
    "size": 3064793
   }
  }
 },
 {
  "name": "com.google.guava:failureaccess:1.0.2",
  "downloads": {
   "artifact": {
    "path": "com/google/guava/failureaccess/1.0.2/failureaccess-1.0.2.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/com/google/guava/failureaccess/1.0.2/failureaccess-1.0.2.jar",
    "sha1": "c4a06a64e650562f30b7bf9aaec1bfed43aca12b",
    "size": 4740
   }
  }
 },
 {
  "name": "com.google.code.gson:gson:2.14.0",
  "downloads": {
   "artifact": {
    "path": "com/google/code/gson/gson/2.14.0/gson-2.14.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/com/google/code/gson/gson/2.14.0/gson-2.14.0.jar",
    "sha1": "efc0e34ede4e3204eaefb84a00e55e8c86634382",
    "size": 313604
   }
  }
 },
 {
  "name": "org.apache.commons:commons-lang3:3.20.0",
  "downloads": {
   "artifact": {
    "path": "org/apache/commons/commons-lang3/3.20.0/commons-lang3-3.20.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/commons/commons-lang3/3.20.0/commons-lang3-3.20.0.jar",
    "sha1": "65897b3e5731220962e659e001904af3c3cbeba9",
    "size": 713862
   }
  }
 },
 {
  "name": "org.apache.commons:commons-compress:1.28.0",
  "downloads": {
   "artifact": {
    "path": "org/apache/commons/commons-compress/1.28.0/commons-compress-1.28.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/commons/commons-compress/1.28.0/commons-compress-1.28.0.jar",
    "sha1": "e482f2c7a88dac3c497e96aa420b6a769f59c8d7",
    "size": 1117221
   }
  }
 },
 {
  "name": "commons-codec:commons-codec:1.22.0",
  "downloads": {
   "artifact": {
    "path": "commons-codec/commons-codec/1.22.0/commons-codec-1.22.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/commons-codec/commons-codec/1.22.0/commons-codec-1.22.0.jar",
    "sha1": "6b3eb4beb7058c2a638f5f17bcb388649fd339dd",
    "size": 420480
   }
  }
 },
 {
  "name": "commons-io:commons-io:2.22.0",
  "downloads": {
   "artifact": {
    "path": "commons-io/commons-io/2.22.0/commons-io-2.22.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/commons-io/commons-io/2.22.0/commons-io-2.22.0.jar",
    "sha1": "5b1e18bc0ad651ed878029d83f88d9c8189fd51e",
    "size": 609182
   }
  }
 },
 {
  "name": "commons-logging:commons-logging:1.4.0",
  "downloads": {
   "artifact": {
    "path": "commons-logging/commons-logging/1.4.0/commons-logging-1.4.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/commons-logging/commons-logging/1.4.0/commons-logging-1.4.0.jar",
    "sha1": "e8f6313365dfa0580e49c58837afc8caa9b4ce05",
    "size": 75828
   }
  }
 },
 {
  "name": "org.apache.maven:maven-artifact:3.9.16",
  "downloads": {
   "artifact": {
    "path": "org/apache/maven/maven-artifact/3.9.16/maven-artifact-3.9.16.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/maven/maven-artifact/3.9.16/maven-artifact-3.9.16.jar",
    "sha1": "1176c6579a8a68508c3479ef72d514e71c98ddca",
    "size": 58857
   }
  }
 },
 {
  "name": "org.apache.commons:commons-text:1.15.0",
  "downloads": {
   "artifact": {
    "path": "org/apache/commons/commons-text/1.15.0/commons-text-1.15.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/commons/commons-text/1.15.0/commons-text-1.15.0.jar",
    "sha1": "9899093aa40f0199d6c39b131b8f087cdb37e399",
    "size": 264873
   }
  }
 },
 {
  "name": "org.tukaani:xz:1.12",
  "downloads": {
   "artifact": {
    "path": "org/tukaani/xz/1.12/xz-1.12.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/tukaani/xz/1.12/xz-1.12.jar",
    "sha1": "bb9703ba3753ab8665f65e6a25b3ddc7b09b1caf",
    "size": 168792
   }
  }
 },
 {
  "name": "com.google.code.findbugs:jsr305:3.0.2",
  "downloads": {
   "artifact": {
    "path": "com/google/code/findbugs/jsr305/3.0.2/jsr305-3.0.2.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/com/google/code/findbugs/jsr305/3.0.2/jsr305-3.0.2.jar",
    "sha1": "25ea2e8b0c338a877313bd4672d3fe056ea78f0d",
    "size": 19936
   }
  }
 },
 {
  "name": "org.jspecify:jspecify:1.0.0",
  "downloads": {
   "artifact": {
    "path": "org/jspecify/jspecify/1.0.0/jspecify-1.0.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/jspecify/jspecify/1.0.0/jspecify-1.0.0.jar",
    "sha1": "7425a601c1c7ec76645a78d22b8c6a627edee507",
    "size": 3819
   }
  }
 },
 {
  "name": "org.apache.httpcomponents.core5:httpcore5:5.4.3",
  "downloads": {
   "artifact": {
    "path": "org/apache/httpcomponents/core5/httpcore5/5.4.3/httpcore5-5.4.3.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/httpcomponents/core5/httpcore5/5.4.3/httpcore5-5.4.3.jar",
    "sha1": "32a0699fbcb103f5621c00983ee8f5aac080e4a6",
    "size": 955121
   }
  }
 },
 {
  "name": "org.apache.httpcomponents.core5:httpcore5-h2:5.4.3",
  "downloads": {
   "artifact": {
    "path": "org/apache/httpcomponents/core5/httpcore5-h2/5.4.3/httpcore5-h2-5.4.3.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/httpcomponents/core5/httpcore5-h2/5.4.3/httpcore5-h2-5.4.3.jar",
    "sha1": "33bcd37d645539d27c65e17420843fd7f6c0ebf4",
    "size": 263675
   }
  }
 },
 {
  "name": "org.apache.httpcomponents.client5:httpclient5:5.6.1",
  "downloads": {
   "artifact": {
    "path": "org/apache/httpcomponents/client5/httpclient5/5.6.1/httpclient5-5.6.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/httpcomponents/client5/httpclient5/5.6.1/httpclient5-5.6.1.jar",
    "sha1": "b418ba210ace28adf920f1decf64d673953d07cf",
    "size": 1054142
   }
  }
 },
 {
  "name": "org.apache.httpcomponents:httpclient:4.5.14",
  "downloads": {
   "artifact": {
    "path": "org/apache/httpcomponents/httpclient/4.5.14/httpclient-4.5.14.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/httpcomponents/httpclient/4.5.14/httpclient-4.5.14.jar",
    "sha1": "1194890e6f56ec29177673f2f12d0b8e627dec98",
    "size": 785639
   }
  }
 },
 {
  "name": "org.apache.httpcomponents:httpcore:4.4.16",
  "downloads": {
   "artifact": {
    "path": "org/apache/httpcomponents/httpcore/4.4.16/httpcore-4.4.16.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/httpcomponents/httpcore/4.4.16/httpcore-4.4.16.jar",
    "sha1": "51cf043c87253c9f58b539c9f7e44c8894223850",
    "size": 327891
   }
  }
 },
 {
  "name": "io.netty:netty-codec-base:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-codec-base/4.2.15.Final/netty-codec-base-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-codec-base/4.2.15.Final/netty-codec-base-4.2.15.Final.jar",
    "sha1": "e97149fdd5fb04858efa90e314651c8d700dc68b",
    "size": 152914
   }
  }
 },
 {
  "name": "io.netty:netty-buffer:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-buffer/4.2.15.Final/netty-buffer-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-buffer/4.2.15.Final/netty-buffer-4.2.15.Final.jar",
    "sha1": "2beb620803bf871cda2dd5d46b8f831e8015dd34",
    "size": 371912
   }
  }
 },
 {
  "name": "io.netty:netty-common:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-common/4.2.15.Final/netty-common-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-common/4.2.15.Final/netty-common-4.2.15.Final.jar",
    "sha1": "7222492c1af9c2d4d78d521eea340a619e242fda",
    "size": 818260
   }
  }
 },
 {
  "name": "io.netty:netty-handler:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-handler/4.2.15.Final/netty-handler-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-handler/4.2.15.Final/netty-handler-4.2.15.Final.jar",
    "sha1": "d5344afd1148e3b9927a74be019605ebb0937a93",
    "size": 586442
   }
  }
 },
 {
  "name": "io.netty:netty-resolver:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-resolver/4.2.15.Final/netty-resolver-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-resolver/4.2.15.Final/netty-resolver-4.2.15.Final.jar",
    "sha1": "b961a16d379b508b473e064ba06842bba280f4e3",
    "size": 32977
   }
  }
 },
 {
  "name": "io.netty:netty-transport:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-transport/4.2.15.Final/netty-transport-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-transport/4.2.15.Final/netty-transport-4.2.15.Final.jar",
    "sha1": "a000c3a6196ee40207b73ac619dcb339409dd62f",
    "size": 549606
   }
  }
 },
 {
  "name": "io.netty:netty-transport-native-unix-common:4.2.15.Final-linux-x86_64",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-transport-native-unix-common/4.2.15.Final/netty-transport-native-unix-common-4.2.15.Final-linux-x86_64.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-transport-native-unix-common/4.2.15.Final/netty-transport-native-unix-common-4.2.15.Final-linux-x86_64.jar",
    "sha1": "653fb56a1ea10cbbc24bbec3c94dddaa96bf9f1a",
    "size": 77479
   }
  }
 },
 {
  "name": "io.netty:netty-transport-classes-epoll:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-transport-classes-epoll/4.2.15.Final/netty-transport-classes-epoll-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-transport-classes-epoll/4.2.15.Final/netty-transport-classes-epoll-4.2.15.Final.jar",
    "sha1": "44bafba9c9993800e955b365bba4981326f3f3b1",
    "size": 159908
   }
  }
 },
 {
  "name": "io.netty:netty-transport-native-epoll:4.2.15.Final-linux-x86_64",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-transport-native-epoll/4.2.15.Final/netty-transport-native-epoll-4.2.15.Final-linux-x86_64.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-transport-native-epoll/4.2.15.Final/netty-transport-native-epoll-4.2.15.Final-linux-x86_64.jar",
    "sha1": "ce256127f8ed3f076756f1f4dcb5877d65d1f1c2",
    "size": 42314
   }
  }
 },
 {
  "name": "io.netty:netty-codec-http:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-codec-http/4.2.15.Final/netty-codec-http-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-codec-http/4.2.15.Final/netty-codec-http-4.2.15.Final.jar",
    "sha1": "e611826aa054371bb9a17f27bdb05755a4cac5f0",
    "size": 674986
   }
  }
 },
 {
  "name": "io.netty:netty-codec-http2:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-codec-http2/4.2.15.Final/netty-codec-http2-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-codec-http2/4.2.15.Final/netty-codec-http2-4.2.15.Final.jar",
    "sha1": "c70540243427c8c952473f55813c6d459817de42",
    "size": 494121
   }
  }
 },
 {
  "name": "io.netty:netty-codec-dns:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-codec-dns/4.2.15.Final/netty-codec-dns-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-codec-dns/4.2.15.Final/netty-codec-dns-4.2.15.Final.jar",
    "sha1": "3da23523d91eaf8af81d2b9080a61d9b1af0762c",
    "size": 71118
   }
  }
 },
 {
  "name": "io.netty:netty-codec-compression:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-codec-compression/4.2.15.Final/netty-codec-compression-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-codec-compression/4.2.15.Final/netty-codec-compression-4.2.15.Final.jar",
    "sha1": "89fc4a20b7ae6af974304b1695405e62c4f9b16d",
    "size": 183091
   }
  }
 },
 {
  "name": "io.netty:netty-resolver-dns:4.2.15.Final",
  "downloads": {
   "artifact": {
    "path": "io/netty/netty-resolver-dns/4.2.15.Final/netty-resolver-dns-4.2.15.Final.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/netty/netty-resolver-dns/4.2.15.Final/netty-resolver-dns-4.2.15.Final.jar",
    "sha1": "1b3eaebe62b905c780e181b5f3fd18c013ca73a4",
    "size": 174348
   }
  }
 },
 {
  "name": "jakarta.xml.ws:jakarta.xml.ws-api:4.0.3",
  "downloads": {
   "artifact": {
    "path": "jakarta/xml/ws/jakarta.xml.ws-api/4.0.3/jakarta.xml.ws-api-4.0.3.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/jakarta/xml/ws/jakarta.xml.ws-api/4.0.3/jakarta.xml.ws-api-4.0.3.jar",
    "sha1": "30b8a7abd7b3958461d8256db31816dd2ae6eb85",
    "size": 77638
   }
  }
 },
 {
  "name": "jakarta.activation:jakarta.activation-api:2.1.4",
  "downloads": {
   "artifact": {
    "path": "jakarta/activation/jakarta.activation-api/2.1.4/jakarta.activation-api-2.1.4.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/jakarta/activation/jakarta.activation-api/2.1.4/jakarta.activation-api-2.1.4.jar",
    "sha1": "9e5c2a0d75dde71a0bedc4dbdbe47b78a5dc50f8",
    "size": 67380
   }
  }
 },
 {
  "name": "jakarta.annotation:jakarta.annotation-api:3.0.0",
  "downloads": {
   "artifact": {
    "path": "jakarta/annotation/jakarta.annotation-api/3.0.0/jakarta.annotation-api-3.0.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/jakarta/annotation/jakarta.annotation-api/3.0.0/jakarta.annotation-api-3.0.0.jar",
    "sha1": "54f928fadec906a99d558536756d171917b9d936",
    "size": 26378
   }
  }
 },
 {
  "name": "jakarta.xml.bind:jakarta.xml.bind-api:4.0.5",
  "downloads": {
   "artifact": {
    "path": "jakarta/xml/bind/jakarta.xml.bind-api/4.0.5/jakarta.xml.bind-api-4.0.5.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/jakarta/xml/bind/jakarta.xml.bind-api/4.0.5/jakarta.xml.bind-api-4.0.5.jar",
    "sha1": "161811f36cad3c65991502e80317f2f6703361df",
    "size": 131219
   }
  }
 },
 {
  "name": "jakarta.inject:jakarta.inject-api:2.0.1",
  "downloads": {
   "artifact": {
    "path": "jakarta/inject/jakarta.inject-api/2.0.1/jakarta.inject-api-2.0.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/jakarta/inject/jakarta.inject-api/2.0.1/jakarta.inject-api-2.0.1.jar",
    "sha1": "4c28afe1991a941d7702fe1362c365f0a8641d1e",
    "size": 10681
   }
  }
 },
 {
  "name": "org.apache.logging.log4j:log4j-api:2.26.0",
  "downloads": {
   "artifact": {
    "path": "org/apache/logging/log4j/log4j-api/2.26.0/log4j-api-2.26.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/logging/log4j/log4j-api/2.26.0/log4j-api-2.26.0.jar",
    "sha1": "ad52af0ecf054a7e3f275a2e180ee06d9c490951",
    "size": 351126
   }
  }
 },
 {
  "name": "org.apache.logging.log4j:log4j-core:2.26.0",
  "downloads": {
   "artifact": {
    "path": "org/apache/logging/log4j/log4j-core/2.26.0/log4j-core-2.26.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/logging/log4j/log4j-core/2.26.0/log4j-core-2.26.0.jar",
    "sha1": "d267ca60b27ddb075e0b4e75e7875859717bf85f",
    "size": 2015101
   }
  }
 },
 {
  "name": "org.apache.logging.log4j:log4j-slf4j2-impl:2.26.0",
  "downloads": {
   "artifact": {
    "path": "org/apache/logging/log4j/log4j-slf4j2-impl/2.26.0/log4j-slf4j2-impl-2.26.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/apache/logging/log4j/log4j-slf4j2-impl/2.26.0/log4j-slf4j2-impl-2.26.0.jar",
    "sha1": "668c0f0e813d83f00a7182533aa658ec7e7a0a0d",
    "size": 30211
   }
  }
 },
 {
  "name": "org.slf4j:slf4j-api:2.0.18",
  "downloads": {
   "artifact": {
    "path": "org/slf4j/slf4j-api/2.0.18/slf4j-api-2.0.18.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/slf4j/slf4j-api/2.0.18/slf4j-api-2.0.18.jar",
    "sha1": "78a9e7a37cd6360e0b818e86341b24123d28d4df",
    "size": 69982
   }
  }
 },
 {
  "name": "org.glassfish.jaxb:jaxb-runtime:4.0.9",
  "downloads": {
   "artifact": {
    "path": "org/glassfish/jaxb/jaxb-runtime/4.0.9/jaxb-runtime-4.0.9.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/glassfish/jaxb/jaxb-runtime/4.0.9/jaxb-runtime-4.0.9.jar",
    "sha1": "500c199572538675d2819c938fbafe34935d8d6b",
    "size": 922445
   }
  }
 },
 {
  "name": "org.glassfish.jaxb:jaxb-core:4.0.9",
  "downloads": {
   "artifact": {
    "path": "org/glassfish/jaxb/jaxb-core/4.0.9/jaxb-core-4.0.9.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/glassfish/jaxb/jaxb-core/4.0.9/jaxb-core-4.0.9.jar",
    "sha1": "3f32ec949d109d666fa30994223d1c25a47b105f",
    "size": 139417
   }
  }
 },
 {
  "name": "com.sun.istack:istack-commons-runtime:4.2.0",
  "downloads": {
   "artifact": {
    "path": "com/sun/istack/istack-commons-runtime/4.2.0/istack-commons-runtime-4.2.0.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/com/sun/istack/istack-commons-runtime/4.2.0/istack-commons-runtime-4.2.0.jar",
    "sha1": "131351109ff27c4aa0958a988bb273e879687232",
    "size": 25789
   }
  }
 },
 {
  "name": "org.glassfish.corba:glassfish-corba-omgapi:5.0.2",
  "downloads": {
   "artifact": {
    "path": "org/glassfish/corba/glassfish-corba-omgapi/5.0.2/glassfish-corba-omgapi-5.0.2.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/glassfish/corba/glassfish-corba-omgapi/5.0.2/glassfish-corba-omgapi-5.0.2.jar",
    "sha1": "5707c4c83d8ec7cf417ef2708fa539ff9204a1f4",
    "size": 1411404
   }
  }
 },
 {
  "name": "org.openjdk.nashorn:nashorn-core:15.7",
  "downloads": {
   "artifact": {
    "path": "org/openjdk/nashorn/nashorn-core/15.7/nashorn-core-15.7.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/openjdk/nashorn/nashorn-core/15.7/nashorn-core-15.7.jar",
    "sha1": "f959627b97cb21316906d3634fecf4ec04016bcd",
    "size": 2139093
   }
  }
 },
 {
  "name": "ca.weblite:java-objc-bridge:1.2",
  "downloads": {
   "artifact": {
    "path": "ca/weblite/java-objc-bridge/1.2/java-objc-bridge-1.2.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/ca/weblite/java-objc-bridge/1.2/java-objc-bridge-1.2.jar",
    "sha1": "af8ba4c82a8979d07319f74278312af6c1cd61a5",
    "size": 1476301
   }
  }
 },
 {
  "name": "org.joml:joml:1.10.9",
  "downloads": {
   "artifact": {
    "path": "org/joml/joml/1.10.9/joml-1.10.9.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/joml/joml/1.10.9/joml-1.10.9.jar",
    "sha1": "438e036486bad66b189bff385dd07dea4f74a146",
    "size": 814581
   }
  }
 },
 {
  "name": "io.github.classgraph:classgraph:4.8.184",
  "downloads": {
   "artifact": {
    "path": "io/github/classgraph/classgraph/4.8.184/classgraph-4.8.184.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/io/github/classgraph/classgraph/4.8.184/classgraph-4.8.184.jar",
    "sha1": "a4f7ddec0f831dcf7ec3db32ae2c7e628c89f1a6",
    "size": 586966
   }
  }
 },
 {
  "name": "com.cleanroommc:cleanmix:0.7.2",
  "downloads": {
   "artifact": {
    "path": "com/cleanroommc/cleanmix/0.7.2/cleanmix-0.7.2.jar",
    "url": "https://repo.cleanroommc.com/releases/com/cleanroommc/cleanmix/0.7.2/cleanmix-0.7.2.jar",
    "sha1": "b8793a2f5b29799853dc4bf070707f91112ea2ed",
    "size": 1095887
   }
  }
 },
 {
  "name": "com.cleanroommc:mixinextras-common:0.5.5",
  "downloads": {
   "artifact": {
    "path": "com/cleanroommc/mixinextras-common/0.5.5/mixinextras-common-0.5.5.jar",
    "url": "https://repo.cleanroommc.com/releases/com/cleanroommc/mixinextras-common/0.5.5/mixinextras-common-0.5.5.jar",
    "sha1": "05a822b77f347f39bd821c2c4759a22686800e05",
    "size": 725959
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-glfw:3.4.1",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-glfw/3.4.1/lwjgl-glfw-3.4.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-glfw/3.4.1/lwjgl-glfw-3.4.1.jar",
    "sha1": "a782b1ddd175c9107bf300fd92920579ea65e2a4",
    "size": 151893
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-jemalloc:3.4.1",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-jemalloc/3.4.1/lwjgl-jemalloc-3.4.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-jemalloc/3.4.1/lwjgl-jemalloc-3.4.1.jar",
    "sha1": "16b663092854fc6adfe0a941e61cae2bb2e437b6",
    "size": 47872
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-openal:3.4.1",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-openal/3.4.1/lwjgl-openal-3.4.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-openal/3.4.1/lwjgl-openal-3.4.1.jar",
    "sha1": "8508bd60589de0539aa465b78fcf838efd07ae9a",
    "size": 153919
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-opengl:3.4.1",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-opengl/3.4.1/lwjgl-opengl-3.4.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-opengl/3.4.1/lwjgl-opengl-3.4.1.jar",
    "sha1": "830412cab823c029cda6b9729f9d2ed36cf79959",
    "size": 937660
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-stb:3.4.1",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-stb/3.4.1/lwjgl-stb-3.4.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-stb/3.4.1/lwjgl-stb-3.4.1.jar",
    "sha1": "f077c3dafc31924fbe8acb0b913f08977ba27f8e",
    "size": 142927
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-tinyfd:3.4.1",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-tinyfd/3.4.1/lwjgl-tinyfd-3.4.1.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-tinyfd/3.4.1/lwjgl-tinyfd-3.4.1.jar",
    "sha1": "562697d40dbd2ed0424bf24dcf65d51170f81adf",
    "size": 15931
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl:3.4.1-unsafe",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl/3.4.1/lwjgl-3.4.1-unsafe.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl/3.4.1/lwjgl-3.4.1-unsafe.jar",
    "sha1": "129e06a04f93992cb2a45172435b21fc4b60dd7d",
    "size": 1062128
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-glfw:3.4.1:natives-windows",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-glfw/3.4.1/lwjgl-glfw-3.4.1-natives-windows.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-glfw/3.4.1/lwjgl-glfw-3.4.1-natives-windows.jar",
    "sha1": "2eb4aa895ea190ba8cf4356f8cea24d3ebb40ea1",
    "size": 173265
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-jemalloc:3.4.1:natives-windows",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-jemalloc/3.4.1/lwjgl-jemalloc-3.4.1-natives-windows.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-jemalloc/3.4.1/lwjgl-jemalloc-3.4.1-natives-windows.jar",
    "sha1": "70db8048d1aca8a6365f46f9963b8d6cd77b9e94",
    "size": 184339
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-openal:3.4.1:natives-windows",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-openal/3.4.1/lwjgl-openal-3.4.1-natives-windows.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-openal/3.4.1/lwjgl-openal-3.4.1-natives-windows.jar",
    "sha1": "08e83fdfdf65c80c9877c6fb6cb645d239ed7638",
    "size": 978825
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-opengl:3.4.1:natives-windows",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-opengl/3.4.1/lwjgl-opengl-3.4.1-natives-windows.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-opengl/3.4.1/lwjgl-opengl-3.4.1-natives-windows.jar",
    "sha1": "617f37ef4e2ffb727bd5e74333e8073ef43ca1ec",
    "size": 97635
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-stb:3.4.1:natives-windows",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-stb/3.4.1/lwjgl-stb-3.4.1-natives-windows.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-stb/3.4.1/lwjgl-stb-3.4.1-natives-windows.jar",
    "sha1": "b4e13ece83c228ecf57354639d8555076a989d74",
    "size": 293099
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl-tinyfd:3.4.1:natives-windows",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl-tinyfd/3.4.1/lwjgl-tinyfd-3.4.1-natives-windows.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl-tinyfd/3.4.1/lwjgl-tinyfd-3.4.1-natives-windows.jar",
    "sha1": "bdd8c03151cc94460247986f843d134ae8f9406a",
    "size": 131192
   }
  }
 },
 {
  "name": "org.lwjgl:lwjgl:3.4.1:natives-windows",
  "downloads": {
   "artifact": {
    "path": "org/lwjgl/lwjgl/3.4.1/lwjgl-3.4.1-natives-windows.jar",
    "url": "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl/3.4.1/lwjgl-3.4.1-natives-windows.jar",
    "sha1": "96a217f0428ab73487f114a54179a4f41e851a04",
    "size": 176521
   }
  }
 }
]

# ModLoader（Risugami）历史版本归档：MC 版本 -> (MCArchive 文件 sha256, 归档文件名)
# 来源：MCArchive https://mcarchive.net/mods/modloader（官方 B2 直链，匿名可下载）。
# zip 归档直接用 Python 解压；rar 归档需系统安装 7-Zip 或 WinRAR。
MODLOADER_B2 = "https://b2.mcarchive.net/file/mcarchive"
MODLOADER_FILES = {
    "1.6.2": ("0b14f5e261c9862989aa74313b59188cce10bea6724bae31130ce1e8e6a1c060", "ModLoader 1.6.2.zip"),
    "1.6.1": ("95fc5afdd9cc14d85cb41225fb689d7994f5994287ed9595e192026c06e7b536", "ModLoader 1.6.1.zip"),
    "1.5.2": ("0c355696c2f3ba405bb1f0f845dc51a6613c121eac25a6c7bc9d8046f2c941df", "ModLoader 1.5.2.zip"),
    "1.5.1": ("af7d7bca70b8bc08c75e96ec90a25432682dfc825aa4fe35485dcb390b1f7014", "ModLoader 1.5.1.zip"),
    "1.5": ("597d4d437a250986da84a9c7aee3ea653739608caf1d4a208f2006d8cbdfbc3d", "ModLoader 1.5.zip"),
    "1.4.7": ("685ead73c19531cf24062c7536737663421ed4170cfa582baddbbf6cba1544d2", "ModLoader 1.4.7.zip"),
    "1.4.6": ("f69b1f99b76c23cc1e076197375996e3b79feb369952ac692630f7b063709d5f", "ModLoader 1.4.6.zip"),
    "1.4.5": ("885b62bde6231b04d0189a06b082edfa48ea1474f22a5502ab40288563036b42", "ModLoader 1.4.5.zip"),
    "1.4.4": ("7d39b6d5e41bcd77edabd0aca3b43a10861a65ee9c2f9b358cedf8382d69c14e", "ModLoader 1.4.4.zip"),
    "1.4.2": ("861324b55c40e4af622e2a987c3c20ed4eb869ea89a004c93222058e394baec4", "ModLoader 1.4.2.zip"),
    "1.3.2": ("01a28a0a3d05634ce8745d34738b0617ddb285ad1584fb668874892c61e489eb", "ModLoader 1.3.2.zip"),
    "1.3.1": ("511881d7432cf740b753180a645ca6abb7cd63d09813e0089485c125d52c09a0", "ModLoader 1.3.1.zip"),
    "1.2.5": ("219370a86a15bfef8ff91f51fdd151e99391b771759183b19f72197452a28b79", "ModLoader 1.2.5.zip"),
    "1.2.4": ("0f9bb79149f95061bee539a3120d820043e84ed8747e9ca98756fc34e40b7d7d", "ModLoader 1.2.4.zip"),
    "1.2.3": ("3d3fbbd5cefe409c9c7328a57c4cd854e72d7a6dce6e829e2120c0ad5e1a5f63", "ModLoader 1.2.3.zip"),
    "1.1": ("3b0a919bd74c09274d607707dae0c165682a2dab63fd91a6b27a98efcebe9b23", "ModLoader 1.1.rar"),
    "1.0.0": ("0abd012bcfd536522d50ac642080d6164cd6cdc22629386a0e8e1fafa2e7cd99", "ModLoader 1.0.0.zip"),
    "b1.9p5": ("666e9f28927db986a92be437335add82ccd0a1b4c111703d4950b075944e92f8", "ModLoader B1.9p5.zip"),
    "b1.8.1": ("4135de0b0fddf6f9b39761a5261b82dae278b311237ec1cd936911b0b133919e", "ModLoader B1.8.1.zip"),
    "b1.7.3": ("78bc1107a2ae78334d1086c7f372601c141b53345f23ce73931ef318df5cf83e", "ModLoader B1.7.3.zip"),
    "b1.7.2": ("2b4e0e19b817a464ef32042a12f3ba1d8e4db25a01a1bb19efe8a5d9713a003c", "ModLoader B1.7.2.zip"),
    "b1.6.6": ("15262e652abcf8b925909e867821575cf25a17bc8217dbc281a20ce166a3f6b9", "ModLoader B1.6.6.zip"),
    "b1.6.5": ("4d4ff139fca19feef2714a1cd00bd3a9d8007a1d9b76caf46259ae4310262417", "ModLoader B1.6.5.zip"),
    "b1.6.4": ("fffb3f021b3bc5a0017e24d98786df63434f36f8a009553a2e410666156207e6", "ModLoader B1.6.4.zip"),
    "b1.5_01": ("c20df06b803903de5f7768107c27c80bbdbeb896003a93391432cf29bb7110cd", "ModLoader B1.5_01v4.zip"),
    "b1.4_01": ("a1fdf3b4698bfe1d29c8b9ec9f40905d9b436f19d9d630b4ace6b133cbf3560f", "ModLoader B1.4_01.rar"),
    "a1.2.6": ("06c5fa6089698570370537c9919c338f436f9666b45cc05c86f5acc2fc087d90", "ModLoader A1.2.6.rar"),
    "a1.2.5": ("9167d88033a20f89fd8d9dbf56902122dc95e091d33365e84c23f286192ae8aa", "ModLoader A1.2.5.rar"),
    "a1.2.4_01": ("400ef249e04915b71df2630f1bacc38c9701b1d205055075c46f95b518ae786b", "ModLoader A1.2.4_01.rar"),
    "a1.2.3_04": ("5c44c13470829c304a84823af4547362065f5252c070510eea2e5f4580ac09b2", "ModLoader A1.2.3_04.zip"),
    "a1.2.2": ("3907e96b5d1a66e872d6eb20045cfd2794c20b03cd9b6e6c418776867124b13b", "ModLoader A1.2.2.rar"),
    "a1.2.1_01": ("b06c0cb8f3524ed3ecaecc97a450df6697af10c7a51b5b5f2b6b59860752b537", "ModLoader A1.2.1_01.rar"),
    "a1.2.0_02": ("f3fc94a79a2a431889f4679237e93eb90da2c0082ede0acf4e80791da46c2e07", "ModLoader A1.2.0_02.rar"),
    "a1.1.2_01": ("3b0a919bd74c09274d607707dae0c165682a2dab63fd91a6b27a98efcebe9b23", "ModLoader 1.1.rar"),
}

# 官方愚人节特殊版本（Mojang 每年愚人节发布的整活版本）
APRIL_FOOLS = {
    "2.0", "15w14a", "1.RV-Pre1", "3D Shareware v1.34",
    "20w14infinite", "21w13a", "22w13oneBlockAtATime",
    "23w13a_or_b", "24w14potato", "25w14craftmine",
}

TYPE_CN = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "远古版",
    "old_alpha": "远古版",
}


def _http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_json_mirror(url):
    """镜像优先、官方兜底读取 JSON（国内网络明显更快、失败率低）。"""
    return _http_json_multi(repair_game.mirror_candidates(url))


def _http_text_mirror(url):
    """镜像优先、官方兜底读取文本。"""
    return _http_text_multi(repair_game.mirror_candidates(url))


def _http_text(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def _download(url, dest, progress=None, cancel=None):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        deadline = time.time() + 90  # 整体超时：防止镜像 302→CDN 慢速吐数据永久卡住
        with open(tmp, "wb") as f:
            while True:
                if cancel and cancel():
                    raise RuntimeError("已取消下载")
                if time.time() > deadline:
                    raise TimeoutError("源 %s 下载超时（90s）" % url)
                c = r.read(65536)
                if not c:
                    break
                f.write(c)
                done += len(c)
                if progress:
                    progress(done, total)
    os.replace(tmp, dest)


def _http_json_multi(urls):
    """依次尝试多个源，全部失败抛 RuntimeError（含每个源的具体错误）。"""
    errs = []
    for u in urls:
        try:
            return _http_json(u)
        except Exception as e:
            errs.append("%s -> %s" % (u, e))
    raise RuntimeError("网络请求失败，已尝试 %d 个源：\n%s" % (len(urls), "\n".join(errs)))


def _http_text_multi(urls):
    """依次尝试多个源读取文本。"""
    errs = []
    for u in urls:
        try:
            return _http_text(u)
        except Exception as e:
            errs.append("%s -> %s" % (u, e))
    raise RuntimeError("网络请求失败，已尝试 %d 个源：\n%s" % (len(urls), "\n".join(errs)))


def _download_multi(urls, dest, progress=None, cancel=None):
    """依次尝试多个源下载同一文件，全部失败才报错。"""
    errs = []
    for u in urls:
        try:
            return _download(u, dest, progress=progress, cancel=cancel)
        except Exception as e:
            errs.append("%s -> %s" % (u, e))
    raise RuntimeError("下载失败，已尝试 %d 个源：\n%s" % (len(urls), "\n".join(errs)))


# ============ 版本列表 ============
_MANIFEST_CACHE = {"t": 0.0, "data": None}


def fetch_manifest():
    """版本清单（内存缓存 30 分钟）：下载游戏每次都拉全量清单有 ~1s 网络往返，
    连续下载多个版本时显著拖慢。"""
    import time as _t
    now = _t.time()
    if _MANIFEST_CACHE["data"] and (now - _MANIFEST_CACHE["t"]) < 1800:
        return _MANIFEST_CACHE["data"]
    data = _http_json_mirror(MANIFEST_URL)
    _MANIFEST_CACHE["t"], _MANIFEST_CACHE["data"] = now, data
    return data


def classify_versions(manifest):
    """把全部版本分成四类：release 正式版 / april 愚人节 / snapshot 快照 / old 远古版"""
    out = {"release": [], "april": [], "snapshot": [], "old": []}
    for v in manifest.get("versions", []):
        vid = v.get("id", "")
        vt = v.get("type", "")
        if vid in APRIL_FOOLS or "_or_b" in vid or "potato" in vid or vid.startswith("3D Shareware"):
            out["april"].append(v)
        elif vt == "release":
            out["release"].append(v)
        elif vt == "snapshot":
            out["snapshot"].append(v)
        else:
            out["old"].append(v)
    return out


def manifest_url_for(manifest, version_id):
    for v in manifest.get("versions", []):
        if v.get("id") == version_id:
            return v.get("url")
    return None


# ============ 原版下载（复用 repair_game 镜像下载） ============
def download_vanilla(version_id, mc_root, progress=None, cancel=None, status=None):
    """下载原版核心 jar + 依赖库 + 原生库 + 资源文件。返回版本 json 数据。

    status: 可选回调 status(文本)，用于 UI 显示阶段提示（如"测速选择最快下载源"）。
    """
    import repair_game
    manifest = fetch_manifest()
    url = manifest_url_for(manifest, version_id)
    if not url:
        raise RuntimeError("版本不存在: %s" % version_id)
    vdir = os.path.join(mc_root, "versions", version_id)
    vjson = os.path.join(vdir, version_id + ".json")
    # 版本 json：launchermeta 与 piston-meta 两种历史域名都要映射
    urls = repair_game.mirror_candidates(url)
    if urls[0] == url:
        for old in ("https://launchermeta.mojang.com/", "http://launchermeta.mojang.com/"):
            if url.startswith(old):
                urls = [BMCLAPI + url[len(old):], url]
                break
    _download_multi(urls, vjson, progress=progress, cancel=cancel)
    with open(vjson, encoding="utf-8") as f:
        data = json.load(f)
    # 依赖 + assets 任务
    tasks, native_jars, _ = repair_game.collect_tasks(version_id, mc_root)
    # —— 原版 client jar：测速选最快源下载（只动 client jar，其余任务源不动）——
    client_task = None
    vjar_rel = os.path.join("versions", version_id, version_id + ".jar").replace("\\", "/")
    for i, t in enumerate(tasks):
        if t[1].replace("\\", "/").endswith(vjar_rel):
            client_task = tasks.pop(i)
            break
    if client_task:
        if repair_game.need_download(client_task[1], client_task[2], client_task[3]):
            cands = vanilla_client_candidates(version_id, data.get("downloads", {}).get("client", {}))
            # 官方源（piston-data/launcher.mojang，CDN 型并发友好）优先分块下载；
            # BMCLAPI 属限速型镜像（并发反降速），仅作单连接兜底。
            official = [u for u in cands if "bmclapi" not in u]
            mirror = [u for u in cands if "bmclapi" in u]
            order = official + mirror
            if status:
                status("下载原版核心 jar（多线程分块）…")
            ok = False
            jar_size = client_task[2]
            for u in order:
                def _jar_prog(d, t, _u=u):
                    if status and t > 0:
                        status("下载原版核心 jar（%dMB）：%.0f%%" % (
                            jar_size // 1048576, d * 100.0 / t))
                ok, _, _ = repair_game.dl_chunked(
                    u, client_task[1], client_task[2], client_task[3],
                    progress=_jar_prog)
                if ok:
                    break
            if not ok:
                raise RuntimeError("原版核心 jar 下载失败（所有源均不可用）")
    missing = [t for t in tasks if repair_game.need_download(t[1], t[2], t[3])]
    total = len(missing)
    fails = 0
    if missing:
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            futs = {ex.submit(repair_game.dl_task, t): t for t in missing}
            for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
                if cancel and cancel():
                    raise RuntimeError("已取消下载")
                ok, _, _ = fut.result()
                if not ok:
                    fails += 1
                if progress:
                    progress(i, total)
    # natives 下载 + 解压
    ndir = os.path.join(vdir, "natives")
    os.makedirs(ndir, exist_ok=True)
    miss_n = [t for t in native_jars if repair_game.need_download(t[1], t[2], t[3])]
    if miss_n:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(repair_game.dl_task, t): t for t in miss_n}
            for fut in concurrent.futures.as_completed(futs):
                fut.result()
    for nj in native_jars:
        if os.path.exists(nj[1]):
            try:
                repair_game.extract_natives(nj[1], ndir)
            except Exception:
                pass
    data["_dl_fails"] = fails
    return data


# ------------------------------------------------------------
# 原版 client jar 下载源（只影响原版核心 jar；加载器/库的源一律不动）
# 候选源：
#   1. BMCLAPI 国内镜像  https://bmclapi2.bangbang93.com/version/{mc}/{mc}.jar
#   2. 官方 piston-data  https://piston-data.mojang.com/v1/objects/{sha1}/{file}
#   3. 官方 launcher.mojang（旧域名） https://launcher.mojang.com/v1/objects/{sha1}/{file}
# 每次下载游戏时并行测速（真实拉取采样字节），自动选择最快的源。
# ------------------------------------------------------------
def vanilla_client_candidates(version_id, client):
    """生成原版 client jar 的候选下载 URL（去重、保持顺序）。"""
    if not client or not client.get("url"):
        return []
    file = client["url"].rsplit("/", 1)[-1]
    sha = client.get("sha1", "")
    cands = [
        "https://bmclapi2.bangbang93.com/version/%s/%s.jar" % (version_id, version_id),
        client["url"],  # 官方 piston-data
    ]
    if sha and file:
        cands.append("https://launcher.mojang.com/v1/objects/%s/%s" % (sha, file))
    # 去重保序
    seen = set()
    out = []
    for u in cands:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# ============ 加载器 ============
def fabric_loader_versions(mc_version):
    """meta API 返回可用 Fabric loader 版本号列表（镜像优先）"""
    data = _http_json_mirror("%s/versions/loader/%s" % (FABRIC_META, mc_version))
    return [x["loader"]["version"] for x in data]


def install_fabric(mc_version, loader_version, mc_root, progress=None, cancel=None):
    """meta API profile json 直接写为版本 json（自足，含原版 client jar 条目）。"""
    profile = _http_json_mirror("%s/versions/loader/%s/%s/profile/json" % (
        FABRIC_META, mc_version, loader_version))
    vid = "%s-fabric-%s" % (mc_version, loader_version)
    vdir = os.path.join(mc_root, "versions", vid)
    os.makedirs(vdir, exist_ok=True)
    vjson = os.path.join(vdir, vid + ".json")
    with open(vjson, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    # 下载该 profile 的库（BMCLAPI 镜像；collect_tasks 支持继承链，client/natives 归原版目录）
    import repair_game
    tasks, native_jars, base_vdir = repair_game.collect_tasks(vid, mc_root)
    missing = [t for t in tasks if repair_game.need_download(t[1], t[2], t[3])]
    total = len(missing)
    if missing:
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            futs = {ex.submit(repair_game.dl_task, t): t for t in missing}
            for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
                if cancel and cancel():
                    raise RuntimeError("已取消下载")
                fut.result()
                if progress:
                    progress(i, total)
    ndir = os.path.join(base_vdir, "natives")
    os.makedirs(ndir, exist_ok=True)
    for t in native_jars:
        if not os.path.exists(t[1]):
            repair_game.dl_one(t)
        try:
            repair_game.extract_natives(t[1], ndir)
        except Exception:
            pass
    return vid


# ------------------------------------------------------------
# Quilt（Fabric 生态社区 fork，meta v3，官方直连）
# profile 直接采用官方 meta json（inheritsFrom 原版，含 loader/hashed/intermediary 全库），
# 库下载走 repair_game 镜像优先+官方兜底（maven.quiltmc.org 与 maven.fabricmc.net）。
# ------------------------------------------------------------
def quilt_loader_versions(mc_version):
    """Quilt meta v3 loader 版本列表（官方直连；BMCLAPI 无 quilt-meta 镜像）。
    按 (主,次,补丁) 数字排序，最新稳定线（如 0.29.2-beta.x）排最后。"""
    data = _http_json("%s/versions/loader/%s" % (QUILT_META, mc_version))
    vs = [x.get("loader", {}).get("version") for x in data if x.get("loader", {}).get("version")]

    def _key(v):
        m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", v)
        if not m:
            return (0, 0, 0, v)
        return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), v)

    vs.sort(key=_key)
    return vs


def install_quilt(mc_version, loader_version, mc_root, progress=None, cancel=None):
    """安装 Quilt：官方 meta profile json 直接写为版本 json（inheritsFrom 原版，自足）。"""
    profile = _http_json("%s/versions/loader/%s/%s/profile/json" % (
        QUILT_META, mc_version, loader_version))
    vid = "quilt-loader-%s-%s" % (loader_version, mc_version)
    vdir = os.path.join(mc_root, "versions", vid)
    os.makedirs(vdir, exist_ok=True)
    vjson = os.path.join(vdir, vid + ".json")
    with open(vjson, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    import repair_game
    tasks, native_jars, base_vdir = repair_game.collect_tasks(vid, mc_root)
    missing = [t for t in tasks if repair_game.need_download(t[1], t[2], t[3])]
    total = len(missing)
    if missing:
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            futs = {ex.submit(repair_game.dl_task, t): t for t in missing}
            for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
                if cancel and cancel():
                    raise RuntimeError("已取消下载")
                fut.result()
                if progress:
                    progress(i, total)
    ndir = os.path.join(base_vdir, "natives")
    os.makedirs(ndir, exist_ok=True)
    for t in native_jars:
        if not os.path.exists(t[1]):
            repair_game.dl_one(t)
        try:
            repair_game.extract_natives(t[1], ndir)
        except Exception:
            pass
    return vid


# ------------------------------------------------------------
# Legacy Fabric（老版本 Fabric 生态，1.3.2~1.13.2）
# 装配规范逐条对照官方 legacy-meta（ProfileHandler/ProfileHelper）与 HMCL：
#   - loader = 官方 fabric-loader 公共版本线（isPublicLoaderVersion：0.13+ / 1.x+；
#     保守取 0.13.x~0.16.x，官网实例 generate.py 与下载页 fallback 均在此线验证）
#   - profile = 独立版本 json，inheritsFrom 原版（合并进同一版本项，不产生多余原版项）
#   - libraries = loader.common + intermediary(legacy maven) + loader本体 + loader.client
#     + enrich：原版 asm-all disallow + LWJGL2 替换 2.9.4+legacyfabric.17（legacy maven）
#   - ≤1.8.9 额外安装 legacy-fixes mod（官网实例规范）
# ------------------------------------------------------------
def legacy_fabric_loader_versions():
    """Legacy Fabric 公共 loader 版本列表（官方 maven metadata 过滤，镜像优先）。"""
    data = _http_text_mirror("%s/net/fabricmc/fabric-loader/maven-metadata.xml" % LEGACY_FABRIC_LOADER_MAVEN)
    raw = re.findall(r"<version>([^<]+)</version>", data)

    def _t(v):
        try:
            p = [int(x) for x in v.split(".")[:3]]
        except ValueError:
            return None
        while len(p) < 3:
            p.append(0)
        return tuple(p)

    out = []
    for v in raw:
        t = _t(v)
        if not t:
            continue
        # isPublicLoaderVersion（meta 规范）：0.13+ 或 1.x+；保守上限 0.16.x（legacy 验证线）
        if (t[0] == 0 and 13 <= t[1] <= 16) or (t[0] >= 1 and t[0] <= 1):
            out.append(v)
    out.sort(key=_t)
    return out


def install_legacy_fabric(mc_version, loader_version, mc_root, progress=None, cancel=None):
    """安装 Legacy Fabric：自建 profile（inheritsFrom 原版），下载库 + natives + legacy-fixes。

    下载源：fabric 库走 BMCLAPI 镜像（repair_game.dl_one 镜像优先、官方兜底）；
    intermediary / LWJGL2 补丁走 maven.legacyfabric.net（官方，镜像映射外原样直连）。
    """
    # 1) loader meta json（mainClass + libraries.common/client，官方 maven）
    loader_meta = _http_json_mirror("%snet/fabricmc/fabric-loader/%s/fabric-loader-%s.json" % (
        LEGACY_FABRIC_LOADER_MAVEN, loader_version, loader_version))

    # 2) 原版版本 json（download_vanilla 已下载；用于 asm-all / LWJGL2 判定）
    vjson_path = os.path.join(mc_root, "versions", mc_version, mc_version + ".json")
    if not os.path.exists(vjson_path):
        raise RuntimeError("缺少原版版本文件 %s，请先下载原版核心" % mc_version)
    with open(vjson_path, encoding="utf-8") as f:
        vanilla = json.load(f)

    # 3) 库装配（顺序与 meta ProfileHandler 一致）
    libs = list(loader_meta.get("libraries", {}).get("common", []))
    libs.append({"name": "net.legacyfabric:intermediary:%s" % mc_version,
                 "url": LEGACY_FABRIC_MAVEN})
    libs.append({"name": "net.fabricmc:fabric-loader:%s" % loader_version,
                 "url": LEGACY_FABRIC_LOADER_MAVEN})
    libs.extend(loader_meta.get("libraries", {}).get("client", []))

    # 4) enrichProfile：原版 asm-all 禁用（loader 自带新版 asm）+ LWJGL2 整体替换 legacy 补丁
    lwjgl2_present = False
    for lib in vanilla.get("libraries", []):
        name = lib.get("name", "")
        if name.startswith("org.ow2.asm:asm-all"):
            libs.append({"name": name, "rules": [{"action": "disallow"}]})
        elif name.startswith("org.lwjgl.lwjgl:lwjgl:2"):
            lwjgl2_present = True
    if lwjgl2_present:
        lv = LEGACY_FABRIC_LWJGL2
        libs.append({"name": "org.lwjgl.lwjgl:lwjgl:%s" % lv, "url": LEGACY_FABRIC_MAVEN})
        libs.append({"name": "org.lwjgl.lwjgl:lwjgl_util:%s" % lv, "url": LEGACY_FABRIC_MAVEN})
        libs.append({"name": "org.lwjgl.lwjgl:lwjgl-platform:%s" % lv,
                     "url": LEGACY_FABRIC_MAVEN,
                     "extract": {"exclude": ["META-INF/"]},
                     "natives": {"linux": "natives-linux", "osx": "natives-osx",
                                 "windows": "natives-windows"}})

    # 5) mainClass（loader json 为 {client, server} 字典，取 client）
    mc_entry = loader_meta.get("mainClass")
    main_class = mc_entry.get("client") if isinstance(mc_entry, dict) else mc_entry
    if not main_class:
        raise RuntimeError("无法确定 Legacy Fabric 启动主类")

    # 6) 写 profile 版本 json（id 命名与官方 meta 一致：fabric-loader-<loader>-<mc>）
    vid = "fabric-loader-%s-%s" % (loader_version, mc_version)
    vdir = os.path.join(mc_root, "versions", vid)
    os.makedirs(vdir, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    profile = {
        "id": vid,
        "inheritsFrom": mc_version,
        "releaseTime": now,
        "time": now,
        "type": "release",
        "mainClass": main_class,
        "libraries": libs,
    }
    with open(os.path.join(vdir, vid + ".json"), "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    # 7) 下载库 + natives（collect_tasks 支持 name+url 格式、继承链合并、老格式 natives）
    import repair_game
    tasks, native_jars, base_vdir = repair_game.collect_tasks(vid, mc_root)
    missing = [t for t in tasks if repair_game.need_download(t[1], t[2], t[3])]
    total = len(missing)
    if missing:
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            futs = {ex.submit(repair_game.dl_task, t): t for t in missing}
            for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
                if cancel and cancel():
                    raise RuntimeError("已取消下载")
                fut.result()
                if progress:
                    progress(i, total)
    ndir = os.path.join(base_vdir, "natives")
    os.makedirs(ndir, exist_ok=True)
    for t in native_jars:
        if not os.path.exists(t[1]):
            repair_game.dl_one(t)
        try:
            repair_game.extract_natives(t[1], ndir)
        except Exception:
            pass

    # 8) legacy-fixes mod（≤1.8.9 必需，官网实例规范；1.9+ 不需要）
    vt = version_tuple(mc_version)
    if vt and vt <= (1, 8, 9):
        mods_dir = os.path.join(mc_root, "mods")
        os.makedirs(mods_dir, exist_ok=True)
        fixes_dest = os.path.join(mods_dir, "legacy-fixes-1.0.1.jar")
        if not os.path.exists(fixes_dest):
            repair_game.dl_one((LEGACY_FABRIC_FIXES_URL, fixes_dest, 0, ""))
    return vid


# ------------------------------------------------------------
# ModLoader（Risugami，远古版 1.6.2 及更早的经典加载器）
# ------------------------------------------------------------
def _extract_modloader(path, dest):
    """解压 ModLoader 归档。zip 用标准库；rar 依赖系统 7-Zip / WinRAR。"""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(dest)
        return
    except Exception:
        pass
    for exe in ("C:/Program Files/7-Zip/7z.exe",
                "C:/Program Files (x86)/7-Zip/7z.exe",
                "C:/Program Files/WinRAR/UnRAR.exe"):
        if os.path.exists(exe):
            if exe.endswith("7z.exe"):
                subprocess.run([exe, "x", "-y", "-o" + dest, path], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run([exe, "x", "-y", path, dest + os.sep], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                if os.listdir(dest):
                    return
            except OSError:
                pass
            break
    raise RuntimeError("ModLoader 归档为 RAR 格式，需要系统安装 7-Zip 或 WinRAR 才能解压")


def _merge_dir_into_jar(jar_path, src_dir):
    """把解压目录里的 ModLoader 类文件合并进 minecraft.jar，删除 META-INF 签名。

    老版本 Minecraft 带签名校验：合并外部类后必须删除 META-INF 下的 .SF/.RSA/.DSA，
    否则启动时报 Invalid signature。
    """
    import zipfile
    entries = {}
    for root, _, files in os.walk(src_dir):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, src_dir).replace("\\", "/")
            parts = rel.split("/")
            # 部分归档带顶层目录（modloader/ 等），去掉首层
            if len(parts) > 1 and parts[0].lower() in ("modloader", "mods", "modloader_1.1"):
                rel = "/".join(parts[1:])
            with open(full, "rb") as f:
                entries[rel] = f.read()
    if not entries:
        raise RuntimeError("ModLoader 归档内容为空")
    tmp = jar_path + ".tmp"
    zin = zipfile.ZipFile(jar_path)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                n = item.filename
                if n.startswith("META-INF/") and n.rsplit("/", 1)[-1].endswith((".SF", ".RSA", ".DSA")):
                    continue
                zout.writestr(item, zin.read(n))
            for name, data in entries.items():
                zout.writestr(name, data)
    finally:
        zin.close()
    os.replace(tmp, jar_path)


def install_modloader(mc_version, mc_root, progress=None, cancel=None):
    """安装 ModLoader 到新版本 "<mc>-ModLoader"（参考 HMCL / 官方教程）。

    流程：复制原版版本目录 -> 下载 ModLoader 归档（MCArchive B2 直链） ->
    解压（zip 标准库 / rar 用 7-Zip、WinRAR）-> 合并 class 进 jar -> 删签名。
    返回新版本 id（"<mc>-ModLoader"）。
    """
    import urllib.parse
    import shutil
    row = MODLOADER_FILES.get(mc_version)
    if not row:
        raise RuntimeError("该版本（%s）没有可用的 ModLoader 归档" % mc_version)
    sha, fname = row
    url = "%s/%s/%s" % (MODLOADER_B2, sha, urllib.parse.quote(fname))
    src_dir = os.path.join(mc_root, "versions", mc_version)
    jar_path = os.path.join(src_dir, mc_version + ".jar")
    if not os.path.exists(jar_path):
        raise RuntimeError("缺少原版核心：%s（请先安装原版 %s）" % (jar_path, mc_version))
    vid = mc_version + "-ModLoader"
    vdir = os.path.join(mc_root, "versions", vid)
    if os.path.exists(vdir):
        shutil.rmtree(vdir)
    shutil.copytree(src_dir, vdir)
    for ext in (".json", ".jar"):
        old = os.path.join(vdir, mc_version + ext)
        new = os.path.join(vdir, vid + ext)
        if os.path.exists(old) and not os.path.exists(new):
            os.rename(old, new)
    vjson = os.path.join(vdir, vid + ".json")
    try:
        with open(vjson, encoding="utf-8") as f:
            jd = json.load(f)
        if jd.get("id") == mc_version:
            jd["id"] = vid
            with open(vjson, "w", encoding="utf-8") as f:
                json.dump(jd, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    tmp_arc = os.path.join(vdir, "_modloader.tmp")
    _download_multi([url], tmp_arc, progress=progress, cancel=cancel)
    extract_dir = os.path.join(vdir, "_ml_extract")
    shutil.rmtree(extract_dir, ignore_errors=True)
    os.makedirs(extract_dir, exist_ok=True)
    try:
        _extract_modloader(tmp_arc, extract_dir)
        _merge_dir_into_jar(os.path.join(vdir, vid + ".jar"), extract_dir)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
        if os.path.exists(tmp_arc):
            os.remove(tmp_arc)
    return vid


# ------------------------------------------------------------
# LiteLoader（Mumfrey，1.5.2 ~ 1.12.2 的轻量客户端加载器）
# ------------------------------------------------------------
def liteloader_version(mc_version):
    """该 MC 版本的 LiteLoader 最新 build（version / url / libraries / tweak_class）。"""
    row = LITELOADER_META.get(mc_version)
    if not row:
        return None
    version, url, libs = row
    return {"version": version, "url": url, "libraries": libs,
            "tweak_class": "com.mumfrey.liteloader.launch.LiteLoaderTweaker"}


def install_liteloader(mc_version, mc_root, progress=None, cancel=None):
    """安装 LiteLoader（参考 HMCL 规范：不跑安装器，直接装配版本 json）。

    生成 "<mc>-LiteLoader<ver>" 版本，继承原版：
      - mainClass = net.minecraft.launchwrapper.Launch（由 launchwrapper 加载）
      - 1.7.2+ 走 arguments.game 追加 --tweakClass；老版本追加到 minecraftArguments
      - libraries = launchwrapper / asm / jopt-simple（BMCLAPI 镜像）+ liteloader 本体
    """
    b = liteloader_version(mc_version)
    if not b:
        raise RuntimeError("该版本（%s）没有可用的 LiteLoader" % mc_version)
    src_dir = os.path.join(mc_root, "versions", mc_version)
    vjson_src = os.path.join(src_dir, mc_version + ".json")
    if not os.path.exists(vjson_src):
        raise RuntimeError("缺少原版核心：%s（请先安装原版 %s）" % (vjson_src, mc_version))
    with open(vjson_src, encoding="utf-8") as f:
        base = json.load(f)
    vid = "%s-LiteLoader%s" % (mc_version, b["version"])
    vdir = os.path.join(mc_root, "versions", vid)
    os.makedirs(vdir, exist_ok=True)
    libs = [{"name": n, "url": LITELOADER_LIB_MIRROR} for n in b["libraries"]]
    art_path = "com/mumfrey/liteloader/%s/liteloader-%s.jar" % (b["version"], b["version"])
    libs.append({
        "name": "com.mumfrey:liteloader:%s" % b["version"],
        "downloads": {"artifact": {"url": b["url"], "path": art_path, "size": 0, "sha1": ""}},
    })
    data = {
        "id": vid,
        "inheritsFrom": mc_version,
        "type": "release",
        "mainClass": "net.minecraft.launchwrapper.Launch",
        "libraries": libs,
    }
    if "arguments" in base:
        data["arguments"] = {"game": ["--tweakClass", b["tweak_class"]]}
    else:
        mca = base.get("minecraftArguments", "")
        data["minecraftArguments"] = (mca + " --tweakClass " + b["tweak_class"]).strip()
    vjson = os.path.join(vdir, vid + ".json")
    with open(vjson, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 下载缺失依赖（liteloader 本体 jar / launchwrapper / asm / jopt-simple）
    import repair_game
    tasks, native_jars, base_vdir = repair_game.collect_tasks(vid, mc_root)
    missing = [t for t in tasks if repair_game.need_download(t[1], t[2], t[3])]
    total = len(missing)
    if missing:
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            futs = {ex.submit(repair_game.dl_task, t): t for t in missing}
            for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
                if cancel and cancel():
                    raise RuntimeError("已取消下载")
                fut.result()
                if progress:
                    progress(i, total)
    return vid


def _ensure_cleanroom_mods(mc_root):
    """Cleanroom 官方必装配套 mod（Fugue + Scalar）：缺失时自动下载到 mods 目录。

    Cleanroom 官方 wiki 安装页明确要求：缺这两个 mod 时游戏启动弹
    "Fugue and Scalar are not installed" 警告，modpack 可能崩溃。
    规则：mods 目录不存在目标文件时自动下载（幂等，已有文件不重复下载；
    下载失败静默跳过，不影响加载器主体安装）。
    """
    mods_dir = os.path.join(mc_root, "mods")
    try:
        os.makedirs(mods_dir, exist_ok=True)
    except Exception:
        return
    for fn, url in CLEANROOM_REQUIRED_MODS:
        dst = os.path.join(mods_dir, fn)
        if os.path.isfile(dst) and os.path.getsize(dst) > 10000:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KMCL-Community/1.0 (launcher)"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) < 10000:
                continue
            with open(dst, "wb") as f:
                f.write(data)
        except Exception:
            continue


def install_cleanroom(mc_version, mc_root, progress=None, cancel=None):
    """安装 Cleanroom（1.12.2 专用，Forge 的现代 fork；照搬官方 MMC 组件规范）。

    生成自足版本 "<mc>-Cleanroom<ver>"（不 inheritsFrom）：
      - 复制原版 json 的 libraries，剔除 LWJGL2 系（org.lwjgl:lwjgl* / net.java.jinput:*），
        追加 Cleanroom 官方库（repo.cleanroommc.com）+ LWJGL3 全库（BMCLAPI 镜像）
      - mainClass = top.outlands.foundation.boot.Foundation（Cleanroom 自研引导）
      - minecraftArguments 追加 --tweakClass net.minecraftforge.fml.common.launcher.FMLTweaker
      - 自动下载官方必装配套 mod：Fugue + Scalar（缺省时启动弹警告、pack 可能崩溃）
    """
    if mc_version != "1.12.2":
        raise RuntimeError("Cleanroom 仅支持 Minecraft 1.12.2")
    src_dir = os.path.join(mc_root, "versions", mc_version)
    vjson_src = os.path.join(src_dir, mc_version + ".json")
    if not os.path.exists(vjson_src):
        raise RuntimeError("缺少原版核心：%s（请先安装原版 %s）" % (vjson_src, mc_version))
    with open(vjson_src, encoding="utf-8") as f:
        base = json.load(f)
    vid = "%s-Cleanroom%s" % (mc_version, CLEANROOM_VERSION)
    vdir = os.path.join(mc_root, "versions", vid)
    os.makedirs(vdir, exist_ok=True)
    # 原版 libraries 剔除 LWJGL2 系（Cleanroom 用 LWJGL3 + lwjglxx 桥替换）
    libs = [l for l in base.get("libraries", [])
            if not any(l.get("name", "").startswith(p) for p in CLEANROOM_EXCLUDE)]
    # 追加 Cleanroom 组件库（按 name 去重，避免与原版重复）
    have = {l.get("name", "") for l in libs}
    for l in CLEANROOM_LIBS:
        if l["name"] not in have:
            libs.append(l)
            have.add(l["name"])
    data = {
        "id": vid,
        "type": "release",
        "mainClass": CLEANROOM_MAIN,
        "libraries": libs,
        "assetIndex": base.get("assetIndex"),
        "downloads": base.get("downloads"),
        "minecraftArguments": (base.get("minecraftArguments", "") + " --tweakClass " + CLEANROOM_TWEAK).strip(),
    }
    vjson = os.path.join(vdir, vid + ".json")
    with open(vjson, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 下载缺失依赖（cleanroom 全家桶，并发 8 线程；大部分走 BMCLAPI 镜像）
    import repair_game
    tasks, native_jars, base_vdir = repair_game.collect_tasks(vid, mc_root)
    missing = [t for t in tasks if repair_game.need_download(t[1], t[2], t[3])]
    total = len(missing)
    if missing:
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            futs = {ex.submit(repair_game.dl_task, t): t for t in missing}
            for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
                if cancel and cancel():
                    raise RuntimeError("已取消下载")
                fut.result()
                if progress:
                    progress(i, total)
    # LWJGL3 原生库（natives-windows）下载并解压到原版 natives 目录
    ndir = os.path.join(base_vdir, "natives")
    for url, dest, size, sha in native_jars:
        if repair_game.need_download(dest, size, sha):
            repair_game.dl_one((url, dest, size, sha))
    if native_jars:
        os.makedirs(ndir, exist_ok=True)
        for _, dest, _, _ in native_jars:
            if os.path.exists(dest):
                try:
                    repair_game.extract_natives(dest, ndir)
                except Exception:
                    pass
    # Cleanroom 官方必装配套 mod（Fugue + Scalar）：缺失时自动下载到 mods 目录
    _ensure_cleanroom_mods(mc_root)
    return vid


def install_rift(mc_version, mc_root, progress=None, cancel=None):
    """安装 Rift（1.13~1.13.2 专用轻量加载器，Forge 缺席 1.13 的过渡方案）。

    启动规范照搬 Rift 官方 profile.json：inheritsFrom 原版 + mainClass=launchwrapper.Launch
    + arguments.game 追加 --tweakClass RiftLoaderClientTweaker（父版本参数自动合并）。
    生成版本 "<mc>-Rift<ver>"，1.13 / 1.13.1 / 1.13.2 共用同一 Rift jar。
    """
    t = version_tuple(mc_version)
    if t is None or not ((1, 13, 0) <= t <= (1, 13, 2)):
        raise RuntimeError("Rift 仅支持 Minecraft 1.13~1.13.2")
    src_dir = os.path.join(mc_root, "versions", mc_version)
    vjson_src = os.path.join(src_dir, mc_version + ".json")
    if not os.path.exists(vjson_src):
        raise RuntimeError("缺少原版核心：%s（请先安装原版 %s）" % (vjson_src, mc_version))
    vid = "%s-Rift%s" % (mc_version, RIFT_VERSION)
    vdir = os.path.join(mc_root, "versions", vid)
    os.makedirs(vdir, exist_ok=True)
    data = {
        "id": vid,
        "inheritsFrom": mc_version,
        "type": "release",
        "mainClass": "net.minecraft.launchwrapper.Launch",
        "arguments": {"game": ["--tweakClass", RIFT_TWEAKER]},
        "libraries": [dict(l) for l in RIFT_LIBS],
    }
    vjson = os.path.join(vdir, vid + ".json")
    with open(vjson, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 下载缺失依赖（Rift 本体走 GitHub Releases 直链、mixin 走 sponge 仓库、asm/launchwrapper 走 BMCLAPI）
    import repair_game
    tasks, native_jars, base_vdir = repair_game.collect_tasks(vid, mc_root)
    missing = [t for t in tasks if repair_game.need_download(t[1], t[2], t[3])]
    total = len(missing)
    if missing:
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            futs = {ex.submit(repair_game.dl_task, t): t for t in missing}
            for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
                if cancel and cancel():
                    raise RuntimeError("已取消下载")
                fut.result()
                if progress:
                    progress(i, total)
    return vid


def version_tuple(v):
    """'1.20.2' -> (1, 20, 2)；'26.3' -> (26, 3, 0)；无法解析（远古/愚人节）返回 None。"""
    s = (v or "").split("-")[0].strip()
    if not s or not s[0].isdigit():
        return None
    parts = []
    for p in s.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            return None
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def loaders_for_version(mc_version):
    """该 MC 版本可用的加载器 key 列表（按展示顺序，参考 HMCL 加载器-版本支持范围）：
    - ModLoader：远古版（Alpha ~ 1.6.2）经典加载器，对应版本有归档即提供
    - LiteLoader：1.5.2~1.12.2 轻量客户端加载器（与 Forge 并存）
    - Fabric：1.14+（Fabric 官方从 1.14 开始支持）
    - NeoForge：1.20.2+（NeoForge 从 1.20.2 起）
    - Forge：1.5.2~1.12.2 与 1.14~1.21.x（Forge 跳过 1.13；26.x 及以后由 NeoForge 承接。
      1.4.7 及更早的官方 installer 已从 maven/下载页下架，无法安装，故不提供选项）
    - 原版：全部版本
    """
    t = version_tuple(mc_version)
    loaders = ["vanilla"]
    # 远古版（含 a1.x/b1.x 等 version_tuple 无法解析的版本）：有 ModLoader 归档就提供
    if mc_version in MODLOADER_FILES:
        loaders.append("modloader")
    if t is None:
        return loaders
    # LiteLoader：1.5.2~1.12.2 的轻量客户端加载器（与 Forge 并存）
    if (1, 5, 2) <= t <= (1, 12, 2):
        loaders.append("liteloader")
    # Cleanroom：仅 1.12.2（Forge 的现代 fork，官方 requires net.minecraft == 1.12.2）
    if mc_version == "1.12.2":
        loaders.append("cleanroom")
    # Legacy Fabric：老版本 Fabric 生态（1.3.2~1.13.2，intermediary 全版本覆盖，官方持续维护）
    if (1, 3, 2) <= t <= (1, 13, 2):
        loaders.append("legacyfabric")
    # Rift：1.13~1.13.2 轻量加载器（Forge 跳过 1.13，Rift 填补该空缺）
    if (1, 13, 0) <= t <= (1, 13, 2):
        loaders.append("rift")
    if t >= (1, 14, 0):
        loaders.append("fabric")
    # Quilt：Fabric 生态社区 fork，1.19+（Quilt 官方在 1.19 起活跃维护）
    if t >= (1, 19, 0):
        loaders.append("quilt")
    if t >= (1, 20, 2):
        loaders.append("neoforge")
    if ((1, 5, 2) <= t <= (1, 12, 2)) or ((1, 14, 0) <= t < (26, 0, 0)):
        loaders.append("forge")
    return loaders


def forge_versions(mc_version):
    """该 MC 版本的可用 Forge 版本号列表。

    BMCLAPI 镜像（国内快）与官方 promotions 源合并取并集：镜像优先、官方兜底。
    并集逻辑保证版本不丢失（官方 117 key 全量、镜像 46 key 缺 1.16.5/1.20.1/1.21.1，
    镜像缺的由官方兜底补上），只是请求顺序优先走 BMCLAPI。
    """
    merged = {}
    for url in (FORGE_PROMO_MIRROR, FORGE_PROMO):
        try:
            data = _http_json(url)
        except Exception:
            continue
        for k, v in (data.get("promos", {}) or {}).items():
            if v:
                merged.setdefault(k, v)
    latest = merged.get("%s-latest" % mc_version)
    if latest:
        return [latest]
    vs = set()
    for k, v in merged.items():
        if k.startswith(mc_version + "-") and v:
            vs.add(v)
    return sorted(vs, reverse=True)


def _ensure_launcher_profiles(mc_root):
    """Forge/NeoForge 新版 installer 要求 mc_root 存在 launcher_profiles.json，否则拒绝安装。"""
    p = os.path.join(mc_root, "launcher_profiles.json")
    if os.path.exists(p):
        return
    try:
        os.makedirs(mc_root, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({
                "profiles": {},
                "selectedProfile": None,
                "authenticationDatabase": {},
                "clientToken": "00000000-0000-0000-0000-000000000000",
                "launcherVersion": {"name": "KmclLauncher", "format": 21},
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def run_installer(java_exe, installer, mc_root):
    """运行官方 installer，兼容三种调用约定；以 mc_root/versions 实际新增目录为成功判据。
    1) NeoForge：--install-client <目录>（目录作为选项值；NeoForge 无视 CWD，必须显式给目录）
    2) 旧版 Forge：--installClient --installDir <目录>
    3) CWD 模式：--installClient（cwd=mc_root；Forge 47.x 等新版不识别 installDir）
    """
    _ensure_launcher_profiles(mc_root)
    vroot = os.path.join(mc_root, "versions")
    os.makedirs(vroot, exist_ok=True)
    before = set(os.listdir(vroot))
    # (命令参数, cwd)
    attempts = [
        (["--install-client", mc_root], mc_root),
        (["--installClient", "--installDir", mc_root], None),
        (["--installClient"], mc_root),
    ]
    last = None
    for args, cwd in attempts:
        r = subprocess.run([java_exe, "-jar", installer] + args,
                           capture_output=True, text=True, timeout=2400,
                           cwd=cwd, errors="replace")
        last = r
        after = set(os.listdir(vroot))
        if r.returncode == 0 and (after - before):
            return r
    return last


def _find_forge_maven_urls(mc_version, forge_version, want):
    """老版本 Forge（1.8~1.11 时代）的 maven 目录带 MCP 后缀（如 1.10-12.18.0.2000-1.10.0），
    按标准路径 <mc>-<fv>/forge-<mc>-<fv>-<want>.jar 必然 404。此函数从
    files.minecraftforge.net 的版本下载页解析该版本真实 maven URL，任何后缀都自动适配。
    want: "installer" / "universal"
    返回 [镜像URL, 官方URL, ...]（镜像优先，国内快）；页面无此版本返回 []。
    """
    page = "https://files.minecraftforge.net/net/minecraftforge/forge/index_%s.html" % mc_version
    try:
        html = _http_text(page)
    except Exception:
        return []
    needle = "forge-%s-%s" % (mc_version, forge_version)
    suffix = "-%s.jar" % want
    found = []
    for m in re.finditer(r'([^"\'&<>]*maven\.minecraftforge\.net[^"\'&<>]*?\.jar)', html):
        u = urllib.parse.unquote(m.group(1))
        if u.startswith("url="):      # adfoc 等外链包装的 url= 参数
            u = u[4:]
        if needle in u and u.endswith(suffix):
            found.append(u)
    uniq, seen = [], set()
    for u in found:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    if not uniq:
        return []
    urls = []
    for u in uniq[:2]:
        mirror = u.replace("https://maven.minecraftforge.net/", "https://bmclapi2.bangbang93.com/maven/")
        urls.append(mirror)
        urls.append(u)
    return urls


def _download_forge_artifact(mc_version, forge_version, want, dest, progress=None, cancel=None):
    """下载 Forge installer/universal 文件：标准路径优先，404 时从官网下载页解析真实路径。"""
    fname = "forge-%s-%s" % (mc_version, forge_version)
    mdir = "%s-%s" % (mc_version, forge_version)
    urls = [
        "https://bmclapi2.bangbang93.com/maven/net/minecraftforge/forge/%s/%s-%s.jar" % (mdir, fname, want),
        "%s/net/minecraftforge/forge/%s/%s-%s.jar" % (FORGE_MAVEN, mdir, fname, want),
    ]
    try:
        _download_multi(urls, dest, progress=progress, cancel=cancel)
        return
    except RuntimeError:
        pass
    alt = _find_forge_maven_urls(mc_version, forge_version, want)
    if not alt:
        raise RuntimeError("Forge %s 下载失败：标准路径 404，且官网下载页无此版本（%s/%s）" % (want, mc_version, forge_version))
    _download_multi(alt, dest, progress=progress, cancel=cancel)


def _install_forge_legacy(installer, mc_root, mc_version, forge_version, progress=None, cancel=None):
    """老 Forge（installer 无 --installClient，实测 1.11.2 / 1.12.2 均无）：手动装配。

    版本 json 来源：zip 内 version.json（1.12.2+）或 install_profile.json 的 versionInfo（更早）；
    universal jar 的 maven 目标路径按 install_profile 的 install.path 坐标（HMCL 规范）：
      1.5.2-1.6.4 老格式是 net.minecraftforge:minecraftforge:<fv>（不带 mc 前缀），
      1.7.x 是 net.minecraftforge:forge:<mc>-<fv>-mcNNN（带后缀），
    坐标怎么给 jar 就放哪，classpath 才能原样找到（build_launch_command 的 maven_lib_path）。
    zip 内提取优先 install.filePath；没有则按坐标 URL / 下载页解析兜底下载。
    """
    import zipfile
    vi = None
    prof = None
    uj_src = None
    with zipfile.ZipFile(installer) as z:
        names = z.namelist()
        if "version.json" in names:
            vi = json.loads(z.read("version.json"))
        elif "install_profile.json" in names:
            prof = json.loads(z.read("install_profile.json"))
            vi = prof.get("versionInfo") or {}
        # universal jar：install.filePath 优先（老格式文件名千奇百怪，
        # 如 minecraftforge-universal-1.5.2-7.8.1.738.jar 不以 -universal.jar 结尾）；
        # 其次匹配本版本名的 -universal.jar；再取任意 universal
        ins = {}
        if isinstance(prof, dict):
            ins = prof.get("install") or {}
        fp = ins.get("filePath")
        cands = [n for n in names if n.endswith("-universal.jar")]
        if fp and fp in names:
            uj_src = fp
        else:
            for cand in cands:
                if ("forge-%s-%s" % (mc_version, forge_version)) in cand or \
                   ("minecraftforge-universal-%s" % mc_version) in cand:
                    uj_src = cand
                    break
            if not uj_src and cands:
                uj_src = cands[0]
    if not vi or not vi.get("id"):
        raise RuntimeError("安装器不含版本 json（version.json / install_profile.json），无法手动装配")
    vid = vi["id"]
    vd = os.path.join(mc_root, "versions", vid)
    os.makedirs(vd, exist_ok=True)
    with open(os.path.join(vd, vid + ".json"), "w", encoding="utf-8") as f:
        json.dump(vi, f, ensure_ascii=False, indent=2)
    # universal 目标 maven 路径：install.path 坐标优先（老格式真实坐标），
    # 否则从版本 json libraries 里找 net.minecraftforge 自身坐标，最后默认路径
    coord = (ins.get("path") or "") if ins else ""
    if not coord:
        for lib in vi.get("libraries") or []:
            nm = lib.get("name", "")
            if nm.startswith("net.minecraftforge:") and forge_version in nm:
                coord = nm
                break
    rel = None
    if coord:
        cp = coord.split(":")
        cgroup, cartifact = cp[0], cp[1]
        cver = cp[2] if len(cp) > 2 else forge_version
        rel = "%s/%s/%s/%s-%s.jar" % (cgroup.replace(".", "/"), cartifact, cver,
                                      cartifact, cver)
        maven_jar = os.path.join(mc_root, "libraries", rel)
    else:
        mdir = "%s-%s" % (mc_version, forge_version)
        maven_jar = os.path.join(mc_root, "libraries", "net", "minecraftforge", "forge", mdir,
                                 "forge-%s-%s.jar" % (mc_version, forge_version))
    if not os.path.exists(maven_jar):
        os.makedirs(os.path.dirname(maven_jar), exist_ok=True)
        if uj_src:
            with zipfile.ZipFile(installer) as z:
                with z.open(uj_src) as src, open(maven_jar, "wb") as dst:
                    dst.write(src.read())
        else:
            try:
                if rel:
                    urls = [
                        "https://bmclapi2.bangbang93.com/maven/" + rel,
                        "https://maven.minecraftforge.net/" + rel,
                    ]
                    _download_multi(urls, maven_jar, progress=progress, cancel=cancel)
                else:
                    raise RuntimeError("no coord")
            except RuntimeError:
                _download_forge_artifact(mc_version, forge_version, "universal", maven_jar,
                                         progress=progress, cancel=cancel)
    # 老格式（1.5.2~1.7.2，无 inheritsFrom）：启动时版本 jar = 自身
    # （build_launch_command: jar_vid = data.get("jar") or base_vid，无继承链时 base_vid = vid）。
    # 【HMCL 规范】版本 jar 必须是【原版核心 jar】副本：老 Forge 的 universal jar 只含 FML/Forge 类
    # （实测 1.7.2 universal 875 条目无 Minecraft 类），FML ClassPatchManager 从版本 jar 读原版类，
    # 缺失即 NPE。原版核心由 ensure_legacy_vanilla_jar 幂等补齐（下载原版 client jar）。
    if not vi.get("inheritsFrom") and not (vi.get("jar") and vi.get("jar") != vid):
        from java_manager import ensure_legacy_vanilla_jar
        ensure_legacy_vanilla_jar(mc_root, vid)
    return vid


def install_forge(mc_version, forge_version, mc_root, java_exe, progress=None, cancel=None):
    """官方 installer --installClient；老 Forge（installer 无该参数）自动手动装配。
    返回实际生成的版本名（官方格式 mc-forge-ver / 老格式 1.11.2-forge1.11.2-...）"""
    fname = "forge-%s-%s" % (mc_version, forge_version)     # installer 文件名
    mdir = "%s-%s" % (mc_version, forge_version)            # maven 目录名不带 forge- 前缀
    installer = os.path.join(mc_root, "libraries", "forge-installer", fname + "-installer.jar")
    _download_forge_artifact(mc_version, forge_version, "installer", installer,
                             progress=progress, cancel=cancel)
    if progress:
        progress(1, 1)
    vroot = os.path.join(mc_root, "versions")
    vbefore = set(os.listdir(vroot)) if os.path.isdir(vroot) else set()
    r = run_installer(java_exe, installer, mc_root)
    vafter = set(os.listdir(vroot)) if os.path.isdir(vroot) else set()
    new_vs = sorted(vafter - vbefore)
    if r.returncode == 0 and new_vs:
        return new_vs[-1]
    # CLI 无法完成（老 Forge 无 --installClient，参数不识别直接崩）→ 手动装配（HMCL 老 Forge 方式）
    try:
        return _install_forge_legacy(installer, mc_root, mc_version, forge_version,
                                     progress=progress, cancel=cancel)
    except Exception as legacy_err:
        detail = (r.stderr or r.stdout or "")[-300:]
        raise RuntimeError("CLI 安装失败：%s；手动装配也失败：%s" % (detail or "无输出", legacy_err))


def _neo_match(v, mc_version):
    """NeoForge 版本目录名匹配：旧式带 mc 前缀（1.20.1-47.x），新式去掉前缀。
    新式规则：MC 1.21.1 -> NeoForge 21.1.x；MC 1.21 -> NeoForge 21.0.x（主版本精确到段）。"""
    if v.startswith(mc_version + "-"):
        return True
    if mc_version.startswith("1."):
        short = mc_version[2:]  # "1.21.1" -> "21.1"
        parts = short.split(".")
        if len(parts) == 1:
            prefix = short + ".0."   # MC 1.21 -> 21.0.x（避免误匹配 21.8.x）
        else:
            prefix = short + "."     # MC 1.21.1 -> 21.1.x
        if v.startswith(prefix):
            return True
    return False


def neoforge_versions(mc_version):
    """该 MC 版本的可用 NeoForge 版本号列表（BMCLAPI 优先，官方 maven 目录兜底）。

    返回元素可能是两种形态：
      - 旧式（1.20.1 及以前）："1.20.1-47.1.105"，发布 groupId 为 forge；
      - 新式（1.20.2+）："21.1.99"，发布 groupId 为 neoforge。
    install_neoforge 按是否含 "-" 区分。
    """
    try:
        data = _http_json("%s/neoforge/list/%s" % (BMCLAPI, mc_version))
        out = []
        for item in data or []:
            rv = (item.get("rawVersion") or "").replace("-forge-", "-")
            v = item.get("version") or ""
            cand = rv if rv.startswith(mc_version + "-") else v
            if cand and _neo_match(cand, mc_version):
                out.append(cand)
        if out:
            out.sort()
            return out
    except Exception:
        pass
    urls = [
        "https://bmclapi2.bangbang93.com/maven/net/neoforged/neoforge/",
        NEOFORGE_MAVEN + "/releases/net/neoforged/neoforge/",
    ]
    html = _http_text_multi(urls)
    versions = re.findall(r'href="\./([^"/]+)/"', html)
    vs = [v for v in versions if _neo_match(v, mc_version)]
    vs.sort()
    return vs


def install_neoforge(mc_version, neo_version, mc_root, java_exe, progress=None, cancel=None):
    """官方 installer --installClient（BMCLAPI 镜像优先、官方兜底）。

    neo_version 兼容两种形态：
      - 旧式（≤1.20.1）："1.20.1-47.1.105"，groupId 为 net.neoforged:forge；
      - 新式（1.20.2+）："21.1.99"，groupId 为 net.neoforged:neoforge。
    """
    if "-" in neo_version:
        fname, group = "forge-%s" % neo_version, "forge"
    else:
        fname, group = "neoforge-%s" % neo_version, "neoforge"
    installer = os.path.join(mc_root, "libraries", "neoforge-installer", fname + "-installer.jar")
    rel = "net/neoforged/%s/%s/%s-installer.jar" % (group, neo_version, fname)
    urls = [
        BMCLAPI + "/maven/" + rel,
        NEOFORGE_MAVEN + "/releases/" + rel,
    ]
    try:
        _download_multi(urls, installer, progress=progress, cancel=cancel)
    except Exception as e:
        raise RuntimeError("NeoForge 安装器下载失败: %s" % e)
    if progress:
        progress(1, 1)
    vroot = os.path.join(mc_root, "versions")
    vbefore = set(os.listdir(vroot)) if os.path.isdir(vroot) else set()
    r = run_installer(java_exe, installer, mc_root)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "")[-300:] or "NeoForge 安装失败")
    vafter = set(os.listdir(vroot)) if os.path.isdir(vroot) else set()
    new_vs = sorted(vafter - vbefore)
    if not new_vs:
        raise RuntimeError("安装器已结束但未产生新版本目录：%s" % (r.stdout or r.stderr or "")[-300:])
    return new_vs[-1]
