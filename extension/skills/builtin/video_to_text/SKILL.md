---
api_version: v3
name: video_to_text
description: "**把本地视频转成 Markdown 文本工件**。输出时间序画面描述、OCR 和分段音轨转写，不直接给最终结论。"
triggers:
- 视频转文本
- video to text
- video transcript
- 提取视频文本
- video markdown
platform_handlers: true
input_schema:
  type: object
  properties:
    path:
      type: string
      description: Absolute or workspace-relative local video path.
permissions:
  filesystem: workspace
  shell: true
  network: limited
entrypoint: scripts/execute.py
---

# Video To Text

这个 skill 的职责只有一件事：把视频转成尽量无损的 Markdown 文本工件。

启用前提：必须配置 `VIDEO_TO_TEXT_WHISPER_ENDPOINT`，否则不会注册视频拦截器。

## 原则

- 不负责下载视频；在线视频先交给 `download_video`。
- 不直接输出“视频总结”或最终结论。
- 主产物是 Markdown 文件，供后续继续读取、追问和总结。

## 用法

```bash
cd extension/skills/builtin/video_to_text
python scripts/execute.py --path /abs/path/to/video.mp4
```

## 输出

- 工件默认写到 `downloads/transcripts/`
- 内容包含：
  - 视频元数据
  - 时间序关键帧描述
  - 画面文字 OCR
  - 分段音轨转写
  - 提取诊断
