# piano 传感器产品集成

适用于 Ubuntu 26.04 ARM64、带 secure ADSP FastRPC/QRTR 的 piano 内核（本次用户原始 SSC 验证为
`7.2.6-piano8`）。2026-10-12 用户在全新启动上用 v4 获得加速度/陀螺各 132 样本、光感 2、
距离 1，静止加速度模长中位数 9.86 m/s²，pristine registry 未变。本包是该实现的产品集成，
**包启动、GNOME 四向旋转和自动亮度尚待用户真机验证**，不能继承诊断脚本的全部通过结论。

## 包和边界

- `piano-sensors 0.1+20261012.1`：上游 hexagonrpc 0.5.0 固定提交及六个锁定补丁，包含原样导入的
  `f0dfd5095d3b7defc3b368f227337bfc6d6aef42` large-in-bufs 提交；独立的 systemd/udev 集成。
- `piano-iio-sensor-proxy 3.9+piano20261012.1`：固定 iio-sensor-proxy 3.9、libssc 0.4.4，保留
  `libssc/sensorproxy.json` 全部五个补丁（现有文件编号为 0003、0004、0005、0006、0001，未重编号，
  0004 保留）。标准 `net.hadess.SensorProxy`、`iio-sensor-proxy.service` 和 `monitor-sensor` 不改名。
  使用 `Provides: iio-sensor-proxy (= 3.9)`、`Conflicts/Replaces: iio-sensor-proxy` 接管同一服务，
  让 GNOME orientation/自动亮度消费者无需修改，也避免两个代理同时运行。
  包替换语义见 [Debian Policy §7](https://www.debian.org/doc/debian-policy/ch-relationships.html#replacing-whole-packages-forcing-their-removal)。

协议代码仍由 upstream Meson 构建；不调用 APT/GDM、不假定桌面用户名。包/服务位于 `packaging/`；
私有库只装入 `/usr/lib/aarch64-linux-gnu/piano-sensors/` 和 `piano-iio-sensor-proxy/`，其余运行库使用发行版包。
当发行版具备 SSC 与等价冷插拔/通知/释放/轮询修复并通过同样回归后，撤销代理替换，回归发行版维护。
来源、许可证、补丁 hash 和退出条件见相邻 `hexagonrpc/source.json`、`libssc/*.json` 和 `NOTICE`。

## 原厂配置与私有标定

`firmware/sensors/` 的 66 个文件来自 OS3.0.303.0.WPYCNXM ROM 的 ODM/vendor 配置树。
已检查它们为静态配置而非 persist 数据；没有序列号/MAC，配置中的 fac_cal 是 ROM 默认值。
按 2026-10-12 用户要求沿用 `firmware/` 政策公开：**没有已确立的再分发许可，应权利方要求移除**，
它们不因集成仓 MIT 而被重新授权。逐文件来源/hash 在 `firmware/sensors/source.json`。
不额外装 Android Java HAL 库；v4 中缺失的 oemconfig.so/部分 json 仍可能有非致命日志，不伪造文件。

persist registry 即使不含序列号/MAC，也含每台设备唯一的传感器 `fac_cal`，**不能入公开仓、通用包，
也不能借用其他平板的副本**。可选工具 `tools/stage-sensor-registry.py` 只消费用户自己的已提取备份，
不读设备、不挂载分区。输入必须是外层 `sensors/registry/`，其下还有内层 `registry/` 及版本/解析列表。

包把不可变 ODM/vendor 配置和空的默认 registry 种子装入 `/usr/share/piano/sensors/`；私有种子放
`/usr/share/piano/sensors/registry-private/`。首次启动复制私有种子（有则使用）或空默认种子至
`/var/lib/piano/sensors/registry/`，让 DSP 按 stock JSON 生成默认标定。后者日志明确打印
`SSC_REGISTRY=stock-default-calibration`；不因缺私有数据拒绝传感器，但默认标定的可用性/精度尚未真机验收。
DSP 写入仅映射到该可写状态，`ProtectSystem=strict` 保持 pristine 配置/种子只读。
升级或普通重启不会覆盖现有状态，也不会重新复制私有种子。

## 安装（由用户在平板执行）

先把交付目录复制到平板，再在该目录执行。以下命令不会刷内核或切槽。

```sh
cd debs
sha256sum -c SHA256SUMS
# 保存当前 Ubuntu 代理的准确版本和包，供离线回滚。
mkdir -p ../rollback
dpkg-query -W -f='${Version}\n' iio-sensor-proxy > ../rollback/iio-sensor-proxy.version
(cd ../rollback && apt-get download "iio-sensor-proxy=$(cat iio-sensor-proxy.version)")
sudo apt install ./piano-sensors_0.1+20261012.1_arm64.deb
sudo apt install ./piano-iio-sensor-proxy_3.9+piano20261012.1_arm64.deb
cd ..
```

APT 应只替换 Ubuntu 的 iio-sensor-proxy；不要接受移除 GNOME 桌面的解算结果。
若原系统没有 iio-sensor-proxy，则跳过保存版本/下载步骤，回滚时仅移除两个 piano 包。
包配置仅启用下次启动，不现场启动/重启 DSP；已有诊断 daemon 必须结束，并正常重启。

可选：在主机从**这台设备**的备份准备私有载荷（该目录不得分享）：

```sh
python3 tools/stage-sensor-registry.py \
  --registry /path/to/own/extracted/persist/sensors/registry \
  --output /path/to/private-sensor-payload
```

把 `private-sensor-payload` 安全复制到平板，在首次启动包服务前执行：

```sh
sudo test ! -e /usr/share/piano/sensors/registry-private
sudo cp -a private-sensor-payload/usr/share/piano/sensors/registry-private /usr/share/piano/sensors/
sudo chown -R root:root /usr/share/piano/sensors/registry-private
sudo reboot
```

不使用私有标定也须 `sudo reboot` 后再测。若已经生成状态，先停止两个服务，将旧状态目录移到自己选定的
备份位置，再装私有种子并正常重启；不要删除原备份、不要把含校准的目录发到公开 issue。

## 全新启动后的检查

```sh
piano-sensors-check | tee sensors-check.txt
# 或交付目录中的 ./check.sh
journalctl -b -u piano-hexagonrpcd-sns -u iio-sensor-proxy --no-pager
```

检查脚本输出 boot ID/内核、两个服务状态、5 秒 `monitor-sensor --accel`，以及：

```sh
busctl --system get-property net.hadess.SensorProxy /net/hadess/SensorProxy net.hadess.SensorProxy HasAccelerometer
busctl --system get-property net.hadess.SensorProxy /net/hadess/SensorProxy net.hadess.SensorProxy AccelerometerOrientation
```

`HasAccelerometer` 应为 `b true`，方向应随竖起并旋转平板变为 `normal`、`bottom-up`、`left-up`、`right-up`；
平放时方向不适合作为判据。脚本会在 5 秒结束 monitor；超时 124 是预期退出，不是硬件 PASS。
关闭 GNOME 旋转锁，以四个边分别朝上，检查桌面文字正立、方向标签变化与屏幕同步；键盘/平板模式策略也可能
禁止旋转，不用修改 GNOME 消费者或强制某个账户设置来掩盖问题。

板级 udev 配置将 stock `sm8750_lsm6dso_0.json` 的 `.orient x=-x,y=-y,z=+z` 作为
`ACCEL_MOUNT_MATRIX="-1, 0, 0; 0, -1, 0; 0, 0, 1"` 交给现有 SSC 加速度驱动；没有改算法。
该配置是源码依据，不能代替物理四向真值；DSP 也消费 stock orientation，真机还需排除重复变换。
触控历史工作曾遇到固定 90° 坐标偏转，随后在触控用户态修正；它不是这颗传感器的安装矩阵证据。
每个方向都点四角检查触点位置，若仅触点偏 90°，分别记录触控与显示坐标，不为补偿触控盲改传感器矩阵。

```sh
timeout --signal=TERM --kill-after=2s 15s monitor-sensor --light
busctl --system get-property net.hadess.SensorProxy /net/hadess/SensorProxy net.hadess.SensorProxy HasAmbientLight
```

遮挡/照亮传感器应使 lux 变化；在 GNOME 电源设置启用自动亮度后独立检查背光是否变化。
仅 `HasAmbientLight=true`、服务 active 或一次数值不能证明自动亮度有效。

服务由 secure FastRPC udev 事件或正常启动触发；准备程序核对 piano DT、通过 DT compatible 识别的 ADSP remoteproc 为 running，
最多等待 QRTR 服务 400 五秒，之后启动 sensor PD。硬件未就绪会留下明确失败日志，不用无限重试。
失败后先保留 journal、确认固件/内核条件，再正常重启复测；不反复手工重启 hexagonrpcd。

## 精确卸载/回滚

先保存自己的私有种子及状态。若有保存的 Ubuntu 包，在交付目录执行：

```sh
sudo systemctl stop iio-sensor-proxy.service piano-hexagonrpcd-sns.service
# 同一 APT 事务以原版本恢复标准代理，并移除替换包。
sudo apt install ./rollback/iio-sensor-proxy_*_arm64.deb piano-iio-sensor-proxy- piano-sensors-
sudo apt purge piano-iio-sensor-proxy piano-sensors
sudo reboot
```

若安装前没有代理：`sudo apt purge piano-iio-sensor-proxy piano-sensors` 后正常重启。
没有原包缓存但联网时，可用 `sudo apt install iio-sensor-proxy piano-iio-sensor-proxy- piano-sensors-` 恢复
仓库版本（不一定与安装前相同）。本包未改内核、固件包、GNOME 用户配置或触控程序，不需要回刷。
remove/purge 保留私有标定和学习状态；确认有自己的备份后，若要彻底删除其剩余数据：

```sh
sudo rm -rf /var/lib/piano/sensors /usr/share/piano/sensors/registry-private
```

## 主机构建和离线验证

```sh
python3 tools/build-sensors-debs.py \
  --hexagonrpc-source /path/to/hexagonrpc-git --libssc-source /path/to/libssc-git \
  --sensorproxy-source /path/to/iio-sensor-proxy-git \
  --cross-file /path/to/arm64-cross.ini --sysroot /path/to/ubuntu-arm64-sysroot \
  --output /path/to/piano-sensors-output
```

需要 Meson >=1.4、Ninja、ARM64 GCC/binutils、pkg-config、patchelf、dpkg-deb、qemu-user，
ARM64 GLib/QMI/protobuf-c/GUdev/polkit 开发库及主机 protoc/protoc-gen-c/GLib 生成工具；
SensorProxy Python 模拟测试在 ARM64 guest 中运行，需 gi/dbusmock/psutil/UMockdev。完整 source commit/patch/config hash、工具版本和
包文件清单在输出 `manifest.json`；构建日志在 `build/`。不自动安装到主机、不访问设备。
本次离线结果另见交付目录 `verification.json`；模拟传感器与 QEMU 结果不等于 GNOME 真机验收。
