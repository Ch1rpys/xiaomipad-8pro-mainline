# piano 系统睡眠验收

`tools/piano-suspend-check.py` 在平板上以 root 运行，适用于 RAM 会话及持久安装。
当前只有离线解析和清理检查通过，尚未在 piano22 或其他真机启动中执行。
它验证 `freeze` / s2idle 的实际睡眠与外设恢复；结果不证明深度睡眠、待机功耗，
也不代替真实触控、打字、录音或相机出图验收。

## 运行

将脚本放到平板，例如 `/var/tmp/piano-suspend-check.py`。以下命令在已连接的 SSH
会话内执行；使用独立 systemd 服务，让 Wi-Fi/USB 在睡眠期间断开时测试仍继续。
`SERIAL` 必须匹配本次启动的 `androidboot.serialno`；可加 `--kernel RELEASE` 锁定内核。

```sh
sudo systemd-run --unit=piano-suspend-auto --collect --property=Type=exec \
  /usr/bin/python3 /var/tmp/piano-suspend-check.py \
  --serial SERIAL --output /var/tmp/piano-suspend-auto
```

默认 3 轮，每轮 RTC 30 秒。用 `--rounds N --seconds N` 修改。输出目录必须不存在。
RAM 会话须预留足够剩余时间：睡眠、恢复等待、网关探测和日志采集都会计入会话期限；
本工具不修改已有的会话退出定时器。

物理唤醒每次只验证一种来源；进入睡眠后按键或开盖。下面测试键盘，其他两种分别用
`--expect-wake pwrkey`、`--expect-wake lid`：

```sh
sudo systemd-run --unit=piano-suspend-physical --collect --property=Type=exec \
  /usr/bin/python3 /var/tmp/piano-suspend-check.py \
  --serial SERIAL --output /var/tmp/piano-suspend-keyboard \
  --physical --expect-wake keyboard --rounds 1 --safety-seconds 180
```

物理模式只设置 180 秒安全 RTC，不设置 30 秒闹钟；打印“请按电源键/按键盘键/开盖”。
要求实测睡眠时间大于采样误差、IRQ 名字符合所选来源。
RTC 唤醒报告 `NO_PHYSICAL_WAKE`，退出非零；不会把兜底恢复记成物理唤醒成功。
物理模式的 180 秒是上限，提前物理唤醒不受自动模式 80% 时长要求限制。

通过 `sudo journalctl -fu piano-suspend-auto.service` 查看进度，结束后检查输出目录
`result.json`；物理测试对应 `piano-suspend-physical.service`。
要中止可用 `sudo systemctl kill --kill-whom=main --signal=SIGTERM UNIT.service`。
睡眠请求进行中收到信号会保留已设的安全闹钟，等本次请求返回或截止后清理，不再启动下一轮。

## 判据与记录

需要已经运行的 GNOME/Mutter 图形会话、piano-thp、已吸附的键盘、已供电的蓝牙控制器、
声卡、可读电量计与 MCA 充电器。摄像头仅对睡前存在的 video 节点检查。
Wi-Fi 睡前已关联时要求睡前和恢复后均能 ping 通其默认网关；未关联时明确记录并跳过此项。
依赖系统已有的 `systemctl`、`systemd-analyze`、`journalctl`、`busctl`、`loginctl`、
`rtcwake`、`iw`、`ip`、`ping`、`runuser` 及 Python 标准库，不自动安装依赖。
内核须提供 suspend_stats、pm_wakeup_irq、已挂载的 tracefs 和 `i2c:i2c_result` 事件。
RTC 默认 `rtc0`（可选 `--rtc rtcN`），已有其他闹钟时拒绝开始。

每轮保存前态、RTC 命令、双时钟、恢复采样、所有检查布尔值及原始命令输出：

| 项目 | PASS 条件 |
| --- | --- |
| 睡眠 | boot_id 相同；success 恰好 +1；fail 与各 failed_* 不变；last_failed_dev 为空；自动模式 BOOTTIME 增量减 MONOTONIC 增量的保守下界 ≥ 闹钟时长 80% |
| 唤醒源 | 保存 pm_wakeup_irq 和 /proc/interrupts 对应原文、IRQ 名称；物理模式还校验来源，未知名称不通过 |
| 触控、网络 | THP MainPID 与进程 starttime 不变、服务 active、触控 event 节点在；睡前已连的 Wi-Fi 恢复关联且网关 ping 成功；原有蓝牙控制器仍在且 Powered |
| 声卡、电源 | 原有声卡仍在；各原有 Battery 容量为 0–100；xiaomi-mca-usb 的 online 与 usb_type 可读，有 status 时亦须可读 |
| 键盘 | nanosic_hinge 报告 attached、桥接驱动与 keyboard input 在；按 sysfs 发现 I²C 总线，独立 trace 实例有传输、无负值/短传输、无丢记录 |
| 摄像头、显示 | 原有 video 字符节点仍在；当前图形用户的 Mutter PowerSaveMode 设为 0 并读回，DSI-1 enabled 且 dpms On |
| 内核日志 | 从轮前游标到恢复检查完成，没有新 WARNING、Call trace、timeout、failed to resume、SMMU/IOMMU fault、ath12k/qca/iris/msm/I²C 错误或其他 error 级消息；原文保存在 JSON；游标丢失或日志缺口不能通过 |

`--resume-timeout` 默认 30 秒，是 RTC 时长之后等待 success 增加的余量；
`--recovery-timeout` 默认 30 秒，用于 Wi-Fi 关联和显示状态的有界观察，不重发睡眠命令。
未增加 success 也会继续记录恢复读数并判失败；命令错误、读取失败或 D 状态导致无法采集时保留已有证据。
发现 D 状态任务立即记录进程/线程及阶段，停止后续轮次和外设探测；只尝试资源清理。
冻结/恢复过渡期间不扫描 D 状态，以免把 freezer 的正常等待误判成驱动死锁，返回后立即检查。

`result.json` 是总报告，`round-NN.json` 是逐轮记录，`commands.jsonl` 和编号日志保留命令及输出。
只有全部请求轮次通过且清理成功才退出 0，首个未通过的轮次即结束测试。
记录含设备序列号、网络地址等私有信息，目录权限 0700，文件权限 0600，不应直接公开。

## 资源与限制

只创建 `/run/systemd/sleep.conf.d/90-piano-suspend-check.conf`，内容为
`[Sleep]`、`AllowSuspend=yes`、`SuspendState=freeze`，并检查合并后的配置。
产品 `/usr/lib/systemd/sleep.conf.d/50-piano-first-release.conf`、`/etc` 和 GNOME 设置均不修改。
经标准 `systemctl suspend` / logind 请求睡眠，不直接写 `/sys/power/state`。
独占本工具覆盖文件，不覆盖已有同名文件；`finally` 与 SIGINT/SIGTERM/SIGHUP 路径删除自己
创建的覆盖、清除 RTC 闹钟并销毁独立 trace 实例。不加载、卸载、重绑驱动或重启服务。

内核死锁、SIGKILL 和掉电无法由 Python 的 finally 保证恢复。RTC 与用户态超时也不能解除
D 状态等待；首次上机必须有人在场并具备强制恢复条件，不能据此工具解除无人值守限制。
若进程被强杀且系统仍可操作，须核对报告中的清理记录与 `/run` 覆盖是否残留，再由现场人员恢复。
IRQ 名字、RTC 唤醒、Mutter、trace 和外设恢复均需真机确认；工具通过不能单独关闭整机睡眠技术债。

## 离线检查

```sh
python3 -m py_compile tools/piano-suspend-check.py tools/test-piano-suspend-check.py
python3 tools/test-piano-suspend-check.py -v
```

9 项检查使用文本夹具、临时目录和发给测试进程自己的信号，覆盖计数差分、双时钟、IRQ、
日志游标与过滤、I²C 返回值、D 状态/input 解析及异常/信号清理，不访问真实 sysfs、RTC 或设备。
