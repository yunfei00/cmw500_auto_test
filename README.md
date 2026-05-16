# cmw500_auto_test

CMW500 手机灵敏度自动化测试工具 UI 原型。

## 功能说明

- 三栏桌面界面：左侧操作与配置区，中间实时测试数据表格区，右侧实时日志区。
- LTE 配置界面包含仪表参数、测试信道选择、Band1 到 Band66 多选配置。
- WiFi、WCDMA、GSM 已搭建基础占位配置结构。
- 支持配置文件加载、手机设置、测试场景选择、测试控制、常用 ADB 操作等 UI 入口。
- 支持 LTE 假仪表自动测试流程：生成测试计划、后台线程执行、实时写入表格/摘要/日志。
- 支持测试暂停、继续、停止，测试结束后自动恢复按钮状态。
- 支持 LTE 测试结果汇总、灵敏度点计算，以及 RawResults/Summary 双 Sheet Excel 导出。
- 支持加载 LTE 信道配置 Excel，并优先使用 Excel 中的 Band/频点/信道映射生成测试计划。
- 支持基础 ADB 手机控制：刷新设备、安装 App、重启、停止/启动 App、清除数据、截图。
- 支持加载串口配置文件，格式为 YAML 或 JSON。
- 支持仪表模式切换：Fake CMW500 与 Real CMW500 TCP Socket/SCPI 连接。
- 支持 CMW500 LTE SCPI 命令模板配置，让 RealCMW500 从 YAML/JSON 模板执行 LTE setup、RX Level 设置和 BLER 查询。
- 支持 LTE 测试流程状态机：小区配置、Cell ON、等待 UE Attach、测量、Cell OFF、Cleanup。

## 运行方式

```bash
pip install PySide6 openpyxl PyYAML
python main.py
```

## 依赖安装

- Python 3.11+
- PySide6
- openpyxl
- PyYAML
- Android Platform Tools（用于 adb 操作）

安装命令：

```bash
pip install PySide6 openpyxl PyYAML
```

ADB 检查：

```bash
adb devices
```

如果命令不可用，请安装 Android Platform Tools，并将其目录加入 PATH。

## 当前版本说明

当前版本为 Phase 8，在原有 UI 原型、FakeCMW500 测试闭环、信道配置、结果导出、手机控制和 CMW500 Socket/SCPI 通信层基础上增加了 LTE 测试流程状态机：

- `MainWindow(QMainWindow)` 作为主窗口。
- `LeftPanel`、`CenterPanel`、`RightPanel` 通过 `QSplitter(Qt.Horizontal)` 组成三栏布局。
- `RightPanel.append_log(level, message)` 统一接收日志。
- `core/test_plan.py` 根据当前 LTE UI 配置生成测试计划。
- `core/test_worker.py` 使用 `QThread + QObject` 后台执行测试，所有 UI 更新通过 Qt Signal 回主线程。
- `core/fake_cmw500.py` 根据接收电平模拟 BLER，`core/result_judge.py` 根据 BLER 门限判定 PASS/FAIL。
- `core/result_summary.py` 按制式、Band、信道、频点类型、测试模式分组计算灵敏度点。
- `reports/excel_exporter.py` 使用 openpyxl 导出 RawResults 和 Summary 两个 Sheet。
- `core/channel_config.py` 解析信道配置 Excel，`scripts/create_sample_channel_config.py` 可生成示例配置文件。
- `devices/adb_client.py` 封装 adb 命令调用，所有操作带超时和异常处理。
- `core/serial_config.py` 解析 YAML/JSON 串口配置文件。
- `devices/scpi_socket_client.py` 使用 Python 标准库 socket 实现 SCPI TCP 客户端，默认端口 `5025`。
- `devices/cmw500_controller.py` 提供 `RealCMW500` 控制器，支持 TCP 连接、断开、`*IDN?` 查询、`*RST` 和 `SYST:PRES` 基础命令。
- `core/fake_cmw500.py` 保持默认可用回退模式，并兼容统一仪表接口。
- `core/scpi_template.py` 解析 CMW500 LTE SCPI 命令模板，并支持模板变量渲染和测量返回值解析。
- `core/test_states.py` 定义 LTE 测试流程状态，`core/test_worker.py` 按状态机推进测试。

## 仪表连接说明

默认仪表模式为 `Fake`。点击“连接仪表”后会创建并连接 Fake CMW500，点击“查询IDN”返回：

```text
Fake CMW500 Simulator
```

`Real CMW500` 模式用于连接真实 CMW500 的 SCPI Socket 服务：

- 默认 IP：`192.168.1.100`
- 默认端口：`5025`
- 默认超时：`5.0 s`

当前 Real CMW500 已支持：

- TCP Socket 连接/断开
- `*IDN?` 查询
- `*RST` reset 基础命令
- `SYST:PRES` preset 基础命令

当前 Real CMW500 仍需按实际仪表继续校准：

- LTE 小区真实配置 SCPI
- RX Level 真实设置 SCPI
- BLER 真实读取 SCPI

加载 CMW500 命令模板后，Real 模式会按模板执行 LTE setup、Cell ON、等待 UE Attach、RX Level 设置、BLER 查询、Cell OFF 和 Cleanup；未加载 `wait_attach` 时不会假装 Attach 成功。Fake 模式会自动 Attach 成功，作为默认可用回退。

## SCPI 命令模板

Phase 8 实现的是 CMW500 LTE SCPI 命令模板和流程状态机执行框架。基础示例模板位于：

```text
config/cmw500_lte_scpi_template.example.yaml
```

Phase 8 流程示例模板位于：

```text
config/cmw500_lte_scpi_template.phase8.example.yaml
```

示例内容：

```yaml
instrument:
  name: CMW500
  transport: socket
  default_port: 5025

lte:
  setup:
    - "INST LTE"
    - "CONFigure:LTE:SIGN:BAND {band_number}"
    - "CONFigure:LTE:SIGN:RFSettings:CHANnel:DL {channel}"
  cell_on:
    - "CALL:LTE:SIGN:PSWitched:STATe ON"
  wait_attach:
    query: "FETCh:LTE:SIGN:PSWitched:STATe?"
    parser: "contains"
    expected: "ATT"
    interval_sec: 1.0
    timeout_sec: 30.0
    fallback_success: false
  before_measure:
    - "SYST:ERR?"
  set_rx_level:
    - "CONFigure:LTE:SIGN:DL:RSEPre:LEVel {rx_level}"
  measure_bler:
    query: "FETCh:LTE:SIGN:BLER?"
    parser: "first_float"
    fallback_simulation: true
  after_measure:
    - "SYST:ERR?"
  cell_off:
    - "CALL:LTE:SIGN:PSWitched:STATe OFF"
  cleanup:
    - "SYST:ERR?"
```

支持变量：

- `{mode}`
- `{band}`
- `{band_number}`
- `{channel}`
- `{channel_type}`
- `{rx_level}`
- `{packet_count}`
- `{test_mode}`

测量结果 parser：

- `first_float`：提取返回字符串中的第一个浮点数
- `second_float`：提取返回字符串中的第二个浮点数
- `csv_index:N`：按逗号分隔后取第 N 个字段，N 从 0 开始

`wait_attach` parser：

- `contains`：返回字符串包含 `expected` 即成功
- `equals`：返回字符串去除首尾空白后等于 `expected` 即成功
- `first_float_ge:X`：返回字符串中的第一个浮点数大于等于 X 即成功
- `first_float_le:X`：返回字符串中的第一个浮点数小于等于 X 即成功
- `regex`：把 `expected` 当作正则表达式，匹配成功即成功

LTE 状态机状态：

- `IDLE`
- `PREPARING`
- `CELL_CONFIGURING`
- `CELL_ON`
- `WAITING_ATTACH`
- `ATTACHED`
- `MEASURING`
- `PAUSED`
- `STOPPING`
- `CLEANUP`
- `COMPLETED`
- `FAILED`

流程顺序：

```text
PREPARING -> CELL_CONFIGURING -> CELL_ON -> WAITING_ATTACH -> ATTACHED -> MEASURING -> CLEANUP -> COMPLETED
```

测试计划按 Band/Channel 重建小区，同一个 Band/Channel 下只扫不同 RX Level；切换 Band/Channel 时重新执行 setup、cell_on 和 wait_attach。`fallback_simulation` 为 `true` 时，如果真实 BLER 查询或解析失败，RealCMW500 会回退模拟 BLER，并在日志中输出 WARNING。示例命令只用于说明模板格式，不保证适配所有 CMW500；真实 LTE attach、信令建立、数据业务、PTM/DAU 或 BLER 读取流程需要根据仪表选件、应用模式和官方手册继续补充。用户可以直接修改 YAML/JSON 模板，而不是修改 Python 代码。

生成示例信道配置：

```bash
python scripts/create_sample_channel_config.py
```

串口配置 YAML 示例：

```yaml
serial_ports:
  - name: phone_debug
    port: COM5
    baudrate: 115200
    role: phone
  - name: relay_board
    port: COM8
    baudrate: 9600
    role: relay
```

串口配置 JSON 示例：

```json
{
  "serial_ports": [
    {
      "name": "phone_debug",
      "port": "COM5",
      "baudrate": 115200,
      "role": "phone"
    }
  ]
}
```

## 后续计划

- 完善真实 CMW500 LTE 测试控制流程。
- 增加 pyvisa、串口通信等实际控制模块。
- 补充 CMW500 LTE 小区配置、RX Level 设置和 BLER 读取 SCPI 命令。
- 实现配置文件参数校验。
- 增加真实测试流程、异常恢复、结果导出与报告生成。
- 引入数据持久化和更完整的测试记录管理。

## 本阶段不包含

- 真实 CMW500 LTE 小区配置和 BLER 测量
- 真实 pyvisa
- 真实串口通信
- 真实测试流程和真实仪表测量
- 数据库存储

## 自动构建与发布

push 到 `main` 后，GitHub Actions 会自动执行基础检查并构建 Windows 绿色版压缩包。

推送 `v*` 格式的 tag 后，会自动创建 GitHub Release，并上传对应的 Windows x64 绿色版构建产物。

打 tag 示例：

```bash
git tag v0.1.0
git push origin v0.1.0
```

构建产物名称示例：

```text
CMW500AutoTest-v0.1.0-windows-x64.zip
```

本地构建命令：

```bash
pip install -r requirements.txt
pip install -r requirements-build.txt
python scripts/build_windows.py
python scripts/package_release.py --version dev
```
