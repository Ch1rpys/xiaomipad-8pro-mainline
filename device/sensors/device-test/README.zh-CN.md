# SSC 一次性传感器检查（7.2.6-piano8）

此包只准备主机产物，设备步骤由操作者执行。**尚无 piano 真实传感器样本 PASS。**
复用固定 HexagonRPC 0.5.0（598b591a + 已有两个补丁）和 libssc 0.4.4
（54dd13e3 + 已有测试退出码补丁），不安装包/服务，不改变内核、DTS 或桌面规则。
daemon 是前台程序，由本次检查监督；60 秒 TERM、再 2 秒 KILL。
四个上游 `ssccli --sensor … --timeout 5` 同时运行，各自完成初始化/开流后读约 5 秒，
初始化和退出合计有共同 45 秒期限。无 daemon 重启或新重试逻辑；上游 libssc 的 registry
等待本来可达 100 秒，本包用外层期限截断它。

所有设备端新增文件在 `/var/tmp/ssc-test/`（或显式指定的 `/run/` 子目录）；
运行后终止并回收本次启动的进程，保留全部日志，不删除根系统文件，不停已有服务。
若已有 hexagonrpcd/ssccli/iio-sensor-proxy，拒绝再启动。读取传感器本身需要 QMI 开流/关流与
FastRPC attach，并非“零协议请求”；只读指不安装、不改配置/校准/Android 分区。
固定 HexagonFS mapped backend 用 `O_RDONLY` 打开映射文件，没有持久写 registry 的实现。

## 传输与运行

在主机工作区根目录执行。使用现有开发者模式连接、root 登录与主机密钥配置。
不用直接执行 scp/ssh；`piano-devmode-ssh.py` 内部仍通过 SSH 传输，透传标准输入。
二进制 tar 流不要加 `-t`。`PIANO_SERIAL` 必须是目标 piano 的序列号。

```sh
: "${PIANO_SERIAL:?先设置本机 piano 的序列号}"
set -o pipefail
tar -C out/ssc-device-test-20261012 -cf - . |
  python3 public/xiaomipad-8pro-mainline/tools/piano-devmode-ssh.py \
    --serial "$PIANO_SERIAL" root \
    'umask 077; mkdir -p /var/tmp/ssc-test/bundle-20261012; tar -xf - -C /var/tmp/ssc-test/bundle-20261012'

python3 public/xiaomipad-8pro-mainline/tools/piano-devmode-ssh.py \
  --serial "$PIANO_SERIAL" root \
  '/var/tmp/ssc-test/bundle-20261012/run.sh'
```

保持平板静止约一分钟；无需转动或操作桌面。本包不重启设备。
脚本打印本次 `SSC_OUTPUT=/var/tmp/ssc-test/run-…`，以及：

```text
SSC_CRITERION=Resting tablet: |a| approximately 9.8 m/s^2; ...
SSC_QRTR_400=[{"service": 400, ...}]
SSC_SENSOR=accelerometer RESULT=PASS SAMPLES=...
SSC_RESULT=PASS plausible acceleration and samples from all advertised requested types
SSC_SAMPLES=... SSC_ACCEL_G=9.8...
```

`SSC_ACCEL_G` 按任务约定命名，数值单位是 **m/s²**，不是 g 倍数；取加速度模长的中位数。
`result.json` 同时保留首个样本模长。静止粗判为至少 2 帧且中位数 7.8–11.8 m/s²。
这只是本次样本可信度检查，不能替代方向、动态量程、采样精度、旋转或挂起验收。

退出码 PASS=0、FAIL=1、UNAVAILABLE=2。上游 CLI 每个类型只查询默认 SUID，**没有全传感器
`--list` 接口**；本包的 `sensors.json` 是 libssc 对 accel/gyro/ambient_light/proximity 四类
默认传感器的实际发现列表，包含名字、厂商、SUID、属性、错误与计数。
不把未查询类型说成不存在。各类型 `.json` 保存全部样本，原始 `.log` 保存完整 libssc/QMI
输出；这些是 libssc 已应用固件安装矩阵的向量，未加本机或参考设备的额外变换。
CLI 不导出 DSP 时间戳/accuracy 字段，不用主机时间冒充。上游 gyro 输出单位标签写成 `m/s`，
本包原样记为 `upstream_unit`，不据该标签声明角速度校准正确。

设备上预期检查：

```sh
# 把本次 SSC_OUTPUT 的完整路径填入，不混用历史会话。
RESULT_DIR=/var/tmp/ssc-test/run-实际本次目录
cat "$RESULT_DIR/result.json" "$RESULT_DIR/sensors.json"
grep -E 'Starting|INIT_ATTACH|Could not|Unknown|not implemented' "$RESULT_DIR/daemon.log"
grep -E 'registry|Discovered|Attributes populated|measurement:|Unable to' "$RESULT_DIR/accelerometer.log"
```

回收同样使用 helper 标准输出（将 RESULT_DIR 换成本次真实路径）：

```sh
python3 public/xiaomipad-8pro-mainline/tools/piano-devmode-ssh.py \
  --serial "$PIANO_SERIAL" root \
  'tar -C /var/tmp/ssc-test -cf - run-实际本次目录' > out/ssc-device-test-results.tar
```

## secure 节点与内核依据

只有 `/dev/fastrpc-adsp-secure` **不构成本测试的源码阻塞**。
已安装 piano8 的内核基线为 `bcdf33caef53`；其 `drivers/misc/fastrpc.c`：

- `fastrpc_rpmsg_probe()` 取 `secure_dsp = !qcom,non-secure-domain`。
  ADSP/MDSP/SDSP 只注册所选的一种节点；`fastrpc_device_register()` 按该布尔值添加 `-secure`。
- `sm8750.dtsi` 的 ADSP `remoteproc@6800000/glink-edge/fastrpc` 没有
  `qcom,non-secure-domain`，piano DTS 继承该节点。CDSP 的同名属性不是 ADSP 的设置。
- `FASTRPC_IOCTL_INIT_ATTACH_SNS` 直接走 `fastrpc_init_attach(fl, SENSORS_PD)`。
  动态创建进程的 `is_session_rejected()` 条件不在这个 attach 路径上。
  HexagonRPC 的 `-f` 接受明确设备路径、`-s` 发该 ioctl；不需要节点别名、改权限或切换安全域。

因此本次命令固定为 `hexagonrpcd -f /dev/fastrpc-adsp-secure -d adsp -s -R <本次目录>/hexagonfs`。
上述只证明有可尝试的 API 路径；DSP 接受 attach、VMID/共享堆和实际文件服务仍需此次真机日志。
P23 的 QRTR 400 公告以及 P24-03 的 ADSP/GPR 通过都不等于这些检查通过。

## 精确文件输入与映射

公开 `firmware/qcom/sm8750/piano/` 中的 `adsp.mdt`、分段及 `adsp_dtb.*` 用于
内核 remoteproc 启动，预期已由安装根的 `/lib/firmware/qcom/sm8750/piano/` 提供。
本检查不重新下载/装载/重启 ADSP。公开 firmware **不含 SSC config 或运行 registry**。

本机交付包额外带有 **私有** `private-input/hexagonfs/`；不提交公开仓或上传发布附件。
运行时完整复制到 `SSC_OUTPUT/hexagonfs/`，`-R` 指向该副本。上游固定映射如下：

| bundle 内输入 | DSP 看见的路径 | 来源/状态 |
|---|---|---|
| `sensors/config/` | `/vendor/etc/sensors/config/`（亦有 `/system/vendor/` 别名） | 已保存的本机 vendor + ODM config，ODM 覆盖同名项；62 文件，含原始 `json.lst` |
| `sensors/sns_reg.conf` | `/vendor/etc/sensors/sns_reg_config` | 已保存的本机 vendor 原件；不是自造 registry |
| `sensors/registry/` | `/mnt/vendor/persist/sensors/registry/registry/`（亦有 `/persist/` 别名） | 从 2026-09-21 冻结读取、hash 已核的本机 persist 备份离线提取，226 文件；含本机数据，只留本地 |
| `socinfo/` | `/sys/devices/soc0/` | 运行时复制当前主线只读 sysfs 已有的 soc_id/revision 等；不伪造 Android 缺失属性 |
| `dsp/adsp/` | `/usr/lib/qcom/adsp/` | 当前为空；不混入 vendor/lib64 中的 ARM64 HAL/skel 或其他设备 DSP 文件 |
| `acdb/` | `/vendor/etc/acdbdata/` | 当前为空；本次仅 sensorspd，不启动音频 rootpd listener |

原始 `json.lst` 有 16 个在现存 vendor/ODM 提取树缺失的条目（交付包的
`private-input/input-status.json` 精确列出），没有删行或合成配置。运行 registry 已有默认
accel/gyro/ambient_light/proximity 组，但不是今天的枚举证据；若固件必须重新解析缺项，
本包可能失败，按日志中的精确请求补齐同版文件，不能把缺文件判成无传感器。
`sns_reg_config` 中的 sibling `registry/file1`/`file2` property 路径不在当前 HexagonFS 映射中；
如有这类请求，记录为已有文件服务能力边界，不改 stock 文件来隐藏它。

## 结果解释

| 观测 | 含义/下一证据 |
|---|---|
| secure 节点存在、没有非 secure 节点 | 正常候选输入，按上述 `-f` 运行；不创建链接、不改 DTS |
| `SSC_QRTR_400=[]` | 一次 nameservice 查询明确未找到服务；UNAVAILABLE，不运行 daemon。Python socket 查询失败则记日志并让 libssc 自己发现，不能当服务不存在 |
| daemon `Could not open` | 节点/权限问题；先看 facts，root 也不绕过内核错误 |
| `Could not attach` / listener register 失败 / daemon 提前退出 | FastRPC/PD/共享内存或 listener 层失败；即便退出码 0 也 FAIL，保留 daemon.log 与设备内核日志 |
| `registry unavailable`、45 秒仍未初始化 | SSC 服务未提供 registry；查 daemon 文件请求、现有 config/registry 映射。不是物理传感器缺失结论 |
| `No 'gyro' sensor available` 等明确 SUID 空回复 | 仅该默认类型 UNAVAILABLE；可选类型不阻挡合格 accel，但不宣称四类都通过 |
| 发现后无样本/CLI 非零/关闭报错 | 该类型 FAIL；光感/proximity 可能是 on-change，没帧不能直接推出硬件坏，需后续光照/遮挡实验 |
| accel 零向量、NaN/Inf 或模长异常 | FAIL；看坐标、单位/矩阵/数据链，不把 QRTR 公告或进程存活当 PASS |

整体 PASS 要求 daemon 在客户端完成前存活、accel 满足静止判据，其他已宣告类型均成功读样本且
CLI 正常退出。可选类型 UNAVAILABLE 在各自结果中保留。默认规则仍未启用 SensorProxy
accelerometer/proximity；本包不启动它，不会替桌面配置旋转。
QMI debug 中的 `translated = ERROR` 是可选文本解码器的诊断，不单独判为采样失败；
原文保留在日志及 JSON `trace_diagnostics`。CLI `Unable to …`、实际 GLib warning/error、
非零退出、无样本和不合理加速度仍会失败。内核前后 FastRPC/ADSP/QRTR/SMMU 摘录保存在
`kernel-before.log` / `kernel-after.log`，未清空 dmesg。

## 离线重建和验证

`../hexagonrpc/source.json`、`../libssc/source.json` 是固定输入；构建脚本先从这些提交
`git archive`，校验补丁 SHA，使用原 Meson，不修改上游工作树。需已有 ARM64 sysroot、
交叉编译器、Meson、native protoc/protoc-gen-c、qemu-aarch64-static；按传感器参考构建设置
PATH/原生工具 LD_LIBRARY_PATH。目标 link 搜索目录必须显式指向 sysroot（见 libssc README）。

```sh
python3 device/sensors/device-test/build-bundle.py \
  --hexagonrpc-source /path/to/hexagonrpc --libssc-source /path/to/libssc \
  --cross-file /path/to/arm64-cross.ini --sysroot /path/to/arm64-sysroot \
  --private-input /path/to/this-piano-private-input \
  --build /path/to/new-build --output /path/to/new-bundle
```

二进制动态依赖闭包及 loader 随包携带，以显式 `--library-path` 运行，不替换系统库。
`payload.json` 记录二进制、依赖、私有输入与脚本 SHA、上游锁、工具版本；设备运行前逐项核验。
构建启用上游 `hexagonrpcd_verbose`，用日志裁定缺失文件/方法，未增加第三个源码补丁。
HexagonRPC 14 项 qemu-user 测试纳入构建；libssc `--help` 和 daemon `--help` 离线执行结果、
SensorProxy 回归与脚本检查见本机交付 `offline-validation.json`。
该 HexagonRPC pin 尚无正式 `--help` 选项：打印 Usage 并返回 4 是其既有行为，不是加载失败。
不为此新增补丁。SensorProxy 的遗留 0004 已独立验证并保留来源；本次采样不依赖该 daemon。
开启上游 verbose 后额外暴露 apps_mem 的 `%lx`/`__u64` 格式告警，加上原有四条 read 返回值
告警共五条；构建通过，不称零告警，不添加超出已批准两项的 RPC 补丁。
