# ubuntu-customizer

[English](README.md) | [简体中文](README.zh-CN.md)

## 实体 ARM：先官方最小系统，再逐步适配板级驱动

不再优先扫描 Mac 或其他本地目录寻找“现成可用”的 IMG。实体 ARM 目标先选择
Ubuntu 官方最小 ARM64 RootFS（当前固定 Ubuntu Base 24.04.5），经联网授权后下载、
固定 SHA-256 校验并保存到 `outputs/baselines/`；随后根据设备证据查找内核、
DTB、Bootloader 等组件，在 `outputs/arm-candidates/` 创建逐版候选目录。
**当前产物只是 RootFS 与板级组件的候选工作区，不是可直接刷写的 USB 镜像。**
完整板级驱动适配、可启动 IMG 组装和实体启动验证仍需继续开发。

**本地目录硬限制：** Agent 只允许读取和修改当前项目目录内的文件，运行产物写在
`outputs/`，虚拟环境位于 `.venv/`。默认不得扫描 `~/Downloads`、
`~/.ssh`、`/dev` 目录及其他外部路径，也不能静默切换工作目录。
直接连接实体串口需要单独授权使用对应设备节点；若禁止访问任何 `/dev` 节点，
TTL 方式本身无法执行。Python 路径检查不能代替系统级进程沙箱。

## 新增：实体 ARM64 USB IMG 构建与失败迭代

已实现 `scripts/workflow/arm_image_builder.py`：在项目内从固定哈希的
Ubuntu Base ARM64 RootFS 创建 MBR 磁盘镜像（FAT32 启动分区、ext4 根分区）、
复制 Kernel/DTB/启动脚本及经校验的驱动覆盖包，并输出 SHA-256 清单。
`arm_dtb_adapter.py` 可使用项目内 `dtc` 对 DTS 编译、检查 DTB 结构。
`arm_boot_diagnose.py` 将本轮镜像哈希与串口日志关联，针对内核、
设备树、rootfs、init、USB 和网卡故障提出下一版适配方向。

**边界**：可生成候选 IMG 文件，但没有实机验证 W152D 能通过 USB 启动，
也不保证原厂 U-Boot 会执行通用 extlinux 配置。构建和 DTB 编译的
`mkfs.vfat`、`mcopy`、`mmd`、`mke2fs`、`dtc` 需由隔离的环境以
当前项目内可执行文件方式提供；模拟测试不代表真实工具链已验证。
绝不写实体 eMMC、自动刷盘或自动重启。所有本地文件输入都必须在
当前项目中，生成内容只进入 `outputs/`；若要求限制底层动态库等隐式
访问，也必须使用操作系统级文件沙箱。

## 项目工作目录

具备主机执行权限时，Agent 在选择设备连接前创建或复用项目内的 `.venv/` 和私有 `outputs/`。
不下载软件包，不修改全局 Python。后续辅助工具使用 `./.venv/bin/python -B`，避免在源码树生成字节码缓存。

所有运行产物写入 `./outputs/`；`.venv/` 是本地环境目录的例外。
受版本控制的源码仍在原位置编辑，不移动或删除已有用户产物。
项目内常规、可逆操作具有持续授权；主机／工具权限限制、设备访问、联网安装、镜像构建、
虚拟机启动及目标系统修改仍各自遵守独立授权。

开发者／Agent 初始化与验证示例：

```bash
python3 -B scripts/workflow/project_workspace.py
./.venv/bin/python -B -m unittest discover -s tests -v
```

## 开始使用：告诉 Agent「开始定制系统」

**这是一个 AI Agent Skill。** 在具备主机执行权限、已加载 `SKILL.md` / `AGENTS.md`
的 Agent 中，直接说：

> 开始定制系统

Agent 检查主机能力、准备工作目录，补齐必要的目标信息，再选择 SSH、ADB、受管理的
TTL/picocom 或本机连接及实际接口。它会说明只读探针、隐私、本地监控和阶段，
在设备访问或服务启动前等待方案确认；方案必须展示实际 SSH/ADB 接口或 TTL 串口及波特率，
缺少接口信息则不允许确认。方案默认包含 localhost 监控，用户可明确退出；
确认后监控先于探针启动，Agent 只报告实际启动并验证过的 URL。

已授权的 SSH/ADB/TTL 采集通过单个持久会话执行固定只读探针；旧版被动 TTL 采集仍保留。
证据分析后，镜像目标逐项补齐 OS／版本、启动介质和功能需求，再进入支持的规划及
单独授权的镜像构建或可选 QEMU 验证。

用户不必选择 Python、Lima 或 QEMU 参数，也不必准备第二台电脑。
Agent 无执行权限时必须说明限制。缺少已验证的板级适配器、BSP、DTB、引导加载程序及
恢复路径时，实体 ARM 候选 IMG 现可离线组装，但实机 USB 引导仍未验证，刷写不支持。

参见[引导式交互流程](references/interactive-agent-flow.md)、
[受管理设备会话](references/device-session.md)和 [Agent 工作约定](AGENTS.md)。
**以下命令是内部开发／Agent 示例，不是用户启动步骤。**

> **项目定位：AI Agent Skill。** Agent 引导连接方式选择、证据采集、兼容性分析、
> 镜像构建规划和授权。下方 Python 命令都是可选的辅助工具，不是独立的设备管理产品。
> 请从 [SKILL.md](SKILL.md) 和 [Agent 工作流](references/agent-workflow.md) 开始。
>
> **构建状态：** 已实现的辅助工具支持经过检查的 VM RAW/QCOW2 转换、有限的离线
> RootFS 定制，以及单独授权的 AMD64 QEMU 来宾健康检查。真实镜像构建和来宾启动
> 尚未验证；不支持实体设备镜像组装和刷写。

用于 Ubuntu、Debian 和 Armbian 系统只读发现、维护规划及有限离线虚拟机镜像定制的
AI Agent Skill。

## 当前能力与验证状态

“已实现”表示存在对应代码；“已验证”需要实际测试结果。
持续维护的能力表、测试记录和剩余工作见[路线图与验收](references/roadmap.md)。

| 能力 | 已实现范围 | 验证边界 |
| --- | --- | --- |
| 设备发现与证据 | 固定的 SSH／ADB／本地只读探针、持久 SSH/ADB/picocom 会话、旧版被动 TTL 采集、SHA-256 档案、对比及软件拓扑 | macOS Python 测试通过；真实设备集成未验证 |
| 规划与归档 | JSON 安全子集配置、本地差异计划、指定文件快照、设备／会话目录、不执行操作的任务计划 | 不应用配置，不自动回滚，不认证硬件身份 |
| 虚拟机镜像 | 只读来宾检查、兼容性门控、RAW/QCOW2 转换、私有副本 hostname/MOTD 定制、身份清理及仅使用公钥的 NoCloud 种子 | 真实 qemu-img/libguestfs 构建未验证；不支持任意软件包或脚本 |
| 启动验证 | 静态镜像和 ARM 日志证据适配器；独立的 AMD64 QEMU Guest Agent 健康检查后端 | 模拟来宾测试通过；没有真实来宾或实体设备启动验证结果 |
| Agent 体验 | 纯下一步／授权策略、项目工作目录初始化、原生 Linux 或现有 Mac Lima 后端、方案授权且可退出的本地监控及离线 HTML 查看器 | 本地 HTTP/socket 测试通过；真实 Lima、浏览器及完整 Agent 交接未验证 |

当前引导策略在证据分析后结束 inspect／diagnose／maintain 目标。
虽然存在独立任务规划器，但尚未实现自动诊断、维护执行和恢复。
同样不支持安装器 ISO 创建、实体板卡 IMG/BSP 组装、已安装系统克隆和刷写。
NoCloud 种子 ISO 不是操作系统安装器 ISO。

## 术语约定

| 英文术语 | 中文术语 | 在本项目中的含义 |
| --- | --- | --- |
| Inspection / verification | 检查／验证 | 检查收集观察结果，验证核对具体要求。仅通过哈希校验不能证明来源真实或镜像能启动。 |
| Evidence session / dossier / manifest | 证据会话／设备档案／清单 | 会话保存采集证据，档案汇总证据，清单记录文件及哈希。 |
| Artifact bundle | 产物包 | 发布的镜像、种子、配置及构建清单，不仅指单个镜像文件。 |
| Guest / build host | 来宾／构建主机 | 虚拟机内的系统／运行镜像工具的环境。 |
| Bootloader / pinmux | 引导加载程序／引脚复用 | 两种语言均保留工具、属性和格式标识符的原始写法。 |
| Public-key-only NoCloud seed | 仅使用公钥的 NoCloud 种子 | 使用 SSH 公钥、不含密码或私钥的初始化数据，不是操作系统安装器。 |
| Feature preview / live preview | 功能预览／实时预览 | 早期功能／可选的只读 localhost 进度观察器。 |

**已实现（implemented）**、**已测试（tested）**、**未验证（unverified）**和
**不支持（unsupported）**采用[路线图](references/roadmap.md#status-terminology)中的定义。
每个测试结果都应注明范围。`complete`、`blocked`、`failed`、`boot_confirmed`
等机器可读状态保持原样；静态检查完成不代表已确认来宾成功启动。

## 交互式设备发现

辅助工具可启动连接和证据采集向导：

```bash
./.venv/bin/python -B scripts/workflow/collect.py
```

可选 SSH、ADB、TTL（被动接收）或本地采集。工具将按类别保存原始证据，
并在新建的本地目录中写入包含路径和 SHA-256 的 `manifest.json`。
不会修改硬件、刷写设备或自动上传诊断数据。此旧版 TTL 模式需要可选依赖 `pyserial`。

连接前提、引脚复用限制和证据布局见[设备发现](references/device-discovery.md)。

对已批准的 SSH/ADB/TTL 交互会话，Agent 使用持久适配器替代旧版采集器：

```bash
# 仅在实际连接和监控方案获得批准后执行。
./.venv/bin/python -B scripts/workflow/adaptive.py \
  --transport ssh --target trusted-host-alias \
  --output ./outputs/managed-session-001 \
  --interactive-shell-approved --preview-approved --yes
```

受管理 TTL 使用实际观察到的串口和波特率。未知、登录或 U-Boot 提示符会阻断 Shell 探针；
单次空行唤醒须另行确认输入行为空。明确退出监控时省略 `--preview-approved`。
工具缺失或预览启动失败必须如实报告。参见[设备会话门控](references/device-session.md)。


## 开发辅助工具示例（不是用户启动步骤）

在目标 Linux 机器（如 Ubuntu Server／Armbian）上运行本地命令：

```bash
bash scripts/detect/system.sh
bash scripts/detect/network.sh
./.venv/bin/python -B scripts/safety/validate_profile.py profiles/base/ubuntu-server.json
./.venv/bin/python -B scripts/system/plan.py profiles/base/ubuntu-server.json
./.venv/bin/python -B -m unittest discover -s tests -v
```

在已安装 OpenSSH 并配置好 Host 别名的机器上执行远程只读清单采集：

```bash
./.venv/bin/python -B scripts/remote/ssh_probe.py ubuntu-server
```

为明确指定的本地文件创建快照：

```bash
./.venv/bin/python -B scripts/safety/snapshot.py --output-dir ./outputs/snapshot-001 ./outputs/sample-input.txt
```

快照不提供自动恢复能力，应保存在安全位置。

## 文档

- [SKILL.md](SKILL.md) — Agent 入口
- [V0.2 操作说明](references/v0.2-operations.md) — 命令用法与限制
- [镜像设计](references/image-building.md) — 后端选择
- [系统管理](references/system-management.md) — 期望状态工作流
- [ARM 诊断](references/arm-hardware.md) — DTB／PHY／UART
- [安全规则](references/safety.md) — 授权与恢复要求
- [路线图](references/roadmap.md) — 当前状态与后续工作

配置 JSON 使用标准库实现的**有限安全子集校验器**，不是通用 JSON Schema 实现。
YAML 示例仅用于说明，目前不能作为可执行配置。

不要在配置中包含凭据，也不要提交包含秘密的机器诊断数据。

## 结构化设备档案（发现工作流）

使用现有交互向导采集会话，然后创建带证据索引的设备档案：

```bash
./.venv/bin/python -B scripts/workflow/collect.py
./.venv/bin/python -B scripts/workflow/dossier.py ./outputs/example-device-session-001
./.venv/bin/python -B scripts/workflow/compare.py ./outputs/example-device-session-001/device.json ./outputs/example-device-session-002/device.json
```

档案生成前会验证各证据文件的 SHA-256。未采集的数据会记为证据缺口，不能据此认定硬件不存在。
对比工具报告观察到的身份字段和证据文件变化，本身不能诊断故障。
详细说明见[设备发现](references/device-discovery.md)。

已实现初步的设备与驱动软件关系图；尚无经过完整验证的引脚或电气拓扑。
这些工具不会向目标设备执行写入命令。

## 设备与驱动拓扑（只读）

新采集会话会收集网络、串口、GPIO、platform、I2C、SPI 和 MDIO 的有限 sysfs 绑定证据。
可据此生成保守的软件拓扑：

```bash
./.venv/bin/python -B scripts/workflow/collect.py
./.venv/bin/python -B scripts/workflow/dossier.py ./outputs/example-device-session-001
./.venv/bin/python -B scripts/workflow/topology.py ./outputs/example-device-session-001
```

`topology.json` 保存设备和驱动节点、观察到的 `bound_to` 边、证据路径与行号，
以及不可用或未绑定的观察结果。它只表示 **Linux 驱动绑定**，不代表已验证的 PCB 引脚、
PHY 信号、电压或完整 SoC 引脚复用关系。旧会话缺少新探针时，会明确标为 `not_collected`。
更多背景见[设备发现](references/device-discovery.md)。

## 设备树与运行时关系图（实验性）

对于目标安装了 `dtc` 的新 Linux/Armbian 会话，采集器会保存反编译后的 DTS、
驱动绑定及 platform 设备的 `of_node` 路径。所有探针保持只读。

```bash
./.venv/bin/python -B scripts/workflow/collect.py
./.venv/bin/python -B scripts/workflow/device_tree.py ./outputs/example-device-session-001
./.venv/bin/python -B scripts/workflow/topology.py ./outputs/example-device-session-001
./.venv/bin/python -B scripts/workflow/link_graph.py ./outputs/example-device-session-001
```

输出文件：

- `device-tree.json`：DTS 节点层次、选定属性和支持的 phandle 引用。
- `topology.json`：观察到的 Linux sysfs 设备与驱动绑定。
- `linked-hardware.json`：合并图，包含 platform 设备与 DTS 节点间观察到的 `of_node` 关联。

所有输入均根据会话清单验证 SHA-256。DTS 缺失或截断时会明确记录证据缺口。
数字 phandle 引用仅标为**候选关系**，不代表已经完成 specifier 解码；
pinctrl、clock、reset 的 cell 数需要结合具体 binding 分析。
图中只表达从哈希校验通过的证据中得出的软件关系，物理排针、PCB 走线、电平及硬件功能状态仍未验证。

解析器支持常见 `dtc` 输出语法，不能替代 libfdt/dtc，也不能完整解释 overlay 或厂商属性。

## 通用硬件发现原则

项目不绑定具体设备，没有内置目标板卡或预设 SoC，也不假定一定存在 Device Tree、
GPIO、MDIO 等接口。采集由证据驱动；厂商或板卡适配器应保持为可选扩展。

采集后可检查各类诊断观察是否可用：

```bash
./.venv/bin/python -B scripts/workflow/capabilities.py ./outputs/example-device-session-001
```

`capabilities.json` 中的 `available`／`partial`／`unknown` 描述观察资料的可用程度，
不代表物理外设存在或工作正常。`profiles/examples/` 下的 YAML 示例尚未接入 JSON 配置执行引擎。

## 按能力自适应采集（功能预览）

分阶段工作流先采集 OS、内核、CPU 和内存信息，再只读检查设备树、sysfs、pinctrl、
总线和诊断工具是否可用，仅运行满足条件的深入探针。跳过项及原因会写入记录。
每个探针都会更新 `manifest.json` 检查点，便于检查中断后的会话。

```bash
# SSH／ADB／TTL／本地交互向导
./.venv/bin/python -B scripts/workflow/adaptive.py

# 明确授权后的非交互只读采集（使用预配置 SSH 别名）
./.venv/bin/python -B scripts/workflow/adaptive.py --transport ssh --target my-linux-host \\
  --output ./outputs/new-session-001 --modules auto --yes

# 仅选择指定模块
./.venv/bin/python -B scripts/workflow/adaptive.py --transport local --target local \\
  --modules network,drivers --output ./outputs/new-session-002 --yes
```

**限制：** `--yes` 只明确授权只读探针，不授权写入。TTL 仍仅被动接收。
会话目录必须是新目录，父目录必须已存在。采集文件可能包含主机和网络标识，绝不自动上传。
未指定 `--interactive-shell-approved` 时，这些示例使用旧版逐命令 SSH/ADB 或被动 TTL 路径。
交互式定制应使用上文另行授权的持久适配器。

## 设备目录与交互管理辅助工具

可选的 `scripts/workflow/manage.py` 维护本地设备目录，记录用户定义的稳定设备 ID、
连接方式及目标，并将各次采集会话分开存储。目录中不嵌入密码。

```bash
# 交互菜单
./.venv/bin/python -B scripts/workflow/manage.py

# 枚举已配置的 SSH Host 别名、已授权的 ADB 设备、
# 本地串口名称和本地目标
./.venv/bin/python -B scripts/workflow/manage.py discover

# 登记目标，不连接设备
./.venv/bin/python -B scripts/workflow/manage.py add lab-server --transport ssh --target server-alias

# 查看目录；使用已有分阶段只读引擎采集
./.venv/bin/python -B scripts/workflow/manage.py list
./.venv/bin/python -B scripts/workflow/manage.py collect lab-server --modules hardware,drivers,network

# 检查已保存的会话及分类摘要
./.venv/bin/python -B scripts/workflow/manage.py sessions lab-server
./.venv/bin/python -B scripts/workflow/manage.py inspect lab-server SESSION_ID
```

旧版管理器的设备目录默认保存在 `./outputs/device-manager/registry.json`，
采集文件位于 `./outputs/device-manager/devices/<id>/sessions/<session>/`。
目录及元数据使用严格权限；按 Agent 工作目录约定，`--data-dir` 指定的私有目录必须位于 `./outputs/`。
管理器默认存储位置不再是用户主目录。

连接发现仅枚举候选项。SSH 别名来自主 SSH 配置中的显式 `Host` 条目，
不展开 `Include` 或通配符。ADB 使用 `adb devices`，可能启动本地 ADB 服务。
串口发现只列出设备名，不打开串口。这些枚举不证明候选设备可连接或已认证。

`collect` 默认要求确认；指定 `--yes` 只授权固定的只读证据探针。
旧版管理器的 TTL 仅被动接收，不发送串口字节，但打开适配器可能影响控制信号。
原始文件可能包含设备标识，不得自动发布。

管理器提供终端交互。下文的 localhost 实时状态预览及离线 HTML 查看器已实现，均为查看工具。
尚未实现浏览器设备控制面板、按已认证设备身份自动分组、断点续采和物理引脚图。

## 硬件浏览与任务选择（功能预览）

终端管理器的 **Explore** 功能读取经过 SHA-256 验证的会话证据，构建软件层面的硬件关系图，
浏览节点关系，并生成**不执行操作**的任务计划。

```bash
# 交互模式：在设备管理菜单中选择 7. Explore
./.venv/bin/python -B scripts/workflow/manage.py

# 列出已保存会话中的节点
./.venv/bin/python -B scripts/workflow/manage.py explore lab-server SESSION_ID

# 检查指定节点及其关系
./.venv/bin/python -B scripts/workflow/manage.py explore lab-server SESSION_ID --node 'device:platform:example-controller'

# 为已验证节点生成诊断计划（不对目标执行操作）
./.venv/bin/python -B scripts/workflow/manage.py explore lab-server SESSION_ID \
  --task diagnose --node 'device:platform:example-controller' \
  --goal 'Investigate why the controller is not responding'

# 对会话目录运行独立辅助向导
./.venv/bin/python -B scripts/workflow/explore.py ./outputs/device-manager/devices/lab-server/sessions/SESSION_ID

# 生成安全的 JSON 计划文件，不覆盖已有计划
./.venv/bin/python -B scripts/workflow/explore.py SESSION_DIRECTORY --mode plan \
  --task maintain --output ./outputs/my-plan.json
```

支持 `diagnose`、`maintain`、`image` 三类计划。计划引用观察节点、软件关系及证据缺口，
但不会执行命令、修改配置、构建镜像或授权刷写。维护执行尚未实现；
Explore 的 `image` 计划不会调用下文独立的 VM 镜像流水线。
依赖分析结果前，必须解决证据缺口和会话不完整问题。

此功能目前是文本节点列表，不是可交互的图形节点画布。
板级物理引脚和电气行为不能仅凭软件证据推断。

## 离线图形硬件浏览器（功能预览）

可从已验证的证据会话导出可交互的本地 HTML 文件，浏览时不需要 HTTP 服务、
外部库、CDN 或设备连接。

```bash
# 通过已登记设备的管理器导出（交互菜单中的第 8 项）
./.venv/bin/python -B scripts/workflow/manage.py browse lab-server SESSION_ID

# 自定义输出位置（必须不存在，不覆盖文件）
./.venv/bin/python -B scripts/workflow/manage.py browse lab-server SESSION_ID --output ./outputs/lab-hardware.html

# 直接从已有采集会话导出
./.venv/bin/python -B scripts/workflow/export_html.py SESSION_DIRECTORY --output ./outputs/hardware.html
```

在本地浏览器打开 HTML。左侧支持搜索和按设备／驱动／设备树节点筛选；
右侧展示节点属性、关联节点、证据来源和采集缺口。点击关联关系可跳转到对应节点。

安全与范围：

- 渲染前验证会话证据的 SHA-256。
- 以转义后的 JSON 嵌入数据，并使用私有文件权限。
- 页面具有严格的 Content Security Policy，不访问网络。
- 数据可能包含私有设备标识；未审查或脱敏前不要上传 HTML。
- 这是离线查看器，不是服务端应用或交互式设备控制器。节点属性属于软件证据，
  不是已验证的物理排针或电气测量结果。
- 任务执行仍被禁用；diagnose／maintain／image 仅创建计划。

## 镜像可移植性流水线（初步后端）

完成目标设备证据采集后，区分 `virtual-machine` 与 `physical-device`。
规划器验证所有源证据文件的哈希，并用独立获得的可信 SHA-256 检查本地基础镜像。
它会记录目标架构、声明的源架构、待满足条件及输出格式。

```bash
# 为已验证基础镜像和 VM 目标生成计划
./.venv/bin/python -B scripts/workflow/image_plan.py SESSION_DIRECTORY \
  --target virtual-machine --format qcow2 \
  --source ./outputs/sources/base.img \
  --sha256 VERIFIED_64_HEX_SHA256 --source-arch amd64 \
  --output ./outputs/image-plan.json

# 也可从已登记设备创建相同计划
./.venv/bin/python -B scripts/workflow/manage.py image-plan lab-server SESSION_ID \
  --target virtual-machine --format qcow2 \
  --source ./outputs/sources/base.img \
  --sha256 VERIFIED_64_HEX_SHA256 --source-arch amd64 \
  --output ./outputs/image-plan.json

# 仅在计划报告 build_allowed=true 后执行离线转换
# （构建主机需已安装 qemu-img）
./.venv/bin/python -B scripts/workflow/build_image.py ./outputs/image-plan.json \
  --output ./outputs/output.qcow2
```

输出镜像及 `output.qcow2.manifest.json` 包含 SHA-256 和虚拟磁盘大小。
转换器只转换**已经检查的源镜像**；源镜像检查不证明能启动。
它不会采集正在运行的系统、安装驱动、定制软件包、重置机器身份，
也不会让镜像在任意硬件上可启动。部署前需另行进行匹配机器类型、固件及虚拟驱动的 VM 启动测试。

对于 `--target physical-device --format raw`，规划器会返回明确阻断项。
在板级引导加载程序、内核／DTB 或 ACPI 支持、固件、存储分区及恢复路径得到验证前，
不允许组装实体镜像。仅改变镜像格式不能让通用 ARM64 系统适配所有硬件。

输入和输出均不得使用块设备。转换器拒绝 `/dev`、`/proc`、`/sys` 下的路径、
覆盖现有输出、不支持的源格式及带 QEMU backing file 的镜像。
保留镜像完整性元数据和许可记录。源架构必须经过来宾检查，并同时匹配声明与发现的目标架构。
工具缺失或检查不完整会阻断转换；单独声明 `--source-arch` 不能授权执行。

## 方案授权的 Skill 实时状态预览

**Agent 负责交互，浏览器仅作观察。** 先选定连接方式和实际接口，再说明并确认包含回环状态页的
只读方案。确认后后端先启动监控再运行探针，返回实际 URL。用户可以明确退出监控，仍继续采集。

已有会话或正在采集的会话可以使用：

```bash
./.venv/bin/python -B scripts/workflow/preview.py SESSION_DIR --port 8765
# 浏览器地址：http://127.0.0.1:8765/
```

页面每两秒轮询本地检查点。后续的分析、镜像规划、转换和验证阶段，
Agent 可发布安全的阶段和计数信息：

```bash
./.venv/bin/python -B scripts/workflow/status.py SESSION_DIR \
  --stage image-plan --state running --completed 1 --total 3
```

预览只读，仅绑定 `127.0.0.1`，没有命令 API，不提供原始采集文件。
它不是设备管理器，也不是使用 Skill 的前提。前台运行时可用 Ctrl+C 停止。
隐私、授权和生命周期规则见[可选实时预览](references/live-preview.md)。

### Skill 管理的预览生命周期（方案授权）

Agent 说明完整连接和监控方案并获得确认后，使用 `--preview-approved` 在采集前启动观察服务，
无需第二次询问是否开启预览。内部 CLI 的 `--yes` 只授权只读探针；监控授权不允许修改目标系统。

```bash
./.venv/bin/python -B scripts/workflow/adaptive.py \
  --transport ssh --target trusted-host-alias \
  --output ./outputs/run-003 --yes --preview-approved
```

创建会话目录后，采集器启动仅限本机的预览，返回经过检查的 URL，然后继续采集。
预览失败不会阻断采集。页面可保留用于结果复查，直到用户要求关闭。

```bash
./.venv/bin/python -B scripts/workflow/preview_control.py status ./outputs/run-003
./.venv/bin/python -B scripts/workflow/preview_control.py stop ./outputs/run-003
```

对于已有会话，`preview_control.py start SESSION_DIR --approved` 可启动预览而不重新采集。
辅助工具选择可用本地端口、检查观察服务响应，并仅保存私有进程元数据。
已停止或过期的预览不能授权系统操作；`clear-stale` 只清除过期本地记录，
不会发送未经检查的进程信号。会话目录必须为私有目录（0700）。
参见[实时预览](references/live-preview.md)。

每次迭代结束，Agent 应简要报告结果、实际测试状态和一个明确的下一步。
支持的聊天界面应提供“继续下一步”按钮，无需用户重新输入命令。

### 镜像流水线的实时进度

用户批准含本地监控的方案后，镜像辅助工具会通过已验证的会话引用自动更新同一个预览。
阶段包括 `image-plan`、`image-build`、`rootfs-build`、`first-boot`（NoCloud）和
`verify`（包括来宾健康检查）。各阶段报告具体里程碑，并区分完成、兼容性阻断和执行失败。
QEMU 冒烟尝试不能证明来宾成功启动。

没有预览时，不自动写状态文件；预览关闭后不会隐式重启。
Skill 负责控制，浏览器仅观察。阶段映射和隐私规则见[实时预览](references/live-preview.md)。

### 只读源镜像检查

转换前，Agent 可检查已有 RAW/QCOW2 源镜像并形成可追溯的兼容性结论。
需要 `qemu-img` 和只读 libguestfs 工具，以确认 GPT/MBR 分区、来宾 Linux 架构和 OS、
已安装内核、BIOS/UEFI 模式及引导加载程序。证据缺失会阻断转换。

```bash
./.venv/bin/python -B scripts/workflow/image_inspect.py ./outputs/sources/base.img \
  --sha256 TRUSTED_SOURCE_SHA256 \
  --output ./outputs/source-inspection.json

./.venv/bin/python -B scripts/workflow/image_plan.py SESSION_DIR \
  --target virtual-machine --format qcow2 --source ./outputs/sources/base.img \
  --sha256 TRUSTED_SOURCE_SHA256 --source-arch amd64 \
  --output ./outputs/image-plan.json
```

`image-plan.json` 包含观察到的源镜像信息及逐项证据矩阵。
即使可编辑的 JSON 计划声称允许构建，`build_image.py` 仍会拒绝未经检查或已经变化的镜像。
实体镜像仍需独立验证板级组件。见[镜像构建](references/image-building.md)。
macOS 合成检查测试已通过；真实 libguestfs 检查尚未验证。

### 离线 Portable RootFS Builder（仅限虚拟机）

对于通过 `image_plan.py` 兼容性检查的源镜像，Skill 可预览有限的 Linux VM RootFS 定制方案，
并在单独明确授权后构建产物包。实体板卡 IMG 需要独立验证的 BSP，目前仍被阻断。

严格配置示例见 `profiles/examples/rootfs-config.json`。
支持 hostname、MOTD 和仅使用公钥的 NoCloud 首次启动种子。
构建器克隆原始镜像，使用 `virt-customize --no-network` 仅修改私有副本，
通过限定范围的 `virt-sysprep` 清理 machine-id／SSH 主机密钥，再检查来宾镜像并发布哈希和清单。
它不安装软件包，不执行任意命令，也不证明能启动。

```bash
# 检查依赖和具体操作计划，不写入镜像。
./.venv/bin/python -B scripts/workflow/rootfs_builder.py ./outputs/image-plan.json \
  --config ./outputs/rootfs-config.json --dry-run

# 仅在 Agent 获得单独明确授权后执行。
./.venv/bin/python -B scripts/workflow/rootfs_builder.py ./outputs/image-plan.json \
  --config ./outputs/rootfs-config.json --output-dir ./outputs/new-rootfs-bundle --approved

# 独立校验已发布的镜像、NoCloud 种子及哈希。
./.venv/bin/python -B scripts/workflow/rootfs_builder.py \
  --verify-bundle ./outputs/new-rootfs-bundle
```

构建主机需要 qemu-img 和 libguestfs。源来宾必须关机，且包含 cloud-init 配置。
NoCloud 首次初始化、SSH 密钥重新生成、VM 启动及机器专属秘密的清理，
在单独审计前仍未验证。输出不适合直接刷入实体设备。
完整约束见[RootFS Builder 工作流](references/rootfs-building.md)。

产物包还包含脱敏后的 `build-config.json`（不含原始公钥文件路径）和
用于追溯的 `image_plan_sha256` 字段。构建清单校验配置与镜像哈希。

### QEMU 首次启动健康检查（仅限 amd64 VM）

Skill 为完整的 Portable RootFS Builder 产物包提供单独授权的隔离首次启动健康检查：

```bash
./.venv/bin/python -B scripts/workflow/rootfs_builder.py --verify-bundle ./outputs/rootfs-bundle
./.venv/bin/python -B scripts/workflow/verify_first_boot.py \
  --bundle ./outputs/rootfs-bundle --timeout 300 \
  --report ./outputs/first-boot-health.json --approved

# UEFI 来宾还需提供：
# --ovmf-code /trusted/OVMF_CODE.fd --ovmf-vars /trusted/OVMF_VARS.fd
```

验证器使用可丢弃的 QEMU TCG 快照，限制来宾 DHCP，不提供互联网／主机路由或端口转发，
并使用私有 UNIX Guest Agent socket 及已验证的 NoCloud 种子 ISO。
来宾必须预装 qemu-guest-agent 和 Python 3。随机挑战值与固定只读脚本用于检查 Linux 启动、
systemd、cloud-init、预期 instance ID、hostname、初始化后的 machine-id 和 SSH 主机密钥、
SSH 服务及已配置的网络接口。全部通过后才能设置 `boot_confirmed=true`。
退出码和串口输出不构成证明；缺少前提、超时或检查失败会保留 `blocked`（阻断）或 `failed`（失败）状态。
报告将健康检查结果保存为布尔值，同时记录产物哈希、状态等元数据。
不保存机器 ID、密钥、秘密或原始来宾命令输出。
关机后会重新计算原始磁盘哈希。

RootFS 暂存阶段仅在私有克隆中清除过期的 `/var/lib/cloud`，以允许新的 NoCloud 实例初始化。
构建结果保留原发现会话引用，供可选预览使用。没有增加实体板卡 BSP、固件或刷写支持。
见[首次启动验证](references/first-boot-verification.md)。

### macOS 本地测试路径兼容性

Python `tempfile.TemporaryDirectory()` 可能返回 `/var/folders` 下的路径，
而 macOS 将其解析为 `/private/var/folders`。
离线 RootFS 构建器、Cloud Image E2E 工具和 Lima 路径校验器会规范化经过检查的系统别名。
仍拒绝用户创建的符号链接、已有输出、目录穿越及块设备／伪文件系统目标。
在采集器或 QEMU 有意规范化路径的地方，测试使用解析后的路径比较。

标准命令 `./.venv/bin/python -B -m unittest discover -s tests -v` 已在 macOS 默认临时目录下通过，
运行时获得了本地测试 socket 权限。套件中的 QEMU 和 libguestfs 执行使用模拟；
本地预览 HTTP 和模拟 Guest Agent socket 测试确实运行。
数量和范围见[验证记录](references/roadmap.md#validation-record)。

### Ubuntu Cloud Image 端到端辅助工具（真实执行未验证）

`scripts/workflow/cloud_image_e2e.py` 在准备好的 Linux 构建主机上协调预检、源镜像校验、
检查与规划、RootFS 定制、产物包校验和来宾健康验证。它接受可信本地镜像，或在明确要求时，
从固定的 Ubuntu Cloud Image URL 下载并检查预设 SHA-256。
这是哈希校验，不是上游签名验证；测试套件没有验证固定下载地址是否可用。

离线构建和 VM 启动需要分别明确授权。工具、固件或来宾依赖缺失时会阻断，
不会自动安装 QGA 或其他软件包。完整流水线测试使用合成数据，不能证明真实构建或启动。
原生 Linux 与现有 Mac Lima 适配器已实现，但真实 Lima 执行尚未验证。
