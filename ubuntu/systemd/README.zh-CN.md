# Ubuntu udev worker 上限修复的源码输入

状态：已认证源码并准备本地 source package；**未构建/安装修改后的 systemd 或 udev 二进制，未验收真机**。

固定输入是 Ubuntu 259.5-0ubuntu3.4 与上游提交
[181a9f65](https://github.com/systemd/systemd/commit/181a9f65a7cf9059da0f2a44e2152d7636446b33)。
该提交在被终止的 worker 尚占据计数时保留事件排队，避免断言退出；保留原有队列调度机制。
补丁仅触及 src/udev/udev-manager.c，不另建服务或运行时重试器。

source.json 锁定官方归档、补丁和 changelog 输入。归档已按 Ubuntu Archive 的 InRelease 签名→Sources
校验和→DSC/orig/debian 归档校验和链确认；DSC 上传者签名未单独验证。获取输入时保留这条认证链，
不能只信任同名下载文件。本目录的补丁是公开源码，含原作者信息；GPL-2.0-or-later 文本在 LICENSES。

从公开集成仓根目录开始；在新的工作目录放置锁文件列出的三个已验证归档，再用标准 Debian 工具准备源码：

```sh
systemd_assets=$(realpath ubuntu/systemd)
cd /path/to/verified-source-archives
python3 - "$systemd_assets/source.json" <<'PY'
import hashlib, json, pathlib, sys
for item in json.load(open(sys.argv[1]))['files']:
    path = pathlib.Path(item['file'])
    assert path.stat().st_size == item['bytes']
    with path.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == item['sha256']
PY
dpkg-source -x systemd_259.5-0ubuntu3.4.dsc source
cp "$systemd_assets/worker-cap.patch" source/debian/patches/piano-udev-worker-cap.patch
printf '%s\n' piano-udev-worker-cap.patch >>source/debian/patches/series
{ cat "$systemd_assets/changelog-entry"; printf '\n'; cat source/debian/changelog; } >source/debian/changelog.new
mv source/debian/changelog.new source/debian/changelog
(cd source && dpkg-source --before-build . && dpkg-source -b .)
```

本地版本为 259.5-0ubuntu3.4+piano1、UNRELEASED；不冒充 Ubuntu 官方更新。
后续二进制仍应使用该源码的原生 Debian 构建规则，在独立 ARM64 Ubuntu 构建环境完成依赖、构建和测试。
不能将单独编译的 udevd 复制覆盖发行版文件。上游补丁可复用于其他发行版；本目录的包版本和配方属于 Ubuntu 集成层。

退出条件：所选官方 Ubuntu 源包包含等价修复，且冷启动、正常与失败关机及相称的 udev 事件回归通过后，移除本地覆盖。
源码包准备完成不等于这些条件已经满足。
