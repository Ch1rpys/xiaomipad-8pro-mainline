# AOSP boot 工具

运行 `sh tools/fetch-aosp-mkbootimg.sh`，将 AOSP mkbootimg 固定检出至 tools/local/aosp-mkbootimg。
源码 commit 为 954bc3ead5e679005fddf3484d247f2557b3c2c9，
关联 android-16.0.0_r4；入口脚本额外使用固定 SHA-256 核对。

固定版本和验证方式源自 liuqin。Gitiles 动态 tar.gz 的归档字节可能变化，
因此使用 Git 对象身份校验，不依赖动态归档的 hash。
检出有修改时拒绝改变它，避免覆盖开发者修改。

主机检查覆盖首次 Git 获取、内容校验、两个 Python CLI 帮助入口及缓存复用，
不代表 piano 的 boot 格式、AVB、DTB 或 ABL 已通过设备验证。

原始脚本的 MIT 声明见 [NOTICE](../NOTICE) 和 [原许可证](../LICENSES/liuqin-MIT.txt)。

## 持久冷启动验收

`tools/piano-cold-boot-accept.py` 复用原生显示捕获生成器；`judge` 只读主机文件，
输出每项 PASS/FAIL/UNAVAILABLE、实测值和预算，再输出 JSON。只有所有必需项 PASS 才退出 0。

```sh
python3 tools/piano-cold-boot-accept.py judge capture-early.txt capture-late.txt
PIANO_SUDO_PASSWORD_FILE=/path/to/password-file python3 tools/piano-cold-boot-accept.py run \
  --serial SERIAL --user USER --out /path/to/new-private-directory --late-seconds 200
```

`run` 经 `piano-devmode-ssh.py` 读取当前启动，立即采一次，再按设备 uptime 等到至少 200 秒采第二次；
不触发重启。sudo 密码来自 stdin 的一行或上述文件，绝不放入 argv；SSH 须已可认证。
输出目录须不存在，以 0700 创建，保存两份原始 capture、各自 stderr 和 `verdict.json`（0600）；
原始捕获包含设备身份，公开前另行脱敏。超时/SSH 失败保留部分输出并失败退出，不自动重试。

判据包含 simpledrm <1 s、切根 ≤10 s、GDM/首次 GMU ≤20 s、拷贝 ≥2000 MB/s、
HF AXI 持有、双 INTF +72±2 帧/0.5 s、模块归属、失败单元/系统状态、参考启动正对照、
单一 active user Wayland、声卡及 THP 首帧/错误。时钟/DSI/GPU 错误须为 0，
两次采样须属于同一 BOOT_ID，晚期 uptime ≥200 s；任一次失败不会被后一次通过覆盖。
声卡允许同一次启动任一采样证明，明确空声卡列表仍失败；HF AXI 只能证明采样时持有，不能证明全程无间隙。

`CAPTURE_LATE` 可省略作初判，缺失晚期窗口仍为 UNAVAILABLE、退出 1。
脱敏真实夹具及来源 hash 在 `tools/tests/fixtures/cold-boot/`：一组两次采样均仅 `failed_units` FAIL；
另一组现有读数全 PASS，但实际 uptime 41.86 s，晚期窗口 UNAVAILABLE。
完整 PASS 与切根 11 s 负例用明确标注的合成晚期读数覆盖，不改写真实夹具。
测试：`python3 tools/tests/test-cold-boot-accept.py`。本工具当前只有主机测试，`run` 尚未真机执行。

## 系统睡眠验收

`tools/piano-suspend-check.py` 在平板上以 root 运行，默认做 3 轮 RTC 30 秒 s2idle，
也可验证电源键、键盘或开盖的物理唤醒。逐轮保存实际睡眠时长、外设恢复、IRQ 与内核日志；
测试期间临时解除 `/run` 睡眠禁令，结束后清理。用法、判据及上机边界见
[系统睡眠验收](suspend-check.zh-CN.md)。当前仅离线检查通过。
