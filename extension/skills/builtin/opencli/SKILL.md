---
api_version: v3
name: opencli
description: OpenCLI command reference for using existing browser, API, and desktop app commands. Use when the user mentions `opencli` or wants to search, read, download, post, publish, or automate supported platforms such as xiaohongshu, twitter, bilibili, zhihu, weixin, xueqiu, reddit, youtube, and more.
triggers:
- opencli
- xiaohongshu publish
- 小红书发布
- twitter post
- browser bridge
- opencli doctor
permissions:
  filesystem: workspace
  shell: true
  network: limited
---

# OpenCLI

Use the installed `opencli` directly. This skill is only for using existing commands.

It intentionally does **not** cover:

- adapter creation or modification
- `explore` / `probe`, `synthesize`, `generate`, `record`, `cascade`
- `install`, `register`, or plugin development

## Version

Local environment confirmed:

`opencli --version` -> `1.4.1`

## Default workflow

1. Discover what is available:

   `opencli list --format md`

2. Inspect a platform:

   `opencli <platform> --help`

3. Inspect a concrete command:

   `opencli <platform> <command> --help`

4. Run the command with structured output when useful:

   `-f json`, `-f md`, `-f yaml`, or `-f csv` when supported

5. If a browser-backed command fails, diagnose first:

   `opencli doctor --sessions`

## Preconditions

- Many commands are browser-backed. Keep Chrome running and logged into the target site before execution.
- Browser-backed commands require the OpenCLI Browser Bridge to already be available in Chrome.
- Some commands open tabs during execution and close them afterwards.
- For write actions such as `post`, `publish`, `reply`, `follow`, `like`, `delete`, or similar account mutations, execute only when the user clearly asked for that action.

## Discovery commands

```bash
opencli --help
opencli list --format md
opencli doctor --no-live
opencli doctor --sessions
opencli <platform> --help
opencli <platform> <command> --help
```

`opencli list --format md` is the authoritative inventory in the current environment. It includes `command`, `site`, `description`, `strategy`, `browser`, and `args`, which are useful for deciding whether a command is browser-dependent and what arguments it expects.

## Common usage patterns

### Read or search content

```bash
opencli xiaohongshu search "美食"
opencli bilibili hot --limit 10
opencli twitter search "AI"
opencli zhihu question 34816524
opencli xueqiu stock SH600519
opencli reddit search "rust" --limit 10
```

### Download or export content

```bash
opencli weixin download --url "https://mp.weixin.qq.com/..."
opencli zhihu download --url "https://zhuanlan.zhihu.com/p/..."
opencli xiaohongshu download <note-id> --output ./downloads
opencli twitter article <tweet-id>
opencli web read --url "https://example.com" --output article.md
```

### Publish or mutate account state

```bash
opencli xiaohongshu publish "正文内容" --title "标题" --images a.png,b.png --topics 话题1,话题2
opencli twitter post "Hello world"
opencli twitter reply https://x.com/... "Nice!"
opencli twitter like https://x.com/...
```

### Inspect creator or account data

```bash
opencli xiaohongshu creator-profile
opencli xiaohongshu creator-stats
opencli xiaohongshu creator-notes --limit 10
opencli bilibili me
opencli twitter profile elonmusk
```

## High-value platforms in the current install

Examples seen in local `opencli --help` / `opencli list --format md`:

- social and content: `xiaohongshu`, `twitter`, `bilibili`, `zhihu`, `reddit`, `weibo`, `youtube`, `douyin`
- articles and exports: `weixin`, `web`, `zhihu download`, `twitter article`
- finance and news: `xueqiu`, `barchart`, `yahoo-finance`, `reuters`, `bloomberg`, `bbc`
- desktop and AI apps: `codex`, `cursor`, `chatgpt`, `chatwise`, `discord-app`, `doubao-app`
- external CLIs: `gh`, `docker`

Do not hardcode this list as complete. Re-check with `opencli list --format md` when the exact platform set matters.

## Practical rules

- Prefer positional arguments exactly as shown in `--help`; many commands use positional `query`, `id`, `url`, or `text`.
- Prefer `-f json` when the result will be parsed by code or fed into another step.
- Prefer `-f md` when producing a user-facing report or saved document.
- If a command is ambiguous, inspect `--help` before running it.
- If the user asks for a platform that might exist but is not obvious, check `opencli list --format md` instead of guessing.
