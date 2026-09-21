# AOSP boot 工具

运行 `sh tools/fetch-aosp-mkbootimg.sh`，将 AOSP mkbootimg 固定检出至 tools/local/aosp-mkbootimg。
源码 commit 为 954bc3ead5e679005fddf3484d247f2557b3c2c9，
关联 android-16.0.0_r4；入口脚本额外使用固定 SHA-256 核对。

复用了 liuqin 的固定版本和验证方式。Gitiles 动态 tar.gz 的归档字节可能变化，
因此获取改用 Git 对象身份；不通过删去校验或不断刷新归档 hash 解决。
检出有修改时拒绝改变它，避免覆盖开发者修改。

2026-09-21 已验证首次 Git 获取、内容校验、两个 Python CLI 帮助入口，以及再次使用缓存。
这只证明主机工具准备完成，不证明 piano 的 boot 格式、AVB、DTB 或 ABL 支持。

原始脚本的 MIT 声明见 [NOTICE](../NOTICE) 和 [原许可证](../LICENSES/liuqin-MIT.txt)。
