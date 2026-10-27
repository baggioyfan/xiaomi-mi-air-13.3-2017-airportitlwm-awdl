# 小米笔记本 Air 13.3 (2017) · AirPlay 接收端修复

> 给 **Intel 网卡黑苹果** 的 `AirportItlwm` 打 AWDL 补丁，让 macOS Ventura 能当 **AirPlay 接收端**
> （隔空播放 / 屏幕镜像到本机），顺带恢复 **隔空投送** 所需的底层接口。
> 本项目在一台 **小米笔记本 Air 13.3" 2017（i5-7200U / Intel AC 8265 / macOS 13.7.8 / OpenCore）** 上实测通过。

---

## 1. 这个仓库到底解决什么问题

黑苹果装完 Ventura 后常见现象：

- Mac 上「隔空播放接收器」开关明明是**打开**的，但 iPhone / 另一台 Mac 的「屏幕镜像」列表里**看不到这台机器**；
- 反过来「本机投到别人」完全正常 —— 只有**接收**方向坏；
- 「隔空投送」也不工作。

根因不是设置，而是**驱动**：`awdl0` 接口根本不存在。

`awdl0` 是 Apple Wireless Direct Link 的虚拟接口，**AirPlay 2 接收端与隔空投送都必须先在 `awdl0` 上注册服务**。
接口不存在 → `_airplay._tcp` 不会广播 → 外界永远发现不了这台机器。

## 2. 根因定位（源码级）

`AirportItlwm/AirportSTAIOCTL.cpp` → `setVIRTUAL_IF_CREATE()`：

```c
// From Ventura, the virtual interface sequence has channged, now temporary disabled
// the virtual interface creation because it is no functionality.
// This fix the issue of delaying start time of associating to AP.
#if __IO80211_TARGET >= __MAC_13_0
    return kIOReturnUnsupported;
#else
    ...（AWDL 分支：new IO80211P2PInterface、init、setInfraChannel）
#endif
```

上游为了修「关联 AP 变慢」，从 Ventura 起把**整个虚拟接口创建短路**了。
即使把短路去掉，AWDL 分支里也只有 `init()`，**从没 `attach()` 到控制器、也从没 `registerService()`**
—— 接口对象建了但没注册，`awdl0` 依旧不会出现。

## 3. 本仓库做了什么（9 行代码，`patches/enable-awdl.py`）

| 改动 | 内容 |
|---|---|
| ① 删短路 | 去掉 `#if __IO80211_TARGET >= __MAC_13_0 / return kIOReturnUnsupported; / #else` 与配对 `#endif` |
| ② 补 attach | AWDL 分支 `init()` 之后加 `if (!inf->attach(this)) { ... release(); return kIOReturnError; }` |
| ③ 补注册 | `fAWDLInterface = inf;` 之后加 `inf->registerService();` |

补丁脚本是**精确字符串替换 + 三重断言**（短路块唯一、`#endif` 配对、AWDL 锚点唯一），
上游代码一旦变化会**直接 fail 而不是静默产出错包**；重复执行幂等跳过。
补丁后 `setVIRTUAL_IF_CREATE()` 的代码与社区已验证实现
[maddog860/itlwm-Working-Ventura-Airplay](https://github.com/maddog860/itlwm-Working-Ventura-Airplay)
（release `Ventura-Airplay-Fix`，其说明明确测试环境就是 Ventura 13.7.8）**逐语句一致**（已用脚本比对，忽略注释后完全相同）。

CI 做的事：拉上游 `master` → 打补丁 → 装 `MacKernelSDK` → `xcodebuild -scheme "AirportItlwm (all)"`
→ 出全部 8 个变体 → **断言产物是 x86_64** 且 **Ventura 变体里确实含 `failed to attach AWDL interface` 字符串**
→ 打包上传 artifact（含 `awdl-fix.diff` 与 `SHA256SUMS.txt`）。

## 4. 适用前提

- 机型：**小米笔记本 Air 13.3" 2017**（本项目实测机型）；其他 Intel 网卡黑苹果通常同样适用，但未逐一验证
- 网卡：Intel Dual Band Wireless-AC **8265**（PCI `8086:24FD`）——补丁与具体型号无关，走的是 AirportItlwm 通用路径
- 系统：**macOS Ventura 13.x**（`__IO80211_TARGET >= __MAC_13_0` 只在 13+ 生效）
- 引导：OpenCore，`config.plist` 里 `Kernel > Add` 已启用 AirportItlwm 系列 kext
- 机型门控：**AirPlay to Mac（接收）要求 2018+ 机型**，SMBIOS 需在支持列表内（本项目用 `MacBookPro15,4`）

## 5. 怎么用

### 5.1 下载

Actions → 最新一次 `build-awdl-airplay` → artifact `AirportItlwm-awdlfix-x86_64`。
里面是 8 个 `*-awdlfix.zip`，每个解压得到一个 `.kext`。

### 5.2 选对变体（**最容易翻车的一步**）

OpenCore 用 `MinKernel / MaxKernel` 在多个 Airport 变体之间分流，**只有内核落在区间内的那个才会被加载**：

| 变体 | 内核区间 | 对应系统 |
|---|---|---|
| `AirportItlwm_Monterey.kext` | 21.0.0 – 21.9.9 | macOS 12 |
| **`AirportItlwm_Ventura.kext`** | **22.0.0 – 22.9.9** | **macOS 13 ← 本项目目标** |
| `AirportItlwm_Sonoma.kext` | 23.0.0 – 23.3.9 | macOS 14.0 – 14.3 |
| `AirportItlwm.kext`（无后缀） | 23.4.0 – 23.9.9 | macOS 14.4+ |

> 所以 **Ventura 上要替换的是 `AirportItlwm_Ventura.kext`，不是那个无后缀的 `AirportItlwm.kext`**。
> 只换无后缀那份 = 完全没生效，重启后一切照旧（本项目曾在这上面白折腾一轮）。

### 5.3 替换（务必先备份）

```bash
# 1) 挂载 EFI（磁盘工具或）
sudo diskutil mount disk0s1

# 2) 备份原文件（秒级回滚用）
cd /Volumes/EFI/EFI/OC/Kexts
mv AirportItlwm_Ventura.kext AirportItlwm_Ventura.<原版本>.bak

# 3) 放入新 kext（保持文件名一致）
cp -R ~/Downloads/AirportItlwm_Ventura.kext .
```

目录结构必须是 `AirportItlwm_Ventura.kext/Contents/MacOS/AirportItlwm`。

### 5.4 重启后验收（4 条，缺一不可）

```bash
# ① 驱动真的换了：看 UUID，不看版本号（见 §6）
kmutil showloaded | grep -i airportitlwm

# ② awdl0 出现了（之前是 does not exist）
ifconfig awdl0          # 期望 flags 里有 UP,RUNNING，mtu 1484

# ③ 本机已在 AWDL 上广播接收器
dns-sd -B _airplay._tcp local   # 期望能看到自己，interface index = awdl0 的编号

# ④ 另一台 Apple 设备的「屏幕镜像」列表里能看到这台机器
```

4 条全绿 = AirPlay 接收打通。

## 6. 三个必须知道的坑

1. **版本号不能当判据**：4 个 Airport 变体常常**全都是同一个版本号**（例如 2.3.0），看 `CFBundleVersion` 区分不了。
   要比 **`LC_UUID`**：`kmutil showloaded` 第 5 列 ↔ 候选二进制的 Mach-O `LC_UUID`。
2. **`com.apple.AirPlayReceiver` 配置域不存在 ≠ 开关没开**：这个域在 Ventura 上本来就不存在，别拿它判断开关状态。
3. **别把「开关开着」当成「服务已注册」**：开关决定意图，`awdl0` 决定能力。两者是两件事。

## 7. 回滚

```bash
cd /Volumes/EFI/EFI/OC/Kexts
rm -rf AirportItlwm_Ventura.kext
mv AirportItlwm_Ventura.<原版本>.bak AirportItlwm_Ventura.kext
```

## 8. 已验证的环境与产物指纹

本项目补丁对应的**已验证产物**（2026-10-13，实机跑通，`awdl0` UP/RUNNING）：

| 项 | 值 |
|---|---|
| 二进制大小 | 15,692,984 B |
| MD5 | `f01d356953fb6625efde719cb756d500` |
| SHA-256 | `330171e7acae5df1c89cda6702f79384a322474eb2dd8779df86d3ea90cd18fa` |
| LC_UUID | `9F773089-A270-3B2A-A285-672ADEF198A2` |
| CFBundleVersion | 2.4.0 |

> ⚠️ CI 每次重新构建**不保证字节级相同**（Xcode 版本、时间戳、UUID 都会变），
> 上面的指纹只用于「和当年那版已验证产物是不是同一份」的核对，不是 CI 产物的固定值。
> 打完后先比对「行为判据」（§5.4）比比对哈希更可靠。

## 9. 风险与免责

- 上游注释称重开虚拟接口创建可能**回归「关联 AP 变慢」**；本项目实机使用未复现明显退化，但不排除。
- 这是**内核扩展**。刷坏 EFI 可能开不了机 —— 请务必保留 §7 的回滚路径（最好再留一份 EFI 备份在 U 盘 / Ventoy）。
- 与本项目**无关**的另一件事：如果你已经能连上但**画面冻住**，那是传输层问题（如 IPv6 路径异常），不是本项目能修的。
- 修改内容来自上游 itlwm（**GPL-2.0**）的派生，本仓库仅提供补丁脚本与构建流水线，同样遵循 GPL-2.0。

## 10. 上游与致谢

- [OpenIntelWireless/itlwm](https://github.com/OpenIntelWireless/itlwm) —— 驱动本体
- [maddog860/itlwm-Working-Ventura-Airplay](https://github.com/maddog860/itlwm-Working-Ventura-Airplay) —— AWDL 修复思路与参考实现
- [acidanthera/MacKernelSDK](https://github.com/acidanthera/MacKernelSDK) —— kext 构建依赖
