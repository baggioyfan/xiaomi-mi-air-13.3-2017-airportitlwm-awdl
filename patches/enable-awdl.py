#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为 OpenIntelWireless/itlwm 的 AirportItlwm 恢复 AWDL 虚拟接口创建能力。

作用：让 Intel 网卡的黑苹果在 macOS Ventura (13.x) 上重新出现 awdl0 接口
      —— 这是 AirPlay 2 接收端（隔空播放 / 屏幕镜像到本机）和隔空投送的前置条件。

用法：python3 patches/enable-awdl.py <itlwm 源码目录>
"""
import re
import sys
import pathlib

SRC_REL = "AirportItlwm/AirportSTAIOCTL.cpp"
FUNC_START = "setVIRTUAL_IF_CREATE"
FUNC_NEXT = "setVIRTUAL_IF_DELETE"

# 上游在 Ventura 上主动短路虚拟接口创建（注释说为了修「关联 AP 变慢」）
SHORT_CIRCUIT_RE = re.compile(
    r" *#if __IO80211_TARGET >= __MAC_13_0\n"
    r" *return kIOReturnUnsupported;\n"
    r" *#else\n"
)

# 上游那句「临时禁用」的注释在补丁后已失效，换成说明性注释（不影响逻辑）
STALE_COMMENT_RE = re.compile(
    r" *// From Ventura, the virtual interface sequence has channged.*\n"
)
BANNER = (
    "    // [AWDL-FIX] Ventura 起上游把虚拟接口创建整个短路了，导致 awdl0 永不出现；\n"
    "    // 这里恢复创建流程：AirPlay 2 接收端（隔空播放/屏幕镜像）与隔空投送都依赖 awdl0。\n"
)

AWDL_ANCHOR = "        setInfraChannel(&chann);\n        fAWDLInterface = inf;\n"
AWDL_PATCHED = (
    "        setInfraChannel(&chann);\n"
    "        if (!inf->attach(this)) {\n"
    '            XYLog("%s failed to attach AWDL interface to controller\\n", __FUNCTION__);\n'
    "            inf->release();\n"
    "            return kIOReturnError;\n"
    "        }\n"
    "\n"
    "        fAWDLInterface = inf;\n"
    "        inf->registerService();\n"
)


def die(msg):
    print("::error::" + msg)
    sys.exit(1)


def main():
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "src")
    src = root / SRC_REL
    if not src.is_file():
        die("找不到 %s，源码目录不对？" % src)

    text = src.read_text(encoding="utf-8", errors="surrogateescape")

    if "inf->registerService();" in text and "failed to attach AWDL interface" in text:
        print("::notice::补丁已存在，跳过（幂等）")
        return

    # 函数区间
    start = text.find(FUNC_START)
    end = text.find(FUNC_NEXT, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        die("断言失败：定位不到 setVIRTUAL_IF_CREATE 函数区间")
    func = text[start:end]

    # ---- 断言 1：短路块存在且唯一 ----
    hits = SHORT_CIRCUIT_RE.findall(func)
    if len(hits) != 1:
        die("断言失败：Ventura 短路块命中 %d 次（期望 1），上游代码可能已变，请人工复核" % len(hits))
    func = SHORT_CIRCUIT_RE.sub("", func, count=1)
    if STALE_COMMENT_RE.search(func):
        func = STALE_COMMENT_RE.sub(BANNER, func, count=1)
        print("OK 替换失效注释")
    print("OK 移除 Ventura 短路（return kIOReturnUnsupported）")

    # ---- 断言 2：函数内应只剩 1 个孤立 #endif（与短路块配对的那个） ----
    if func.count("#endif") != 1:
        die("断言失败：函数内 #endif 数量 = %d（期望 1），预处理指令不配对" % func.count("#endif"))
    func = re.sub(r" *#endif\n", "", func, count=1)
    print("OK 清除孤立 #endif")

    # ---- 断言 3：AWDL 分支锚点唯一 ----
    if func.count(AWDL_ANCHOR) != 1:
        die("断言失败：AWDL 锚点命中 %d 次（期望 1）" % func.count(AWDL_ANCHOR))
    func = func.replace(AWDL_ANCHOR, AWDL_PATCHED, 1)
    print("OK 为 AWDL 接口补 attach(this) + registerService()")

    # ---- 结果自检 ----
    if "return kIOReturnUnsupported;" in func:
        die("自检失败：短路代码仍在，补丁未生效")
    for need in ("inf->attach(this)", "inf->registerService();"):
        if need not in func:
            die("自检失败：缺少 %s" % need)

    src.write_text(text[:start] + func + text[end:], encoding="utf-8", errors="surrogateescape")
    print("::notice::补丁写入完成 -> %s" % src)


if __name__ == "__main__":
    main()
