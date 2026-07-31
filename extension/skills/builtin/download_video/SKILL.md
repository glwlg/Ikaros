---
api_version: v3
name: download_video
description: "**下载视频或音频**。使用内置下载脚本抓取在线视频并返回落盘路径。"
triggers:
- 下载
- download
- save
- 保存视频
- 视频下载
- get video
policy_groups:
- media
platform_handlers: true
input_schema:
  type: object
  properties: {}
permissions:
  filesystem: workspace
  shell: true
  network: limited
entrypoint: scripts/execute.py
---

# Download Video (视频下载服务)

此技能已经自带完整下载能力，入口是 `scripts/execute.py`，底层由 `scripts/services/download_service.py` 负责下载、路径管理与大文件判断。

支持 `yt-dlp` 可解析的视频站点，包括 X、YouTube、Instagram、TikTok、Bilibili、微博和抖音。抖音、微博和 Bilibili 遇到登录限制时会向当前聊天发送二维码，扫码确认后保存加密会话并自动重试下载。

## 扫码登录

- 主动登录：`/login douyin`、`/login weibo`、`/login bilibili`。
- 自动登录：下载器识别到 Cookie、401、403 或 412 登录错误后，管理员会直接收到二维码。
- 二维码登录仅允许管理员发起；Cookie 内容不会出现在聊天或日志中。
- 浏览器 Cookie 以 Fernet 加密保存，调用 `yt-dlp` 时才临时解密到权限为 `0600` 的文件，下载结束立即删除。
- 宿主机首次启用需执行 `playwright install firefox`。Ikaros 使用无头 Firefox 打开平台登录页，不需要用户操作电脑。

## 固定存放路径

- 下载文件统一保存到 **项目根目录** 下的 `downloads/`。
- 脚本执行成功后会输出：
  - `download_dir=<绝对目录>`
  - `saved_path=<绝对文件路径>`
  - `is_too_large=true|false`
- 如果 `is_too_large=true`，文件依然保留在同一个 `downloads/` 目录里，供后续处理。

## 使用方式

通过 `bash` 在技能目录执行：

```bash
cd skills/builtin/download_video
python scripts/execute.py <url> [--format video|audio]
```

## 参数

- `<url>`
  必填，目标视频地址。
- `--format video`
  默认值，下载最佳可用视频。
- `--format audio`
  只提取音频，输出 mp3。

## 推荐 SOP

1. 用户未明确格式时，默认用 `--format video`。
2. 用户明确要 mp3、音频、只听声音时，用 `--format audio`。
3. 下载后读取脚本输出里的 `saved_path`，再告诉用户真实落盘位置。
4. **不要** 自己拼 `yt-dlp` 命令，不要自定义输出目录，不要绕过脚本。
5. 需要登录时让用户扫描 Ikaros 发出的平台二维码，不要要求用户在聊天中粘贴 Cookie。

## 示例

```bash
cd skills/builtin/download_video
python scripts/execute.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
python scripts/execute.py "https://www.bilibili.com/video/BV1xx411c7mD" --format audio
```

## 注意事项

- 路径与 cookies 文件由代码内部管理，不要自行指定 `-o` 或额外输出目录。
- 该脚本会在 stderr 输出进度，在 stdout 输出最终结果字段；总结结果时以 stdout 为准。
