# Ubuntu for Xiaomi Pad 8 Pro

目标是在 Xiaomi Pad 8 Pro（piano / SM8750）上原生运行主线系 Linux 与 Ubuntu ARM64 桌面。
[English](README.md)

**当前处于主线首启诊断阶段。P01 实测停在厂商 ABL 的设备树 overlay 合成；没有可安装镜像或主线功能通过记录。**
本仓库提供最小 piano 内核/DTS 构建、诊断 ramdisk、原厂 overlay 隔离打包和 RAM 镜像生成，
以及保留属主、硬链接和扩展属性的无 root Ubuntu 桌面层合并。离线构建通过不代表引导器兼容，当前候选不能视作可启动系统。

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

启动、内屏、触控、GPU、无线、音频、键盘、传感器、电源和持久安装均未在 piano 验证。
官方 Android 驱动和同 SoC 社区实现仅为候选来源，不代表主线支持已经成立。

## 贡献与许可

请阅读[贡献规范](CONTRIBUTING.md)及[来源说明](NOTICE)。
除文件另有声明外，本项目原创代码采用 [MIT](LICENSE)。复用的一加诊断工具保持 GPL-2.0-only，
小米集成工具保持 MIT；Linux、BusyBox、Ubuntu 与 AOSP 保留各自许可。
