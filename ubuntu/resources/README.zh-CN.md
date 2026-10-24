# Resources：Ubuntu 回移包

固定 Ubuntu 源包 `1.10.2-0ubuntu3.1`，构建版本 `1.10.2-0ubuntu3.1+piano1`。
[source.json](source.json) 列出 snapshot URL、大小和 SHA256；按这些固定输入下载并校验。
通用实现只维护于 [apps/resources](../../apps/resources/README.md)；本目录的
`backport.patch` 将那四个补丁适配到 Ubuntu 的旧目录布局和 API，保留原有 Ubuntu 补丁。
补丁按 Resources 的 GPL-3.0-or-later 分发，见 [COPYING](COPYING)，不适用集成仓 MIT。

从集成仓根目录设置 `repo=$(pwd)`，进入已下载三份源包文件的构建目录：

```sh
dpkg-source -x resources_1.10.2-0ubuntu3.1.dsc resources
mkdir telemetry-patches
cp "$repo"/apps/resources/patches/*.patch telemetry-patches/
(cd telemetry-patches && patch -p1 < "$repo/ubuntu/resources/backport.patch")
cp telemetry-patches/*.patch resources/debian/patches/
for file in telemetry-patches/*.patch; do
    basename "$file" >> resources/debian/patches/series
done
{ cat "$repo/ubuntu/resources/changelog-entry"; echo; cat resources/debian/changelog; } > changelog
mv changelog resources/debian/changelog
(cd resources && QUILT_PATCHES=debian/patches quilt push -a)
(cd resources && dpkg-buildpackage -b -us -uc)
```

使用 Ubuntu ARM64 构建环境和源包声明的 Build-Depends；Debian 原有 Meson/Cargo
流程生成应用、辅助程序、翻译、桌面资源及 schema。需要交叉编译时按 Debian 的
Meson cross-file、Cargo target/linker 与目标 sysroot 配置，不改变补丁实现。
二进制分发应同时保留本目录、通用补丁、原始源包和由它们生成的对应源包。

`piano-ubuntu-desktop` 精确依赖这个版本，将 `piano-resources` 安装为 APT preferences
conffile；精确版本优先级 1001，其他 Resources 版本为 -1，安装的本地 deb 也受保护。
它也会阻止 Resources 安全更新，因此 Ubuntu 更新时须回移修复、重建并同步更新
源包锁、桌面精确依赖和 pin。其他 Ubuntu 包的更新不受影响。
构建桌面包：`tools/build-device-debs.py --desktop-only --version 0.6.2 --output OUTPUT`。
根镜像和发布打包时将 Resources deb 与设备包一起显式传入现有 `--deb` 流程。
Ubuntu 含等价功能后，验证遥测并同时删除本地补丁、精确依赖和 pin。
