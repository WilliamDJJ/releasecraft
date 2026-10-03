"""Shared desktop translations; machine-readable evidence keeps stable identifiers."""
EN = {
    "metrics_result":"Payload files {files}   Archive bytes {bytes}   Elapsed {seconds} s",
    "title":"Releasecraft — Prepare source package", "preview":"v{build}",
    "source":"Project folder", "output":"Output folder", "browse":"Browse…", "elsewhere":"Elsewhere…",
    "no_edit":"A new package per run. Your source files are never edited.", "scope":"Source package",
    "scope.Tests":"Tests", "scope.Documentation":"Documentation", "scope.Notebooks":"Notebooks", "scope.Samples":"Samples", "scope.Reproducibility":"Reproducibility",
    "gates":"Required files, secrets and licenses stay checked when options change.",
    "advanced_closed":"▸ Advanced options", "advanced_open":"▾ Advanced options",
    "profile":"Profile", "profile.source":"Source package", "profile.runtime":"Runtime bundle", "profile.research":"Research bundle",
    "strip":"Strip saved notebook outputs", "policy":"Policy file (optional)", "choose":"Choose…",
    "exclude":"Exclude patterns", "patterns_help":"Separate patterns with ;  •  Git ignores do not decide release membership.",
    "progress":"Progress", "idle":"Choose a project to prepare", "no_execution":"Source analysis only; project commands will not run.",
    "metrics":"Phase files {files} / {total}    Bytes {bytes}    Elapsed {seconds}s", "unknown":"unknown",
    "details":"Problem details", "config_help":"Safe config help", "open_output":"Open output", "cancel":"Cancel", "prepare":"Prepare package",
    "choose_source":"Choose project folder", "choose_output":"Choose parent folder for releasecraft-output", "choose_policy":"Choose reviewed policy", "json_policy":"JSON policy",
    "choose_folders_title":"Choose folders", "choose_folders":"Select the project folder and output folder first.",
    "policy_rejected_title":"Policy rejected", "policy_rejected":"Check the policy file and portable exclude patterns. No project files were changed.",
    "workspace":"Preparing safe workspace…", "cancelling":"Cancelling safely…", "cancel_wait":"Finishing the current bounded operation; no partial package will be published.",
    "candidate":"Package prepared — static checks passed", "blocked":"Blocked — review the problems", "cancelled":"Cancelled — no package published", "failed":"Operation did not complete",
    "candidate_limit":"CANDIDATE: runtime has not been verified.", "source_unchanged":"Your original source files were not edited.",
    "details_title":"Releasecraft — Problem details", "output_rejected":"Use a readable local project and an unused releasecraft-output folder. Existing user folders are never adopted. Links, concurrent runs or changed inputs are rejected.",
    "details_limit":"Display limited to 1,000 details; the private audit retains available evidence.", "close":"Close",
    "safe_config_title":"Safe configuration", "safe_config":"Never publish live keys or passwords. Use a reviewed .env.example with placeholders, for example:\n\nAPI_KEY=${API_KEY}\nPASSWORD=${PASSWORD}\n\nKeep actual values outside the release. Detected secrets cannot be approved by an option or policy override. Releasecraft does not edit your configuration.",
    "open_error_title":"Cannot open output", "open_error":"Open the selected output folder in your file manager.",
    "preference_error":"Language changed for this window; local preference could not be saved.",
    "Scanning":"Scanning files", "Analyzing":"Analyzing dependencies and safety", "Checking snapshot":"Checking frozen input", "Copying":"Copying selected files",
    "Writing archive":"Writing archive", "Verifying archive":"Verifying archive", "Completing staging":"Completing private staging", "Verifying":"Verifying candidate", "Publishing":"Publishing verified candidate",
    "action.limit":"Choose a smaller coherent component root; this plan is incomplete.",
    "action.license":"Supply or review the release license. An option cannot replace release permission.",
    "action.secret":"Remove detected secret/private content from selected source. Use placeholders in a reviewed configuration template.",
    "action.resource":"Fix the missing resource or declaration, or enable the required file category. Required exclusions cannot create a valid release.",
    "action.dynamic":"Provide explicit reviewed resource/workflow declarations, or select a coherent supported component root.",
    "action.provenance":"Provide third-party source and license evidence before inclusion.",
    "action.path":"Use readable regular files without links or reparse points. Inspect the private path identifier.",
    "action.npm":"Keep only supported literal npm preferences. Credentials and machine-specific configuration cannot be approved by inclusion overrides.",
    "action.other":"Review the private evidence and correct the source or its explicit declarations.",
}

ZH = {
    "metrics_result":"发布文件 {files}   归档字节 {bytes}   已用 {seconds} 秒",
    "title":"Releasecraft — 准备源码发布包", "preview":"v{build}",
    "source":"项目文件夹", "output":"输出文件夹", "browse":"浏览…", "elsewhere":"其他位置…",
    "no_edit":"每次生成独立发布包，不修改原始源码文件。", "scope":"源码发布范围",
    "scope.Tests":"测试", "scope.Documentation":"文档", "scope.Notebooks":"笔记本", "scope.Samples":"示例数据", "scope.Reproducibility":"复现资料",
    "gates":"更改选项不会跳过必需文件、敏感信息或许可证检查。",
    "advanced_closed":"▸ 高级选项", "advanced_open":"▾ 高级选项",
    "profile":"发布类型", "profile.source":"源码发布包", "profile.runtime":"运行文件包", "profile.research":"研究资料包",
    "strip":"清除笔记本已保存输出", "policy":"策略文件（可选）", "choose":"选择…",
    "exclude":"排除模式", "patterns_help":"使用 ; 分隔模式。Git 忽略规则不决定发布文件范围。",
    "progress":"处理进度", "idle":"请选择要处理的项目", "no_execution":"仅分析源码，不执行项目命令。",
    "metrics":"本阶段文件 {files} / {total}    字节 {bytes}    已用 {seconds} 秒", "unknown":"未知",
    "details":"问题详情", "config_help":"安全配置帮助", "open_output":"打开输出", "cancel":"取消", "prepare":"准备发布包",
    "choose_source":"选择项目文件夹", "choose_output":"选择 releasecraft-output 的父文件夹", "choose_policy":"选择已审阅策略", "json_policy":"JSON 策略",
    "choose_folders_title":"选择文件夹", "choose_folders":"请先选择项目文件夹和输出文件夹。",
    "policy_rejected_title":"策略未通过检查", "policy_rejected":"请检查策略文件和可移植的排除模式。项目文件未被修改。",
    "workspace":"正在准备安全工作区…", "cancelling":"正在安全取消…", "cancel_wait":"等待当前有界操作结束，不会发布不完整的文件包。",
    "candidate":"发布包已准备 — 静态检查通过", "blocked":"已阻断 — 请查看问题", "cancelled":"已取消 — 未发布文件包", "failed":"操作未完成",
    "candidate_limit":"CANDIDATE：尚未验证项目运行结果。", "source_unchanged":"原始源码文件未被修改。",
    "details_title":"Releasecraft — 问题详情", "output_rejected":"请选择可读取的本地项目和未使用的 releasecraft-output 文件夹。不会接管已有用户文件夹。链接、并发操作或发生变化的输入会被拒绝。",
    "details_limit":"界面最多显示 1,000 条详情，私有审计保留可用证据。", "close":"关闭",
    "safe_config_title":"安全配置", "safe_config":"不要发布真实密钥或密码。请使用经过审阅、仅含占位符的 .env.example，例如：\n\nAPI_KEY=${API_KEY}\nPASSWORD=${PASSWORD}\n\n真实值应保留在发布包之外。选项或策略不能批准检测到的敏感值。Releasecraft 不会修改你的配置。",
    "open_error_title":"无法打开输出", "open_error":"请在文件管理器中打开所选输出文件夹。",
    "preference_error":"当前窗口语言已切换，但无法保存本地偏好。",
    "Scanning":"正在扫描文件", "Analyzing":"正在分析依赖与安全性", "Checking snapshot":"正在核对冻结输入", "Copying":"正在复制选定文件",
    "Writing archive":"正在写入归档", "Verifying archive":"正在校验归档", "Completing staging":"正在完成私有暂存", "Verifying":"正在校验候选包", "Publishing":"正在保存已校验候选包",
    "action.limit":"请选择规模更小且功能完整的组件根目录。当前计划不完整。",
    "action.license":"请补充或审阅发布许可证。选项不能代替发布授权。",
    "action.secret":"请从选定源码中移除检测到的密钥或私有内容，并在已审阅的配置模板中使用占位符。",
    "action.resource":"请补充缺失资源或声明，或重新启用必需的文件类别。排除必需资源不能生成有效发布包。",
    "action.dynamic":"请提供经过审阅的明确资源或工作流程声明，或选择功能完整且受支持的组件根目录。",
    "action.provenance":"请先补充第三方来源与许可证证据。",
    "action.path":"请使用可读的普通文件，不要使用链接或重解析点。请在私有计划中核对路径标识。",
    "action.npm":"仅保留受支持的 npm 字面量配置。包含选项不能批准凭据或机器特有配置。",
    "action.other":"请审阅私有证据，并修正源码或明确声明。",
}


EN.update({
    "install.title":"Releasecraft — Local installation", "install.welcome":"Welcome to Releasecraft",
    "install.help":"Install the bundled wheel in this folder.\nNo download, account or system-wide changes.",
    "install.ready":"Ready to install locally", "install.running":"Creating the local environment…",
    "install.button":"Install and open Releasecraft", "install.failed":"Installation did not finish.",
    "install.failure_help":"Check write permissions and Python's venv/Tk components. Extract a fresh folder before retrying. Existing environments are never overwritten.",
    "install.existing":"An existing environment will not be overwritten. Extract a fresh distribution folder to install again.",
    "install.wait":"Please wait for local installation to finish.", "install.python":"Python 3.11 or newer is required.",
})
ZH.update({
    "install.title":"Releasecraft — 本地安装", "install.welcome":"欢迎使用 Releasecraft",
    "install.help":"将随附的软件包安装到当前文件夹。\n无需下载、账户或修改系统环境。",
    "install.ready":"可以开始本地安装", "install.running":"正在创建本地运行环境…",
    "install.button":"安装并打开 Releasecraft", "install.failed":"安装未完成。",
    "install.failure_help":"请检查写入权限和 Python 的 venv/Tk 组件。重试前请解压到新的文件夹。不会覆盖已有运行环境。",
    "install.existing":"不会覆盖已有运行环境。请解压到新的发行包文件夹后再安装。",
    "install.wait":"请等待本地安装完成。", "install.python":"需要 Python 3.11 或更高版本。",
})


def translate(key, language="en", **values):
    return (ZH if language == "zh" else EN)[key].format(**values) if values else (ZH if language == "zh" else EN)[key]


def action_key(code):
    if code == "insufficient-disk-space": return "action.space"
    if code in ("review-decision-stale", "review-decision-missing"): return "action.stale"
    if code in ("generated-test-output-review", "user-review-required"): return "action.review"
    if code == "parser-file-limit": return "action.parser"
    if code == "agent-config-needs-review": return "action.agent"
    if code.startswith(("scan-", "analysis-")): return "action.limit"
    if code in ("missing-license", "license-needs-review", "license-excluded"): return "action.license"
    if code == "sensitive-content": return "action.secret"
    if code in ("missing-resource", "explicit-resource-missing", "dependency-not-included"): return "action.resource"
    if code.startswith("dynamic-") or code in ("absolute-resource", "unclassified-resource", "binary-needs-classification"): return "action.dynamic"
    if code == "third-party-provenance": return "action.provenance"
    if code in ("unsafe-or-unreadable-file", "unreadable-directory"): return "action.path"
    if code == "npm-config-needs-review": return "action.npm"
    return "action.other"

EN.update({'storage.title': 'Storage / History', 'storage.help': 'Keep up to 20 private audits (64 MiB total), 100 compact summaries and 1 GiB private state. Export needed evidence before clearing. Public packages are never removed here.', 'storage.refresh': 'Refresh', 'storage.export': 'Export selected audit', 'storage.clean': 'Clean staging / expired', 'storage.clear': 'Clear full audits', 'storage.id': 'Run ID', 'storage.status': 'Result', 'storage.bytes': 'Audit bytes', 'storage.cleanup': 'Retention', 'storage.working': 'Checking owned private storage…', 'storage.unknown': 'Unregistered, changed or linked content is retained. An empty list does not mean all private storage is removable.', 'storage.unavailable': 'Private storage is busy, unsafe or over its inspection bound. Active operations and unknown content remain untouched.', 'storage.usage': 'Measured private bytes: {bytes} / {limit} · Entries: {entries}', 'storage.retained': 'Review needed', 'storage.audit': 'Full audit retained', 'storage.expired': 'Summary only', 'storage.cleaned': 'Maintenance completed. Unchanged registered staging and expired audits were eligible; review-needed content was retained.', 'storage.cleared': 'Eligible full audits cleared; compact summaries and public packages remain. Review-needed content was retained.', 'storage.exported': 'Exact private audit exported. Keep this evidence private.', 'storage.confirm': 'Clear eligible full private audits? Export needed evidence first. Public packages and compact summaries remain. Unknown, changed and active work is retained.', 'storage.wait': 'Please wait for the current storage operation to finish.', 'storage.warning': 'Package result is separate from cleanup: some private or pending content needs review. Open Storage / History.', 'storage.blocked': 'STORAGE_BLOCKED: private space, evidence limits or safe ownership could not be established. Inspect Storage / History; do not delete unknown content.', 'storage.state.RUNNING': 'Running', 'storage.state.INTERRUPTED': 'Interrupted', 'storage.state.CANDIDATE': 'Candidate', 'storage.state.BLOCKED': 'Blocked', 'storage.state.FAILED': 'Failed', 'storage.state.CANCELLED': 'Cancelled'})
ZH.update({'storage.title': '存储 / 历史', 'storage.help': '最多保留 20 份完整私有审计（合计 64 MiB）、100 条摘要和 1 GiB 私有状态。清理前请导出需要的证据。此处不会删除公开发布包。', 'storage.refresh': '刷新', 'storage.export': '导出选中审计', 'storage.clean': '清理暂存 / 过期审计', 'storage.clear': '清除完整审计', 'storage.id': '运行标识', 'storage.status': '结果', 'storage.bytes': '审计字节', 'storage.cleanup': '保留状态', 'storage.working': '正在检查已登记的私有存储…', 'storage.unknown': '未登记、被修改或含链接的内容将保留。列表为空不代表所有私有存储都可以删除。', 'storage.unavailable': '私有存储忙碌、不安全或超出检查上限。正在运行的任务和未知内容不会被删除。', 'storage.usage': '已测量私有字节：{bytes} / {limit} · 条目：{entries}', 'storage.retained': '需要检查', 'storage.audit': '保留完整审计', 'storage.expired': '仅保留摘要', 'storage.cleaned': '维护已完成。仅处理登记且未变化的暂存及过期审计；需要检查的内容已保留。', 'storage.cleared': '符合条件的完整审计已清除；摘要和公开发布包保留。需要检查的内容已保留。', 'storage.exported': '已导出原始私有审计。请妥善保管，勿公开其中的私有证据。', 'storage.confirm': '清除符合条件的完整私有审计吗？请先导出需要的证据。公开发布包和摘要会保留。未知、被修改及运行中的内容不会被删除。', 'storage.wait': '请等待当前存储操作完成。', 'storage.warning': '发布结果与清理结果分开记录：部分私有或待发布内容需要检查。请打开“存储 / 历史”。', 'storage.blocked': 'STORAGE_BLOCKED：无法确认私有空间、证据上限或安全归属。请查看“存储 / 历史”，不要删除未知内容。', 'storage.state.RUNNING': '运行中', 'storage.state.INTERRUPTED': '已中断', 'storage.state.CANDIDATE': '候选包', 'storage.state.BLOCKED': '被阻断', 'storage.state.FAILED': '失败', 'storage.state.CANCELLED': '已取消'})


EN.update({
    "Reading": "Reading and hashing", "Extracting": "Extracting verified archive",
    "PLANNED": "Plan complete — review contents before packaging",
    "result.PLANNED": "Plan complete — review contents before packaging",
    "storage.available_space": "available disk space",
    "storage.help": "Keep up to 20 private audits (64 MiB total) and 100 summaries. Active staging is sized against available disk space. Export needed evidence before clearing. Public packages are never removed here.",
    "review.analyze": "Analyze first", "review.title": "Review release contents",
    "review.help": "Inspect every decision. Select files, enter a reason, and save a policy for this tool and other people or agents to reuse. Safety, dependencies and license gates still apply. No original file is deleted. CANDIDATE is not runtime verified.",
    "review.path": "File", "review.state": "Decision", "review.reason": "Review reason", "review.size": "Bytes",
    "review.include": "Include", "review.exclude": "Exclude", "review.review": "Needs review",
    "review.save": "Save policy…", "review.saved": "Policy saved and selected. Analyze again to apply it. Decisions are tied to exact file hashes; changes require a fresh review.",
    "review.rejected": "Enter a reason and select ordinary files. Secrets, private state, missing rights and parser/safety findings require correction, not inclusion approval.",
    "review.save_error": "Choose a new policy filename outside the selected project. Existing files are not overwritten.",
    "review.load_error": "The private plan is unavailable or its integrity check failed. Analyze the project again.",
})
ZH.update({
    "Reading": "读取并计算哈希", "Extracting": "解压已验证的归档",
    "PLANNED": "计划完成，请先检查发布内容", "result.PLANNED": "计划完成，请先检查发布内容",
    "storage.available_space": "可用磁盘空间",
    "storage.help": "最多保留 20 份私有审计（合计 64 MiB）和 100 条摘要。当前暂存按可用磁盘空间预检。清理前请导出需要的证据；此处不会删除公开发布包。",
    "review.analyze": "先分析", "review.title": "检查发布内容",
    "review.help": "逐项检查文件决定。选择文件、填写理由并保存规则，供自己、其他人或 AI 重复使用。秘密、依赖及许可检查仍生效，不会删除原文件。候选包不表示已经运行验证。",
    "review.path": "文件", "review.state": "决定", "review.reason": "检查理由", "review.size": "字节",
    "review.include": "包含", "review.exclude": "排除", "review.review": "待检查",
    "review.save": "保存规则…", "review.saved": "规则已保存并选中。再次分析后生效；决定绑定文件哈希，文件改变后需要重新检查。",
    "review.rejected": "请填写理由并选择普通文件。秘密、私有状态、许可不明或解析安全问题需要修正，不能直接批准包含。",
    "review.save_error": "请选择项目目录之外的新规则文件名；不会覆盖已有文件。",
    "review.load_error": "私有计划无法读取或完整性检查失败，请重新分析。",
})

EN["Copying bytes"] = "Copying file contents"
ZH["Copying bytes"] = "复制文件内容"
EN.update({
    'review.pending': 'Pending',
    'action.space': 'There is insufficient free disk space for staging and verification. Choose a disk with enough space; no incomplete package is approved.',
    'action.stale': 'The reviewed file changed or disappeared. Compare the plans and renew its decision after checking the new content.',
    'action.review': 'Review whether this file is a required input or generated output. Save a decision and reason, then analyze again.',
    'action.parser': 'This code or structured document exceeds the complete-parser bound. It was not approved from a prefix; split the document or choose a coherent component.',
    'action.agent': 'Keep only shareable agent settings. Correct private credentials in source; include cannot approve them.',
})
ZH.update({
    'review.pending': '待保存',
    'action.space': '可用磁盘空间不足以暂存和校验，请选择空间足够的磁盘。不会批准不完整的发布包。',
    'action.stale': '已审阅文件发生变化或消失，请比较计划，检查新内容后更新决定。',
    'action.review': '请判断该文件是必需输入还是生成输出，保存决定和理由，再次分析。',
    'action.parser': '此代码或结构化文档超出完整解析边界，没有仅凭前缀批准。请拆分文档或选择功能完整的组件。',
    'action.agent': '仅保留可共享的智能体配置。请在源码中修正私有凭据，包含规则不能批准凭据。',
})
