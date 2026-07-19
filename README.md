# CMW500 Auto Test

面向 Rohde & Schwarz CMW500 的 LTE 手机灵敏度自动化测试桌面工具。当前版本为 `0.2.0-dev`，已完成 P0 软件闭环，定位为商业发布候选版；在完成目标仪表实机校准、端到端验收和代码签名前，不应作为正式量产发布。

## 已实现能力

- LTE 灵敏度粗扫、首个确认失败点后的细扫，以及失败/异常重试。
- 全局线损与信道配置线损叠加，分别记录 DUT 目标电平和仪表下发电平。
- Fake CMW500 模拟流程；所有模拟结果均带 `SIMULATION` 标识和红色水印。
- Real CMW500 支持 VISA 与 SCPI Socket，连接时强制校验 R&S CMW 身份。
- 真实模式严格 fail-closed：通信、超时、解析和 BLER 越界错误不会回退为模拟值。
- 类型化 SCPI 步骤：`write`、`query`、`query_and_assert`；查询响应会被消费并写入结构化 trace。
- LTE 小区配置、Cell ON、Attach、BLER、Cell OFF、Cleanup 状态机。
- 暂停、继续、协作取消、I/O 中断、断线后安全重连清理；清理未确认时锁存 `FAILED_UNSAFE`，在操作员明确确认人工 RF/Cell OFF 前禁止新测试和退出。
- 每次测试使用独立 Run ID，并记录仪表 IDN、连接参数、配置快照、配置哈希、软件版本、构建 commit、校准信息和命令 trace。
- 自动保存 Excel 报告，包含 `RawResults`、`Summary`、`RunMetadata`、`SCPITrace` 四个工作表。
- `STOPPED`、`FAILED`、`FAILED_UNSAFE` 报告带不完整/不安全水印，不能被误认为正式 PASS。
- 基础 ADB 能力：设备刷新、APK 安装、重启、App 启停、清数据和截图；耗时操作在后台执行。
- 用户配置、日志、截图和自动报告保存在 `%LOCALAPPDATA%\cmw500_auto_test`，不会写入程序安装目录。

当前只开放 LTE。WiFi、WCDMA、GSM 页签已禁用，尚未形成测试闭环。

## 开发环境运行

要求 Python 3.11+：

```powershell
python -m pip install --requirement requirements.txt
python main.py
```

VISA 连接优先使用系统已安装的 NI/Keysight/R&S VISA；系统后端不可用时会回退到随依赖安装的 `pyvisa-py`。Socket 模式默认使用 TCP 5025。

ADB 功能需要安装 Android Platform Tools，并确保 `adb` 在 `PATH` 中：

```powershell
adb devices
```

## 正式测试操作要求

1. 选择 `Real CMW500`，填写实际 VISA Resource 或 Socket 地址并连接。
2. 确认 `*IDN?` 被识别为受支持的 R&S CMW。
3. 加载并审核目标仪表适用的 LTE SCPI 模板。
4. 加载 LTE 信道/线损配置，确认 Band、带宽、信道和线损来源。
5. 填写测试人员、DUT 标识、仪表校准标识及有效期；过期校准会阻止启动。
6. 核对扫描起止电平、粗细步长、包数、BLER 门限、稳定时间和重试次数。
7. 完成测试后检查终态。只有 `COMPLETED` 且数据来源为 `REAL` 的报告才具备进入正式评审的前提。

随仓库提供的推荐模板位于：

```text
config/cmw500_lte_scpi_template.cmw500_recommended.yaml
```

模板是可审计的基线，不代表已适配所有 CMW500 软件版本、选件和 LTE 应用模式。正式使用前必须依据目标仪表手册与实机返回值校准，并保存验证证据。

## SCPI 模板格式

命令步骤支持：

```yaml
- type: write
  command: "INST LTE"
- type: query
  command: "CONFigure:LTE:SIGN:RFSettings:FREQuency:DL?"
- type: query_and_assert
  command: "SYST:ERR?"
  parser: regex
  expected: '^\s*0(?:,|$)'
```

支持的上下文变量包括：

- `{mode}`、`{band}`、`{band_number}`、`{channel}`、`{channel_type}`
- `{test_mode}`、`{rx_level}`、`{packet_count}`
- `{bw}`、`{bandwidth}`、`{cable_loss}`

BLER parser 支持 `first_float`、`second_float`、`csv_index:N`。Attach/状态 parser 支持 `equals`、`equals_ci`、`contains`、`regex`、`first_float_ge:X`、`first_float_le:X`。

真实测试启动前会校验安全关键段、变量、parser、超时和 fallback 标志。`fallback_simulation=true` 与 `fallback_success=true` 在正式预检中会被拒绝。

## 配置与报告

内置 LTE 信道基线位于 `configs/lte_channel_config.xlsx`。首次运行会复制到：

```text
%LOCALAPPDATA%\cmw500_auto_test\configs\lte_channel_config.xlsx
```

每次运行结束后会自动写入：

```text
%LOCALAPPDATA%\cmw500_auto_test\runs\<run_id>.xlsx
```

报告保留所有重试原始记录，并对外部字符串做 Excel 公式转义。模拟、停止、失败和安全清理未确认的报告均有醒目水印。

## 测试

```powershell
python -m pytest -q --basetemp=.pytest-tmp
```

测试覆盖扫描/重试/线损、状态终态、安全停止、SCPI 模板与控制器、Socket/VISA 异常、汇总、Excel 报告以及构建/归档校验。

## Windows 构建与发布

```powershell
python -m pip install --requirement requirements.txt
python -m pip install --requirement requirements-build.txt
python scripts/build_windows.py
python scripts/package_release.py --version dev
```

构建会检查关键资源、运行时版本、构建 commit、PyVISA 后端、归档内容和 SHA-256 清单。开发构建允许未签名，但会明确告警；正式版本构建和归档都会独立拒绝未通过 Authenticode 验证的 EXE。

正式 tag 必须使用严格的 `vX.Y.Z`：

```powershell
git tag v0.2.0
git push origin v0.2.0
```

GitHub Actions 对 tag 构建强制 Authenticode 签名并验证。需要配置：

- `CMW_SIGNTOOL_PATH`：`signtool.exe` 路径或命令名。
- `CMW_SIGN_CERT_SHA1`：证书存储中的签名证书 SHA1（GitHub Secret）。
- `CMW_SIGN_TIMESTAMP_URL`：RFC 3161 时间戳服务地址。

缺少签名配置时，tag 发布会 fail-closed，不会创建 GitHub Release。

## 商业发布前仍需完成的外部门禁

- 在目标 CMW500 型号、软件版本、选件和 LTE 应用模式上完成 SCPI 校准。
- 使用真实 DUT 完成代表性 Band/信道/电平的端到端验收并归档报告、日志和 trace。
- 确认仪表校准证书有效，核对线损文件来源和复测周期。
- 配置并验证组织代码签名证书、时间戳服务和发布权限。
- 完成第三方依赖许可证、隐私说明、用户手册及支持流程的法务/运营评审。

详细进度与下一步见 `PROJECT_STATUS.md`。
