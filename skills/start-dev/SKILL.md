---
description: Launch automated dev-flow workflow. Starts scaffold → autopilot → run → summarize cycle with session-based state tracking. Use when starting a new development cycle or resuming one.
triggers:
  - "start dev"
  - "dev flow"
  - "开始开发"
  - "启动工作流"
---

# Start Dev — 启动自动化开发工作流

调用 `start-dev.py` 脚本启动 dev-flow 自动化工作流。

## 使用方式

```
/dev-flow:start-dev                    ← 从 scaffold 阶段开始
/dev-flow:start-dev --phase autopilot  ← 从指定阶段开始
/dev-flow:start-dev --phase run --retry ← 重试 run 阶段
```

## 工作流

```
scaffold → autopilot → run → (判断) → autopilot/summarize → done
```

## 执行

将 $ARGUMENTS 传递给 start-dev.py 脚本：

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/start-dev.py $ARGUMENTS
```

脚本会：

1. 启动 `claude --bg '/<phase>'` 后台 session
2. 捕获 session ID 并记录到项目的 .zac/sessions.json
3. 后续由 stop-hook.py 自动推进工作流
