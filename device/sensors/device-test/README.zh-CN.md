# SSC 一次性检查 v4（7.2.6-piano8）

v3 在用户正常重启后已通过 registry scratch 写入，随后在大块 fstempfile 写请求处退出：
`Large (>256B) input buffers aren't implemented`。同一次 ADSP 启动内重启 hexagonrpcd 不会重置
sensors PD；旧启动下零文件请求不能拿来评价新包。**v4 修复 listener 大包续取，并强制共享 boot_id 准入。**

固定基线仍为 HexagonRPC `598b591a`，先保留本项目原四项补丁，再原样导入上游 PR #27 的
[`f0dfd5095d3b7defc3b368f227337bfc6d6aef42`](https://github.com/linux-msm/hexagonrpc/commit/f0dfd5095d3b7defc3b368f227337bfc6d6aef42)。
它是 PR 提交，未声称已进入 upstream main；原作者 Fady、日期和 Signed-off-by 保留，已在隔离
源码仓对固定基线 clean cherry-pick。另有本地第六项最小校验/回归补丁，详见 source.json/NOTICE。
libssc/ssccli 不变，保留空 SUID 30 秒重查、5 秒采样、客户端 70 秒/daemon 75 秒的上限。

### 256 B 与真正的 FastRPC ABI

这是 DSP→AP listener 的首段容量。超过 256 B，必须用同一 rctx 调用
`adsp_listener_get_in_bufs2`（method 5、offset=256）获取余段，重组后才解码和调用真实 fwrite。
不是把栈数组任意改大，也不是将 DSP 指针当作主机指针。

这些“输入”对 AP 发起的 get_in_bufs2 RPC 而言是**输出参数**。本库现有 marshaller 使用
`FASTRPC_IOCTL_INVOKE`、参数 fd=-1；所核 piano 内核的 `fastrpc_get_args()` 会为这一路径分配
DMA/remote-heap 载荷、填写物理页描述，`fastrpc_put_args()` 将输出复制回用户缓冲区。
源码没有“超过 256 B 必须提供 ION fd”的分支。因此复用现有映射机制，无新增 /dev/ion、DMA heap
依赖或内核修改。参照 [Qualcomm listener_android.c](https://github.com/qualcomm/fastrpc/blob/v1.0.7/src/listener_android.c)
和 [adsp_listener.h](https://github.com/qualcomm/fastrpc/blob/v1.0.7/inc/adsp_listener.h)。

上游续取限制为 16 MiB；本地补充返回长度上界检查、失败释放与空错误回复编码长度修正。
未知 RPC 仍回真正的 AEE 错误，不伪造成功。scratch 的目录、链接和文件类型约束保持。

## 精确传输与运行

在主机工作区根目录执行，沿用已设置的开发者模式/root 登录。`PIANO_SERIAL` 为目标 piano 的
序列号。本地交付 README 已填本机值，公开仓文档不含它。不直接调用 scp/ssh；helper 内部仍用
SSH，并透传 stdin。tar 二进制流不要加 `-t`。

```sh
: "${PIANO_SERIAL:?先设置本机 piano 的序列号}"
set -o pipefail
tar -C out/ssc-device-test-20261012-4 -cf - . |
  python3 public/xiaomipad-8pro-mainline/tools/piano-devmode-ssh.py \
    --serial "$PIANO_SERIAL" root \
    'umask 077; mkdir -p /var/tmp/ssc-test/bundle-20261012-4; tar -xf - -C /var/tmp/ssc-test/bundle-20261012-4'

python3 public/xiaomipad-8pro-mainline/tools/piano-devmode-ssh.py \
  --serial "$PIANO_SERIAL" root \
  '/var/tmp/ssc-test/bundle-20261012-4/run.sh'
```

**首次启用守卫：上面的第一次运行会仅登记当前 boot_id，打印 `SSC_FRESH_BOOT=NO` 并返回 2，
不会查询 QRTR 或启动 daemon/CLI。请先在当前 Ubuntu 启动完成这次登记，再正常重启回 Ubuntu，
重新执行上面的运行命令。**若已经有另一轮 v4 的历史，重启后的正常运行会直接得到 YES。

原因是 v1–v3 没有记录 boot_id，首次空历史不能证明当前 ADSP 是否已被它们使用。守卫采用
`/proc/sys/kernel/random/boot_id`，状态固定放在跨版本共享的 `/var/tmp/ssc-test/last-boot-id` 和
`boot-history.json`，不随 bundle 路径或 --output 改变。任何已记录的 boot ID 都拒绝，不仅是最后一个；
在 DSP 接触前先落盘，实验失败也不解除标记。`fresh-boot.json`、facts 和 result 都记录实际判定。

显式诊断可用 `run.sh --force` 覆盖首次/重复启动拒绝，但仍打印 `SSC_FRESH_BOOT=NO`、记录 forced=true；
其结果不构成新启动验收。损坏或无法落盘的历史会明确报错，不静默重置。
boot_id 只覆盖经本守卫登记的调用，不能识别用户另行运行旧版/其他 listener 的行为或 DSP 内部重启；
可判定的试验应正常重启后首先运行本包。脚本不替用户重启系统/ADSP。

静置平板，观察窗口最长约 75 秒。脚本打印本轮 `SSC_OUTPUT` 与 `SSC_SCRATCH`，不要混入旧会话。
输出默认在 `/var/tmp/ssc-test/run-…/`，可写 registry 在
`/var/tmp/ssc-test/scratch/run-…/registry/`。若显式使用 `/run/` 下的输出目录，则 scratch
跟随该目录。包内 pristine 数据、主机 persist 备份和设备真实 persist 均不作为写目标。
不自动重启设备/ADSP、不停已有传感器服务；发现已有 hexagonrpcd/ssccli/iio-sensor-proxy 会拒绝运行。

```text
SSC_FRESH_BOOT=YES
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
保证 piano 的全部 OEM 初始化功能。如果 v4 文件链通过后仍失败，按新日志裁定。

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
不使用任何已运行的 scratch 生成新输入，不重新读设备、不写真实备份。
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
  'tar -C /var/tmp/ssc-test -cf - run-实际本次目录 scratch/run-实际本次目录' > out/ssc-device-test-v4-results.tar
```

如仍无 registry，看**最早失败的文件/method**；不要把 QRTR 400、daemon 存活或 QMI ACK 当样本通过。
如该默认类型在完整 30 秒空 SUID 重查窗口后仍未出现，才标 UNAVAILABLE。光感/proximity 可能为 on-change，零帧
不直接证明硬件损坏。模长检查也不能替代方向、动态范围、自动旋转或休眠验收。

## 离线重建和验证

先用 `stage-input.py --stock-root <保存的vendor/odm根> --registry <已核备份提取的完整sensors/registry父目录>
--output <新私有输入目录>` 装配同机数据。`build-bundle.py` 接口保持不变，输入新私有目录，
新 output 为 `out/ssc-device-test-20261012-4/`。它校验固定 source.json/patch SHA 并用原 Meson 构建，
动态库/loader 随包携带，不替换系统库。沿用原交叉 sysroot、native protoc/Meson 与 qemu-user 环境。

原 registry-io 和目录边界用例保留。新增 `test_listener_large.c` 只模拟 ioctl 的 DSP 响应，实际执行
libhexagonrpc marshaller → next2/get_in_bufs2 → decoder → apps_std fwrite → HexagonFS → scratch 文件。
校验同一 context、offset=256、标量/缓冲区长度和 fd=-1 ABI；4 KiB、64 KiB 含零字节载荷逐字节读回。
还覆盖编码总长 256/257 B 边界、续取错误、长度异常、16 MiB 上限、截断包、真实 unsupported 回复。
这比旧的直接调用 apps_std 小缓冲区回放多覆盖了发生故障的 listener 层。

v3 的同一 4 KiB/64 KiB 负对照复现旧错误；v4 ARM64 24/24、native ASan/UBSan 24/24、runner/守卫
20/20。ASan 延续不含上游进程生命周期目录树 leak 审计的范围；原五条编译告警保留。
这里验证的是 ioctl 参数和实际用户态文件操作，未模拟真实 DMA/安全固件接受过程，不是真机 PASS。
输入 registry/config 和 16 个缺项处置与 v3 相同，未补造 oemconfig.so 或 JSON。
精确来源、cherry-pick 身份、输入与失败/最终日志 SHA 见本地 offline-validation.json。
