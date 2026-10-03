<p align="center"><img src="docs/assets/banner.svg" alt="Releasecraft — 可检查、可重建的源码发布包" width="100%"></p>
<p align="center"><strong>保留必要功能，让每个取舍有依据，让发布包接受验证。</strong></p>
<p align="center"><a href="CHANGELOG.md"><img src="docs/assets/version.svg" alt="版本 1.1.0"></a> <a href="#快速开始"><img src="docs/assets/python.svg" alt="Python 3.11+"></a> <a href="LICENSE"><img src="docs/assets/license.svg" alt="MIT 许可证"></a></p>
<p align="center"><a href="README.md">English</a> · <strong>简体中文</strong> · <a href="docs/DOWNLOADS.md">下载说明</a> · <a href="docs/DESKTOP.md">桌面界面</a> · <a href="docs/POLICY.md">配置参考</a></p>

## AI 已经把项目做出来了，下一次也应打出同样的发布包

项目能运行，不代表整个工作目录都适合公开。目录中可能混有本地凭据、实验脚本、生成报告和并行开发副本。
每次让不同助手“清理一下”，得到的文件集合可能不同。Releasecraft 把保留、排除和待审阅的理由保存为明确规则，
让另一个人或智能体无需读取原来的私人对话，也能复现同一份源码发布包。

先点击 **先分析**，再打开 **检查发布内容**。对不明确的文件填写理由并保存策略，重新分析后再准备发布包。
也可以直接使用默认 **准备发布包**；真正不明确的资源、许可或敏感内容仍会阻断。策略不会偷偷自动加载。

已审阅决定绑定文件哈希；文件变化后必须重新审阅。测试、样例、快照、依赖锁文件和必需数据不会因为像“杂物”就丢弃。
共享智能体说明与认证状态分别处理，不能把整个智能体目录一概删除。原始项目文件始终保留。

大文件按块扫描、复制、写入 ZIP、校验和解压，不再使用默认 256 MiB 项目上限；会检查实际可用磁盘空间。
代码解析、归档元数据、文件数量和证据仍有独立边界，达到边界明确阻断，不能把未扫描部分当作已通过。
详见[文件决策](docs/AI_PROJECTS.md)、[审阅与复现](docs/REVIEW.md)和[资源边界](docs/SCAN_LIMITS.md)。

## 从项目目录到可检查的源码发布包

Releasecraft 面向 Python、Notebook、数据处理及常见 Node.js/TypeScript 项目，使用有界、可重放的静态规则识别源码、必要资源和维护资料，记录文件决策，生成并验证源码候选包。
桌面窗口、命令行和受令牌保护的本地 HTTP 界面共享同一核心。分析不需要模型 API、付费账号或远程服务。

原有源码文件保持不变。桌面流程默认在项目内创建独立的 `releasecraft-output` 输出目录；完整私有计划保存在项目外。
依赖、敏感内容、许可或扫描完整性存在未解决问题时，程序会阻断，不会通过删减必要功能强行打包。

## 下载与版本

当前版本的 Python 包号为 **1.1.0**，Git 标签为 **v1.1**。请从[官方 GitHub Release](https://github.com/WilliamDJJ/releasecraft/releases/tag/v1.1)下载，并按[下载说明](docs/DOWNLOADS.md)核对校验和。[源码仓库](https://github.com/WilliamDJJ/releasecraft)包含各平台共用的代码、测试和文档。

| 平台 | 安装与启动 | 前提 |
| --- | --- | --- |
| Windows ZIP | 双击 `Start Releasecraft.cmd` | Python 3.11+，含 pip、venv 和 Tcl/Tk |
| Linux tar.gz | `sh install.sh` 后运行 `sh releasecraft-gui.sh` | Python 3.11+、venv、匹配的 Tk 包及图形桌面 |
| 源码 ZIP / wheel | 审阅、维护或自定义安装 | Python 3.11+ |

平台包包含同一个 wheel，可离线安装到自身目录的 `.venv`，但不是内置 Python 的独立可执行程序。安装器拒绝覆盖已有环境。

## 快速开始

### Windows

解压 Windows ZIP，在其中的 `releasecraft` 文件夹双击 **Start Releasecraft.cmd**。首次启动会显示离线安装窗口。

1. 在可见的 **中文 / English** 选择器中切换语言
2. 点击浏览，选择含 README 和许可证、功能完整的项目根目录
3. 保留默认源码范围，点击准备发布包
4. 检查问题详情；候选包完成后点击打开输出

语言偏好保存在用户本地配置中，不写入项目或公开包。运行中切换语言不会重新启动任务，取消会在安全检查点停止。

默认输出为项目内的 `releasecraft-output`。只有本应用为该项目创建并登记的目录，才会在后续扫描中排除。
已有但未登记的同名目录不会被接管；每次成功运行创建全新的子目录。也可选项目外的专用输出位置。
参阅[桌面流程](docs/DESKTOP.md)了解权限、恢复和并发限制。

### Linux

在已具备 Python、venv 和 Tk 的图形桌面中，进入解压后的平台包目录：

```sh
sh install.sh
sh releasecraft-gui.sh
```

命令行入口为 `sh releasecraft.sh --help`。无图形环境可使用 CLI 或 `serve` 本地 HTTP 界面。
HTTP 的 `--work` 目录必须位于项目外；不要将 CLI 的任意输出路径与桌面的专用目录规则混淆。

### 从源码安装

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\releasecraft-gui.exe
```

Linux 对应执行 `python3 -m venv .venv`、`.venv/bin/python -m pip install .` 和 `.venv/bin/releasecraft-gui`。
源码安装可能获取构建依赖；平台包的 wheel 安装器不联网。不需要管理员权限或更改 PowerShell 执行策略。

## 候选包与运行验证

桌面界面只调用确定性的分析、构建和静态校验，不运行所选项目代码。**CANDIDATE 不等于 READY**。
以下命令演示如何验证自带、已审阅的合成示例；重复运行请使用新的工作和输出目录：

```sh
releasecraft plan examples/demo --config examples/demo-policy.json --work ../demo-work
releasecraft build examples/demo --plan ../demo-work/plan.json --output ../demo-release
releasecraft verify ../demo-release/release.zip
releasecraft validate ../demo-release/release.zip --backend trusted --trust-project --report ../demo-validation.json
```

`build` 和静态 `verify` 返回 3（CANDIDATE）；适用的运行验证通过后才返回 0（READY）。
`trusted` 的新 Python 环境不是安全沙箱，只能用于已审阅且可信的代码。不可信项目需要独立 Docker 后端和预装、digest 固定的镜像；缺少隔离时返回 BLOCKED，不执行代码。程序不会自动拉取镜像。

## 范围与安全门槛

默认保留可维护开源源码包所需的代码、测试、文档、Notebook 和已识别资源。界面中的范围选项不能绕过依赖、许可或敏感内容检查；取消必需资源会产生明确阻断。
密码、API 令牌、私钥不能通过勾选或 include 覆盖发布。可使用 `${API_KEY}` 等无值模板，真实配置放在发布内容之外。

动态资源、跨命令生成文件的执行顺序、不明确的原生构建行为及未识别数据，可能仍需审阅。工具不能推断私人历史中的最终批准版本，也不会依据修改时间自动选择“最新版”。
达到扫描上限时，计划明确标为不完整且 BLOCKED；保留的计数不是整个未扫描目录的总量。

`plan` 默认输出分组摘要；完整私有证据保存在 `plan.json`，`--details` 可输出完整 JSON。请勿将私有计划自动放入公开发行包。

- [桌面工作流](docs/DESKTOP.md)：语言、进度、取消、输出登记与恢复
- [默认分析](docs/DEFAULTS.md)：已支持的静态模式和局限
- [策略参考](docs/POLICY.md)：资源、排除、运行命令和功能声明
- [扫描限制](docs/SCAN_LIMITS.md)：条目、字节、深度和证据边界
- [验证契约](docs/VERIFICATION.md)：回归和平台验收要求
- [发布指南](docs/RELEASING.md)：可重复构建、验收和人工发布
- [更新记录](CHANGELOG.md)：各公开版本的功能

## 测试与构建

```sh
python -m unittest discover -s tests -v
python scripts/build_distributions.py --output ../releasecraft-artifacts
```

使用已安装 Releasecraft 的环境；构建还需 setuptools 68+ 和 wheel。Node 用于相关执行与界面脚本测试；原生桌面测试需要 Tk 和可用显示环境。跳过的测试必须单独记录，不能计为通过。
最终验收报告绑定准确的归档哈希；有限样本的通过不代表任意项目都能零配置自动发布。

桌面的 **存储 / 历史** 窗口可查看私有存储用量、导出审计并清理归属已验证的暂存文件。
完整审计按明确上限保留；未知或运行中的内容不会被删除，必要时会阻断新任务。
详见[存储与历史](docs/DESKTOP.md#storage-and-history)。
