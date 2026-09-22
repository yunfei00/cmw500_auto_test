# WCDMA 真机验证手册（CMW500）

> 适用分支：`feat/wcdma-test`
>
> 目标：先验证基础连接和单点 BER，再验证灵敏度搜索，最后验证固定信道 / 遍历 / 多场景。任何一步失败，都先停止在当前步骤，不要继续扩大测试范围。

## 0. 验证原则

1. 第一次真机验证只选 **1 个 Band + 1 个固定信道 + 默认场景**。
2. 优先使用你现场确认可工作的 Band/Channel；不要第一次就全 Band 遍历。
3. BER 按 CMW500 原始返回值使用：例如返回 `0.01` 就按 `0.01`，不乘 100，也不除 100。
4. 每一步保存：软件日志、CMW500 屏幕状态、关键 SCPI 返回值。
5. 出现无法解释的状态、掉线、BER 无效或仪表报错时停止测试并记录，不要连续重试掩盖问题。

---

## 1. 准备环境

### 1.1 代码

确认使用：

```bash
git fetch origin
git switch feat/wcdma-test
git pull origin feat/wcdma-test
```

记录当前提交：

```bash
git rev-parse HEAD
```

### 1.2 硬件

- CMW500 已开机且 WCDMA Signaling 可用。
- 手机与 CMW500 RF 线缆连接正确。
- USB/ADB 可识别手机（需要场景切换时）。
- 确认实际 RF 口对应软件 COM1/COM2/COM3/COM4。
- 确认输入/输出线损；当前默认值 35 dB，仅在现场确实如此时使用。

### 1.3 软件启动后检查

进入 **WCDMA** 页签，先检查：

- 线损
- COM 口
- 灵敏度初始值
- 灵敏度连接值
- 最大步长
- 最小步长
- 测试包个数
- 快速浏览包个数
- BER 门限（默认 0.1，原始值）
- 信道模式
- Band / Channel / BW

先测试“保存配置”：修改一个无风险配置 → 保存 → 关闭软件 → 重新打开，确认值恢复；再点“恢复默认”，确认默认配置恢复。关闭时停留在 WCDMA 页，再启动一次，确认仍默认进入 WCDMA。

---

## 2. 第一阶段：只验证 CMW500 通信

这一阶段**不要直接跑完整灵敏度测试**。

1. 软件选择 Real CMW500。
2. 填写实际 VISA/SOCKET 地址。
3. 执行仪表连接/身份验证。
4. 确认 IDN 返回正确，软件没有超时或 SCPI Error。

### 通过条件

- CMW500 能连接。
- IDN 正常。
- 软件日志无通信异常。

### 反馈记录

```text
CMW500连接：成功/失败
连接方式：VISA/SOCKET
IDN：
异常信息：
```

---

## 3. 第二阶段：验证 WCDMA 基础初始化

先只选择一个确定可用的 Band，例如现场最方便验证的 Band。

需要重点观察程序依次完成：

1. RF Route / COM 设置
2. Input Loss
3. Output Loss
4. Measurement Repetition = SING
5. UE Termination = TEST
6. Test Mode Type = RMC
7. RMC Test Mode = MODE1
8. RMC Data = PRBS9
9. UL TPC = ALL1
10. Cell ON

### 重点

Band 设置命令必须以 CMW500 实际接受为准。如果出现 Undefined header、Data out of range、Execution error 等仪表错误，立即记录 Band、发送命令和错误，不继续全 Band 测试。

### 反馈记录

```text
测试Band：
COM口：
Cell ON：成功/失败
手机是否驻网：是/否
CMW500错误：
软件日志最后20行：
```

---

## 4. 第三阶段：验证单 Band + 单 Channel 连接

使用 **固定信道** 模式，只勾一个 Band，并把固定信道临时改成一个 Channel。

例如实际使用 Band 1 时，可以只保留：

```text
10562
```

BW 使用现场需要的值（当前默认 5 MHz）。场景只选“默认”或当前最基础、不会增加额外负载的场景。

启动后重点观察：

1. Band 设置成功。
2. Channel 设置成功。
3. Cell ON。
4. 手机注册。
5. CS 状态查询。
6. 必要时执行 CONNECT。
7. 最终 CS 是否进入 `CEST`。
8. PS 是否为预期的 `ATT` / `ON`。

如果停在 `REG`，记录 CONNECT 前后的状态。

### 反馈记录

```text
Band：
Channel：
CS第一次状态：
执行CONNECT：是/否
CONNECT后CS状态：
PS状态：
最终是否连接成功：
耗时：
异常：
```

---

## 5. 第四阶段：验证单点 BER

只有第三阶段连接稳定后才进行。

确认程序单次 BER 流程：

1. 再次检查连接状态。
2. 设置当前接收功率。
3. ABORT BER。
4. Repetition = SING。
5. 设置 TBLocks。
6. Stop Condition = NONE。
7. INIT BER。
8. 查询 BER State，等待 RDY。
9. RDY 后 Fetch BER。

当前设计最多轮询约 40 秒；没有 RDY 时应超时，而不是读取旧 BER。

记录至少 3 个不同电平的 BER，例如强、中、弱各一个点。具体电平以现场安全且可工作的范围为准。

**不要换算 BER。** CMW500 返回 0.01，记录就是 0.01。

### 反馈表

| Power | BER State | BER Status | BER Raw | 连接状态 | 备注 |
|---:|---|---|---:|---|---|
| | | | | | |
| | | | | | |
| | | | | | |

如果出现 `INV`、status=3、status=4，把完整原始返回字符串保存下来。

---

## 6. 第五阶段：验证灵敏度自动搜索

仍然只使用：

**1 Band + 1 Channel + 1 Scene**。

重点检查：

- 从灵敏度初始值开始。
- 快速搜索使用“快速浏览包个数”。
- BER 接近/超过门限后使用正式“测试包个数”确认。
- BER 判断使用原始值，门限默认 0.1。
- 进入 0.08～0.12 确认窗口时行为符合设计。
- 需要向上恢复时使用最小步长。
- 最终输出灵敏度、电平、BER、Band、Channel、Scene。

建议把整个功率变化序列记录下来，例如：

```text
-70.1 -> -70.6 -> -71.1 -> ... -> 最终灵敏度
```

同时记录每一步 BER，方便我们判断自适应步长逻辑是否正确。

---

## 7. 第六阶段：验证固定信道

单点通过后，把固定信道恢复为该 Band 默认值，例如 Band 1：

```text
10562 10700 10838
```

确认实际执行顺序为：

```text
Band
 ├─ Channel 1
 ├─ Channel 2
 └─ Channel 3
```

每个 Channel 都必须独立完成连接检查和灵敏度测试。

---

## 8. 第七阶段：验证遍历模式

切换到 **遍历**。

第一次不要使用很大的范围，建议临时设置一个很小的 Begin / End / Step，确认生成顺序和结束条件正确。

确认无误后，再恢复保存的正式 Begin / End / Step。

特别检查：当 Step 不能刚好落在 End 时，当前程序会把 **End 额外作为最后一个测试信道**。现场确认这是否符合你的旧机器人测试规则。

---

## 9. 第八阶段：验证 Scene 遍历

信道逻辑确认后，再打开多个 Scene。

需要验证的层级是：

```text
Band
  └─ Channel
       ├─ Scene 1
       ├─ Scene 2
       ├─ Scene 3
       └─ ...
```

也就是说：**同一个 Channel 下把所有 Scene 跑完，再进入下一个 Channel。**

检查每次 Scene 切换后：

- Android 场景确实生效。
- CMW500 连接状态重新检查。
- 掉线能够恢复。
- BER 测试使用当前 Scene。
- 结果中的 Scene 名称正确。

---

## 10. 第九阶段：多 Band 验证

最后才勾选多个 Band。

先两个 Band，再逐步扩大到全部需要测试的 Band。逐 Band 检查 CMW500 是否接受 Band 设置命令，尤其是 Band 2/4/5/6/8/19。

如果某个 Band 设置失败，只记录该 Band，不要因此否定已经验证成功的其他 Band。

---

## 11. 最终验收项目

完成真机验证后，应确认：

- [ ] WCDMA 页面记忆正常
- [ ] 配置保存/加载正常
- [ ] 恢复默认正常
- [ ] 固定信道模式正常
- [ ] 遍历模式正常
- [ ] BW 修改/保存正常
- [ ] RF Route 正常
- [ ] Cell ON/OFF 正常
- [ ] Band 设置正常
- [ ] Channel 设置正常
- [ ] CS/PS 状态判断正常
- [ ] CONNECT/重连正常
- [ ] BER 单点正常
- [ ] BER 原始值没有百分比换算
- [ ] 灵敏度搜索正常
- [ ] Channel → Scene 遍历顺序正确
- [ ] 多 Band 正常
- [ ] 停止测试后 Cell/RF 安全清理正常
- [ ] LTE 原有功能未受影响

---

## 12. 给我反馈时直接复制这个模板

```text
【WCDMA真机验证】
当前commit：
CMW500型号/版本（能看到就填）：
连接方式：VISA / SOCKET
COM：

阶段2 基础初始化：通过 / 失败
阶段3 单信道连接：通过 / 失败
阶段4 单点BER：通过 / 失败
阶段5 灵敏度搜索：通过 / 失败
阶段6 固定信道：通过 / 失败
阶段7 遍历：通过 / 失败
阶段8 Scene：通过 / 失败
阶段9 多Band：通过 / 失败

Band：
Channel：
Power：
CS状态：
PS状态：
BER原始返回：
最终灵敏度：

失败步骤：
软件错误：
CMW500错误：
软件日志：
其他现象：
```

## 推荐实际执行顺序

今天第一次上真机，只做到 **阶段 1 → 5**。确认单 Band、单 Channel、单 Scene 的连接和 BER 灵敏度搜索完全正确后，再进行固定信道、遍历、Scene 和多 Band。这样一旦出现问题，可以快速判断属于仪表命令、连接状态机还是搜索算法，而不会把多个问题混在一起。
