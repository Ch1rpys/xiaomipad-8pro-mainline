# SSC 一次性检查 v2（7.2.6-piano8）

v2 修复已由用户真机日志证实的文件服务缺口：**ODM 路径没有映射，registry 写打开被拒绝**。
这两处发生在 FastRPC sensorspd 已开始请求文件、QMI SSC 已回复成功之后；不是 secure 节点不能 attach。
尚未以 v2 取得 piano 样本。主机工作已完成，设备步骤由操作者执行。

复用原 HexagonRPC `598b591a` + 前两项序列修复 + 新增第三项文件服务补丁，libssc
`54dd13e3` 及其测试退出码补丁不变。没有新 daemon/框架、内核修改或服务安装。
`run.sh` 保持 v1 的 60 秒 daemon 超时（TERM 后 2 秒 KILL）、四类默认 sensor 查询、
每类开流后约 5 秒采样和共同 45 秒客户端期限，结束时回收本次启动的全部进程。

## 精确传输与运行

在主机工作区根目录执行，沿用已设置的开发者模式/root 登录。`PIANO_SERIAL` 为目标 piano 的
序列号。本地交付 README 已填本机值，公开仓文档不含它。不直接调用 scp/ssh；helper 内部仍用
SSH，并透传 stdin。tar 二进制流不要加 `-t`。

```sh
: "${PIANO_SERIAL:?先设置本机 piano 的序列号}"
set -o pipefail
tar -C out/ssc-device-test-20261012-2 -cf - . |
  python3 public/xiaomipad-8pro-mainline/tools/piano-devmode-ssh.py \
    --serial "$PIANO_SERIAL" root \
    'umask 077; mkdir -p /var/tmp/ssc-test/bundle-20261012-2; tar -xf - -C /var/tmp/ssc-test/bundle-20261012-2'

python3 public/xiaomipad-8pro-mainline/tools/piano-devmode-ssh.py \
  --serial "$PIANO_SERIAL" root \
  '/var/tmp/ssc-test/bundle-20261012-2/run.sh'
```

静置平板约一分钟。脚本打印本轮 `SSC_OUTPUT` 与 `SSC_SCRATCH`，不要混入旧会话。
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

用户的 v1 12 行 daemon 日志依次证实：`oemconfig.so` 找不到，vendor `sns_reg_config` 两次
成功读取（271 B），`registry/DIR` 写打开被拒绝，最后 ODM `config/json.lst` 打开失败。
加速度前 140 行包含 QRTR node 5/port 19、QMI Control 成功；完整日志约 30 次轮询后触发
30 秒超时，`(30/100)` 中 100 是重试上限。无需延时或更换 kernel 来解释这些失败。

新增文件服务补丁：

- 增加 `/odm/etc/sensors/` 的只读映射，vendor/ODM 目录分别保留原厂内容，不混合两处不同的
  `chre_dynamic_sensors.json`。继续原 upstream vendor 路径，并提供 vendor 的 sns_odp_config、hals.conf、javalibs。
- `-w DIR` 显式选择唯一可写 registry 根；未传该参数仍只读。`fopen` 的 r/w/a、binary/update
  模式具有实际读写语义；method 5 fwrite 返回真实写入字节，method 24 remove 真正删除 scratch 文件。
  普通映射仍拒绝写入，拒绝软链接、硬链接和非普通文件写目标；`..` 只能回到原虚拟目录，不能赋予外部路径写权限。
- 每轮新建 0700 scratch 目录，复制为新 inode、文件 0600。记录 `registry-pristine.json`、
  `registry-before.json`、`registry-after.json`，结束核验 pristine 未变并列出 scratch 改变项。
  保留 scratch 及日志；不还原或删除根系统文件。写入的只是试验副本，不是永久校准更新。

协议依据为 [Qualcomm fastrpc v1.0.7 apps_std](https://github.com/qualcomm/fastrpc/blob/v1.0.7/inc/apps_std.h)
和 [HexagonRPC PR #21](https://github.com/linux-msm/hexagonrpc/pull/21) 的 method 5/24 布局；
PR 固定 head `9f987970f9bc3e72081b7966a1f4e766ce6af6f7` 的写/删除为 stub，本补丁没有采用假成功逻辑。
复核了 liuqin `7df47f82` 的 registry-version/property 补丁与 upstream 文档的 SDM845 文件布局：
它们未提供这里需要的受限真实写入实现，未导入他机 registry、property 策略或 SLPI 启动服务。
本机社区 piano-sensors `65a92202` 也将 ODM/persist 导入副本供 sensorspd 使用，但用的是 Qualcomm
adsprpcd；本包继续原 HexagonRPC。详细文件/来源/hash/退出条件见 `../hexagonrpc/source.json` 和 NOTICE。

`oemconfig.so`：保存的 stock tree 中没有该文件；本机日志在它 ENOENT 后继续到 registry/config
文件读取，所以**就已观察的初始化序列而言是可选探测，不是当前最早阻塞**。保留真实 ENOENT，
不放空 ELF、不借用其他设备库。现有 persist 已解析 registry 是本次输入；不能凭其他端口的成功
保证 piano 的全部 OEM 初始化功能。如果 v2 文件链通过后仍失败，按新日志裁定。

## 本包原厂输入和实际路径

原始设备文件只在本地 `private-input/`，不进公开 Git/发布附件。公开 firmware 中的 ADSP
`adsp.mdt`/分段/DTB 仍由安装根 `/lib/firmware/qcom/sm8750/piano/` 提供，本包不重新装载它。

| DSP 请求 | bundle 输入/实际目的地 | 权限 |
|---|---|---|
| `/odm/etc/sensors/config/json.lst` 及 JSON | `private-input/hexagonfs/sensors/odm/config/`，原厂 ODM 60 文件 | 只读 |
| `/vendor/etc/sensors/config/*` | `sensors/config/`，原厂 vendor 3 文件；不以 ODM 覆盖 | 只读 |
| `/vendor/etc/sensors/sns_reg_config` | `sensors/sns_reg.conf`，原厂 271 B 文本 | 只读 |
| `/vendor/etc/sensors/sns_odp_config`、`hals.conf`、`javalibs/*` | `sensors/vendor/` 对应原件（vendor 全树 7 文件） | 只读 |
| `/mnt/vendor/persist/sensors/registry/registry/*`（以及 `/persist/…`） | 包内 `sensors/registry/` 的 **每轮 scratch 副本**；传 `-w` 给 daemon | 可读写/删除副本 |
| `/sys/devices/soc0/*` | 每轮复制实际主线 sysfs 已有属性到输出的 socinfo/ | 只读 |
| `/usr/lib/qcom/adsp/`、`/vendor/etc/acdbdata/` | 空 dsp/adsp、acdb 目录；本次仅 sensorspd | 只读 |

运行 registry 的 226 文件来自既有、已核 hash 的本机 persist 备份。本轮再与 v1 pristine SHA
逐项核对，不重新读设备，不往真实备份写入。
69 行 ODM `json.lst` 中 53 项有现存原厂文件，已全部提供；余 16 项在本机保存的**整个** stock tree
中也没有同名文件，因此未新增它们，原列表不改。精确名单和搜索结果在 `private-input/input-status.json`。
不能把缺失项用默认值/他机配置补齐。其他原厂已存在但未列入 json.lst 的 ODM 配置也原样提供。

`sns_reg_config` 的两个 property 路径是 registry 的 sibling `file1`/`file2`，sns_odp_config
指向独立 `/mnt/vendor/persist/sensors/odp/`；当前日志没有请求这些服务，不扩大写权限。
若随后出现 sibling version/property、ODP 或更高 FastRPC method 请求，会明确失败并留下日志，
不添加未知 ABI 的成功 stub。若同一次 ADSP 启动已经放弃初始化，再次运行可能不再请求配置；
保留这次记录，由操作者另行决定是否正常重启系统后再测，脚本不重启 ADSP。

## 预期日志与回收

在设备上，把目录换成这次打印的 SSC_OUTPUT：

```sh
RESULT_DIR=/var/tmp/ssc-test/run-实际本次目录
cat "$RESULT_DIR/result.json" "$RESULT_DIR/sensors.json"
grep -E 'json.lst|sns_reg_config|/DIR|write\(|remove\(|Could not|Unknown|not implemented' "$RESULT_DIR/daemon.log"
grep -E 'registry|Discovered|Attributes populated|measurement:|Unable to' "$RESULT_DIR/accelerometer.log"
```

应看到 ODM json.lst 成功 open/read/close，`registry/DIR` 的写打开不再报拒绝；随后实际是否出现
write/remove、registry SUID、各类型 SUID/样本，均按真实日志判定。`oemconfig.so` ENOENT 可保留。
`kernel-before.log`/`kernel-after.log` 收集 FastRPC/ADSP/QRTR/SMMU 摘录，不清空 dmesg。
QMI debug 的 `translated = ERROR` 仅保留为 trace_diagnostics；真实 GLib 错误、CLI 失败、无样本仍 FAIL。

```sh
python3 public/xiaomipad-8pro-mainline/tools/piano-devmode-ssh.py \
  --serial "$PIANO_SERIAL" root \
  'tar -C /var/tmp/ssc-test -cf - run-实际本次目录 scratch/run-实际本次目录' > out/ssc-device-test-v2-results.tar
```

如仍无 registry，看**最早失败的文件/method**；不要把 QRTR 400、daemon 存活或 QMI ACK 当样本通过。
如明确回复某类型无 SUID，只标该默认类型 UNAVAILABLE。光感/proximity 可能为 on-change，零帧
不直接证明硬件损坏。模长检查也不能替代方向、动态范围、自动旋转或休眠验收。

## 离线重建和验证

先用 `stage-input.py --stock-root <保存的vendor/odm根> --registry <已核备份提取的registry目录>
--output <新私有输入目录>` 装配同机数据。`build-bundle.py` 接口保持不变，输入新私有目录，
新 output 为 `out/ssc-device-test-20261012-2/`。它校验固定 source.json/patch SHA 并用原 Meson 构建，
动态库/loader 随包携带，不替换系统库。沿用原交叉 sysroot、native protoc/Meson 与 qemu-user 环境。

新增 `tests/test_registry_io.c` 直接调用真实 apps_std handlers（模拟 DSP 请求，无 ioctl），
核对路径字节、写入/追加/截断/更新/删除、只读默认、越界路径、软/硬链接以及错误返回。
原 v1 同一负对照在 ODM json.lst 失败。ARM64 回放对 293 个本机原件逐字节比对，只在 scratch
新增 3 字节 `DIR`，原输入/registry 哈希不变。主机 ASan/UBSan 检查与 ARM64 15 项通过；
ASan 未启用 leak 检查：上游构建的虚拟目录树原本是进程生命周期分配、没有释放树接口，
不将这次内存安全检查说成无泄漏审计。已有四条 read 返回值告警和一条 verbose 格式告警保留。
最终校验、完整/失败日志 hash 见本地 `offline-validation.json`；**不是本机 v2 样本 PASS**。
