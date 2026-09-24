# Ubuntu for Xiaomi Pad 8 Pro

目标是在 Xiaomi Pad 8 Pro（piano / SM8750）上原生运行主线系 Linux 与 Ubuntu ARM64 桌面。
[English](README.md)

**P12/P13 已在本机原生运行 Ubuntu 26.04 GNOME 桌面和终端，P13 内屏目视正常并验证 200% 缩放；触控/真实输入尚未验收，没有安装镜像。**
本仓库提供最小 piano 内核/DTS 构建、诊断 ramdisk、原厂 overlay 隔离打包和 RAM 镜像生成，
以及保留属主、硬链接和扩展属性的无 root Ubuntu 桌面层合并。有界 RAM 诊断启动不能视作可用 Ubuntu 系统。
还提供本地 DSP 固件 deb、隔离 APT 输入和无 root ext4 装配；根系统已在 QEMU 运行 Ubuntu systemd/指定命令，
dracut 更新包已下载但未安装，不能外推平板桌面支持。
另有[原生 THP 手指处理组件](device/piano-thp/README.md)：从用户提供的本机配置提取私有标定，
并完成 host/ARM64 静态记录回放；SPI/live/uinput 仍未接通，不代表触控可用。

## 仓库分工

本仓库负责 Ubuntu 集成、设备用户态、构建/安装工具和用户文档。
Linux 驱动、设备树和内核配置维护在独立内核仓库；远端尚未建立，不提供虚构地址。
[kernel/source.json](kernel/source.json) 锁定本地诊断源码提交与配置，构建器实际读取该文件。
当前仍需提供独立本地内核检出；公开远端发布前不宣称第三方能够直接拉取该项目提交。

内部实验记录、设备备份、校准及身份不在本仓库维护。
不把其他小米/一加平板镜像用于此设备。

## 已提供的工具

```sh
sh tools/fetch-aosp-mkbootimg.sh
```

需要 Git、Python 3 和 sha256sum；首次运行需要网络。
工具在 tools/local/aosp-mkbootimg 获取固定 AOSP 提交，
校验 mkbootimg.py 与 unpack_bootimg.py，并检查命令入口。
此操作不访问设备、不构建 piano 镜像。下载和检出均不进入 Git。
详见[工具说明](docs/tools.zh-CN.md)和[离线构建](docs/build.zh-CN.md)。

## 硬件状态

P04/P05 的 USB2 NCM、自动 DHCP、双向命令、精确身份与运行 FDT 已在 piano 验证，正常 60 秒会话能自行返回 Android。
跨重启 pstore 仍有损坏，故障恢复和完整 Type-C/SS/DP 尚未验收；P03 ACM 未实测，已后移。
P12 为标准 simpledrm 补齐显示 AXI 时钟依赖，P13 内屏桌面已目视确认；仍依赖固件扫描输出，不等于原生面板/亮度/唤醒支持。
实际 Ubuntu 根在 RAM 中校验、挂载并交接；显式诊断时可在 RAM 层使用锁定临时用户和标准 GDM 自动登录，重启即丢弃。
P12/P13 自动回 Android 已验证；桌面和终端绘制不等于触控或键鼠已可用。
P06 曾因临时工具命名错误失去控制/自动退出，已在离线复现并修正，失败不能被后续结果覆盖。
触控、GPU、无线、音频、键盘、传感器、电源和持久安装均未验收。
官方 Android 驱动和同 SoC 社区实现仅为候选来源，不代表主线支持已经成立。

## 贡献与许可

请阅读[贡献规范](CONTRIBUTING.md)及[来源说明](NOTICE)。
除文件另有声明外，本项目原创代码采用 [MIT](LICENSE)。复用的一加诊断工具保持 GPL-2.0-only，
小米集成工具保持 MIT；Linux、BusyBox、Ubuntu 与 AOSP 保留各自许可。
