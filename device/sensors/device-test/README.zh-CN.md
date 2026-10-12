# SSC 一次性检查 v3（7.2.6-piano8）

v2 真机已能发现 registry，但尚无默认 accel。完整 567 行日志定位到：可写目录仅覆盖内层
`registry/registry/`，外层的 `sns_reg_version`、`fstempfile`、`parsed_file_list.csv` 仍无法写入或缺失。
**v3 将整个 registry 父目录及其 registry/ 子目录映射到每轮 scratch**，并携带同机 persist
备份中已有的版本文件和解析清单（不是生成占位文件）。尚无 v3 piano 样本 PASS。

仍用原 HexagonRPC `598b591a` + 四项局部补丁；libssc `54dd13e3` 与 ssccli 二进制保持不变。
在已有 one-shot runner 内，只对 ssccli 的明确空 SUID 结果重查，每次空回复后间隔 1 秒、从第一次空回复起最多
30 秒；registry 超时、GLib 错误、其他退出码不重试。四类并发，daemon 始终保留。
每次请求/失败日志保存为 `<类型>.attempt-NN.log`，常规 `<类型>.log` 和 JSON 取最后一次，
避免早先的 `UNKNOWN` 初始化错误污染后来成功的样本。发现类型后允许完成约 5 秒采样。

registry 本来有 30 秒等待；为覆盖两阶段，客户端总限时 70 秒、daemon 75 秒（TERM 后 2 秒 KILL）。
结束回收全部自启进程，保留日志和副本；不重启 daemon/ADSP/设备，不安装服务、不改内核。

## 精确传输与运行

在主机工作区根目录执行，沿用已设置的开发者模式/root 登录。`PIANO_SERIAL` 为目标 piano 的
序列号。本地交付 README 已填本机值，公开仓文档不含它。不直接调用 scp/ssh；helper 内部仍用
SSH，并透传 stdin。tar 二进制流不要加 `-t`。

```sh
: "${PIANO_SERIAL:?先设置本机 piano 的序列号}"
set -o pipefail
tar -C out/ssc-device-test-20261012-3 -cf - . |
  python3 public/xiaomipad-8pro-mainline/tools/piano-devmode-ssh.py \
    --serial "$PIANO_SERIAL" root \
    'umask 077; mkdir -p /var/tmp/ssc-test/bundle-20261012-3; tar -xf - -C /var/tmp/ssc-test/bundle-20261012-3'

python3 public/xiaomipad-8pro-mainline/tools/piano-devmode-ssh.py \
  --serial "$PIANO_SERIAL" root \
  '/var/tmp/ssc-test/bundle-20261012-3/run.sh'
```

静置平板，观察窗口最长约 75 秒。脚本打印本轮 `SSC_OUTPUT` 与 `SSC_SCRATCH`，不要混入旧会话。
输出默认在 `/var/tmp/ssc-test/run-…/`，可写 registry 在
`/var/tmp/ssc-test/scratch/run-…/registry/`。若显式使用 `/run/` 下的输出目录，则 scratch
跟随该目录。包内 pristine 数据、主机 persist 备份和设备真实 persist 均不作为写目标。
不自动重启设备/ADSP、不停已有传感器服务；发现已有 hexagonrpcd/ssccli/iio-sensor-proxy 会拒绝运行。

```text
SSC_QRTR_400=[{"service": 400, ...}]
SSC_SCRATCH=/var/tmp/ssc-test/scratch/run-.../registry
SSC_SENSOR=accelerometer RESULT=PASS SAMPLES=...
SSC_REGISTRY_PRISTINE_UNCHANGED=YES
SSC_RESULT=PASS ...
SSC_SAMPLES=... SSC_ACCEL_G=9.8...
```

`SSC_ACCEL_G` 单位为 **m/s²**（不是 g 倍数），取加速度模长中位数；`result.json` 也记录首帧模长。
脚本明确打印静止粗判：至少 2 帧，模长中位数 7.8–11.8 m/s²，预期约 9.8 m/s²。
总 PASS 还要求 daemon 在客户端完成前存活、CLI 正常关闭，已宣告的其余请求类型有样本。
可选类型明确未宣告时单独 UNAVAILABLE，不谎称四类都通过。退出码 PASS=0、FAIL=1、UNAVAILABLE=2。

上游 CLI 无全量 `--list`；`sensors.json` 是 accel/gyro/ambient_light/proximity **四类默认 SUID**
的发现记录。各类型 JSON 保留样本、属性、计数与错误，原日志保留 QMI 文本。
向量已由 libssc 应用固件安装矩阵，无另加本机/参考设备坐标变换；CLI 不导出 DSP 时间戳或 accuracy。
上游 gyro 单位标签 `m/s` 原样保存在 `upstream_unit`，不据此声明角速度单位/校准通过。

## 这次修正与已知边界

v2 日志中，内层 `registry/registry/DIR` 成功写入 3 B，ODM JSON 能逐个读取；但外层
`sns_reg_version` 写打开被拒一次、`fstempfile` 被拒 **108 次**，`parsed_file_list.csv` 首次读取 ENOENT。
因此 v2 的 DIR 单点回放覆盖不足。v3 的 `-w` 和 pristine 布局都对应外层
`/mnt/vendor/persist/sensors/registry/`，里面真实保留 `registry/` 子目录。

外层新增文件与内层条目使用同一受限映射：真实 create/truncate/append/update/write/remove，
其他目录仍只读，软/硬链接和非普通文件写目标被拒绝，`..` 跨出外层 registry 不会获得写权限。
每轮从 pristine 复制为新 inode、目录 0700/文件 0600；前后 SHA、变更文件清单和完整副本保留。
`sns_reg_version`、`fstempfile`、`parsed_file_list.csv` 逐个通过 w/wb/w+、读回以及 108 次临时文件
重开的实际 handler 回放。v2 失败行没有记录 mode/flags，不能声称这些测试模式全部被真机观测；
v3 的失败日志新增 mode/flags，后续可精确裁决。

**硬件访问线索：**完整日志无 PD 的 `/dev`/sns_* 设备节点、QUP、I2C、SPI、GPIO、regulator 请求；
唯一 `/dev/` 字样来自 daemon 启动横幅的 FastRPC 节点。`sns_*.json` 是配置文件。
当前没有证据把这次失败转成 kernel/DTS 任务，因此未改内核。该文件服务日志不覆盖 DSP 内部总线操作，
也不能据它证明 ADSP 已拥有所需 QUP 或物理传感器已工作。

协议依据为 [Qualcomm fastrpc v1.0.7 apps_std](https://github.com/qualcomm/fastrpc/blob/v1.0.7/inc/apps_std.h)
和 [HexagonRPC PR #21](https://github.com/linux-msm/hexagonrpc/pull/21) 的 method 5/24 布局；
PR 固定 head `9f987970f9bc3e72081b7966a1f4e766ce6af6f7` 的写/删除为 stub，本补丁没有采用假成功逻辑。
复核了 liuqin `7df47f82` 的 registry-version/property 补丁与 upstream 文档的 SDM845 文件布局：
它们未提供这里需要的受限真实写入实现，未导入他机 registry、property 策略或 SLPI 启动服务。
本机社区 piano-sensors `65a92202` 也将 ODM/persist 导入副本供 sensorspd 使用，但用的是 Qualcomm
adsprpcd；本包继续原 HexagonRPC。详细文件/来源/hash/退出条件见 `../hexagonrpc/source.json` 和 NOTICE。新增第四项补丁仅调整父目录映射、失败日志和回放，写入约束不变。

`oemconfig.so`：保存的 stock tree 中没有该文件；v1 本机日志在它 ENOENT 后继续到 registry/config
文件读取，所以**就已观察的初始化序列而言是可选探测，不是当前最早阻塞**。保留真实 ENOENT，
不放空 ELF、不借用其他设备库。现有 persist 已解析 registry 是本次输入；不能凭其他端口的成功
保证 piano 的全部 OEM 初始化功能。如果 v3 文件链通过后仍失败，按新日志裁定。

## 本包原厂输入和实际路径

原始设备文件只在本地 `private-input/`，不进公开 Git/发布附件。公开 firmware 中的 ADSP
`adsp.mdt`/分段/DTB 仍由安装根 `/lib/firmware/qcom/sm8750/piano/` 提供，本包不重新装载它。

| DSP 请求 | bundle 输入/实际目的地 | 权限 |
|---|---|---|
| `/odm/etc/sensors/config/json.lst` 及 JSON | `private-input/hexagonfs/sensors/odm/config/`，原厂 ODM 60 文件 | 只读 |
| `/vendor/etc/sensors/config/*` | `sensors/config/`，原厂 vendor 3 文件；不以 ODM 覆盖 | 只读 |
| `/vendor/etc/sensors/sns_reg_config` | `sensors/sns_reg.conf`，原厂 271 B 文本 | 只读 |
| `/vendor/etc/sensors/sns_odp_config`、`hals.conf`、`javalibs/*` | `sensors/vendor/` 对应原件（vendor 全树 7 文件） | 只读 |
| `/mnt/vendor/persist/sensors/registry/*`（以及 `/persist/sensors/registry/*`） | 包内 `sensors/registry/` 的 **每轮 scratch 副本**；含版本/清单和 `registry/` 内层条目，传 `-w` 给 daemon | 可读写/删除副本 |
| `/sys/devices/soc0/*` | 每轮复制实际主线 sysfs 已有属性到输出的 socinfo/ | 只读 |
| `/usr/lib/qcom/adsp/`、`/vendor/etc/acdbdata/` | 空 dsp/adsp、acdb 目录；本次仅 sensorspd | 只读 |

整个父目录共 228 文件：内层原 226 项，加同一备份中 9 B 的 sns_reg_version 和 10,908 B 的
parsed_file_list.csv。都从既有已核 SHA 的 persist 备份离线提取；内层与 v2 pristine 逐项同 SHA。
不从 v2 已修改的 scratch 生成 v3，不重新读设备、不写真实备份。
69 行 ODM `json.lst` 中 53 项有现存原厂文件，已全部提供；余 16 项在本机保存的**整个** stock tree
中也没有同名文件。提取记录确认 vendor_a/odm_a 为完整 EROFS 提取，故它们在该原厂快照中不存在；
v2 日志在各 ENOENT 后继续解析，缺项被容忍。未新增它们，原列表不改。精确名单和搜索结果在 `private-input/input-status.json`。
不能把缺失项用默认值/他机配置补齐。其他原厂已存在但未列入 json.lst 的 ODM 配置也原样提供。

`sns_reg_config` 的两个 property 路径 file1/file2 也在该父目录内；只有固件明确创建时才出现，
不预填属性值。独立 `/mnt/vendor/persist/sensors/odp/` 仍无写权限，高 method 的未知 ABI 仍明确失败。
若同一次 ADSP 启动已放弃初始化，后续可能不再请求文件；保留新日志，脚本不自动重启 ADSP。

## 预期日志与回收

在设备上，把目录换成这次打印的 SSC_OUTPUT：

```sh
RESULT_DIR=/var/tmp/ssc-test/run-实际本次目录
cat "$RESULT_DIR/result.json" "$RESULT_DIR/sensors.json"
grep -E 'json.lst|sns_reg_version|fstempfile|parsed_file_list|/DIR|write\(|remove\(|Could not|Unknown|not implemented' "$RESULT_DIR/daemon.log"
grep -E 'registry|Discovered|Attributes populated|measurement:|Unable to' "$RESULT_DIR/accelerometer.log"
```

应看到外层 sns_reg_version/parsed_file_list.csv 可读，外层 fstempfile 写打开不再报只读；随后实际是否出现
write/remove、registry SUID、各类型 SUID/样本，均按真实日志判定。`oemconfig.so` ENOENT 可保留。
`kernel-before.log`/`kernel-after.log` 收集 FastRPC/ADSP/QRTR/SMMU 摘录，不清空 dmesg。
QMI debug 的 `translated = ERROR` 仅保留为 trace_diagnostics；真实 GLib 错误、CLI 失败、无样本仍 FAIL。

```sh
python3 public/xiaomipad-8pro-mainline/tools/piano-devmode-ssh.py \
  --serial "$PIANO_SERIAL" root \
  'tar -C /var/tmp/ssc-test -cf - run-实际本次目录 scratch/run-实际本次目录' > out/ssc-device-test-v3-results.tar
```

如仍无 registry，看**最早失败的文件/method**；不要把 QRTR 400、daemon 存活或 QMI ACK 当样本通过。
如该默认类型在完整 30 秒空 SUID 重查窗口后仍未出现，才标 UNAVAILABLE。光感/proximity 可能为 on-change，零帧
不直接证明硬件损坏。模长检查也不能替代方向、动态范围、自动旋转或休眠验收。

## 离线重建和验证

先用 `stage-input.py --stock-root <保存的vendor/odm根> --registry <已核备份提取的完整sensors/registry父目录>
--output <新私有输入目录>` 装配同机数据。`build-bundle.py` 接口保持不变，输入新私有目录，
新 output 为 `out/ssc-device-test-20261012-3/`。它校验固定 source.json/patch SHA 并用原 Meson 构建，
动态库/loader 随包携带，不替换系统库。沿用原交叉 sysroot、native protoc/Meson 与 qemu-user 环境。

新增 `tests/test_registry_io.c` 直接调用真实 apps_std handlers（模拟 DSP 请求，无 ioctl），
核对路径字节、写入/追加/截断/更新/删除、只读默认、越界路径、软/硬链接以及错误返回。
v2 负对照在相同外层 sns_reg_version 写打开返回 EROFS。v3 回放 295 个原厂文件（原 293 加两份
外层元数据），实际创建/更新 DIR 与三个外层路径，原件 SHA 保持不变。ARM64/native ASan/UBSan
15 项通过；ASan 不含 leak 检查，因为上游虚拟目录树仍为进程生命周期分配，不能称无泄漏审计。
原五条编译告警保留。扩展 QEMU QRTR mock 验证先空 SUID、后出现的传感器能采样，永久缺失类型
等待完整 30 秒后才 UNAVAILABLE，同一模拟 SSC 服务在重查期间保留；实际 FastRPC daemon 的
75 秒监督与不重启策略由 runner 执行，未在本轮访问真机。备份原本已有内容为 `DIR` 的 3 B 内层
文件，回放重写相同字节，其 SHA 不变；此前“新增 DIR”的表述不准确，实际内容变化为三个外层路径。
精确结果/失败记录见 offline-validation.json。
这些都是离线回放，不是本机 v3 样本 PASS。
