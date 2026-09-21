# Session JSONL 持久化

## 已完成

Tau 现在支持可选的追加式 JSONL 会话存储。每条运行时消息会被包装成一个 `MessageEntry`，包含：

- 唯一 `id`
- `parent_id`
- 时间戳
- 序列化后的 `AgentMessage`

`parent_id` 让条目天然形成会话树。启动 Harness 时，系统从最后一个条目作为活动叶节点，沿父节点回溯并重建模型上下文。

存储实现分为：

- `InMemorySessionStorage`：嵌入式和确定性检查使用
- `JsonlSessionStorage`：逐行追加，写入后 `flush` 并 `fsync`

Harness 只在观察到消息列表新增内容时写入存储，因此不会把流式 token 当成独立消息。工具循环中的用户消息、助手工具调用、工具结果和最终助手消息都会按顺序持久化。

## 使用方式

CLI 和 Textual TUI 都支持显式指定：

```bash
PYTHONPATH=src uv run python -m tau_coding.cli \
  --provider fake \
  --session-file /tmp/tau-session.jsonl \
  "你好"
```

再次使用同一个 `--session-file` 时，Harness 会在第一次模型请求前恢复历史。

## 当前边界

当前格式只包含 `message` 条目，尚未加入 compaction、模型切换、分支摘要和 session manager。这些功能需要在基本的追加、重放和恢复行为稳定后再添加。

检查命令：

```bash
PYTHONPATH=src uv run python examples/check_session_persistence.py
```
