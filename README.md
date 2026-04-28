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

## 运行方式

```bash
pip install PySide6 openpyxl
python main.py
```

## 依赖安装

- Python 3.11+
- PySide6
- openpyxl

安装命令：

```bash
pip install PySide6 openpyxl
```

## 当前版本说明

当前版本为 Phase 3，在原有 UI 原型和 FakeCMW500 测试闭环基础上增加了结果汇总和 Excel 导出：

- `MainWindow(QMainWindow)` 作为主窗口。
- `LeftPanel`、`CenterPanel`、`RightPanel` 通过 `QSplitter(Qt.Horizontal)` 组成三栏布局。
- `RightPanel.append_log(level, message)` 统一接收日志。
- `core/test_plan.py` 根据当前 LTE UI 配置生成测试计划。
- `core/test_worker.py` 使用 `QThread + QObject` 后台执行测试，所有 UI 更新通过 Qt Signal 回主线程。
- `core/fake_cmw500.py` 根据接收电平模拟 BLER，`core/result_judge.py` 根据 BLER 门限判定 PASS/FAIL。
- `core/result_summary.py` 按制式、Band、信道、频点类型、测试模式分组计算灵敏度点。
- `reports/excel_exporter.py` 使用 openpyxl 导出 RawResults 和 Summary 两个 Sheet。

## 后续计划

- 接入真实 CMW500 通信流程。
- 增加 pyvisa、串口、adb 等实际控制模块。
- 实现配置文件解析与参数校验。
- 增加真实测试流程、异常恢复、结果导出与报告生成。
- 引入数据持久化和更完整的测试记录管理。

## 本阶段不包含

- 真实 CMW500 通信
- 真实 pyvisa
- 真实 adb 命令
- 真实 Excel 解析
- 真实串口通信
- 真实测试流程和真实仪表测量
- 数据库存储
- Excel 导出
