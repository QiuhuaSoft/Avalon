# Avalon

由 **LLM 驱动的阿瓦隆游戏**，支持本地与机器人对战，也支持远程真人玩家一起游戏。每次运行一局，支持 **5–10 名玩家**。

## 功能

- **锤子规则（Hammer Rule）**：第 5 次组队提案会自动通过，无需投票。
  - 如果关闭锤子规则，则按照官方规则：一轮中连续 5 次组队提案被否决后，**邪恶阵营直接获胜**。
- **秘密投票**：
  - 队伍投票只有在提案结算后才会公开。
  - 任务投票永远不会离开服务器，只会公开任务失败票的**总数**。
- **游戏结束时公布身份**：
  - 当游戏决出胜负后，所有玩家的真实身份以及**湖中仙女（Lady of the Lake）**历史记录都会公开。
  - 游戏界面会显示每个玩家最终是什么角色。
  - 任务投票仍然保持秘密。
- **SQLite 事件日志**：
  - 所有游戏事件都会记录到 SQLite 中，方便进行游戏回放和调试。
- **真人玩家优先的回合机制**：
  - 系统会优先等待真人玩家进行操作。
  - 如果真人玩家没有及时操作，机器人可以自动补上。
- **支持所有核心阿瓦隆角色**：
  - 每局游戏可以自由选择需要启用的角色。
- **仅限主机的接口安全机制**：
  - 只有真正来自 `localhost` 的客户端才能访问主机专用接口。
  - 如果请求经过隧道（Tunnel）或反向代理，并且带有转发相关的 Header，则会被视为远程请求，需要提供 Token 才能访问。

## 安装

创建 Python 虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

默认使用本地 MLX 运行的 **Qwen2.5 72B 4-bit** 模型。

可以通过环境变量修改模型：

```bash
export QWEN_MODEL="mlx-community/Qwen2.5-72B-Instruct-4bit"
```

如果不想运行 LLM 推理，可以使用**启发式机器人（heuristic bot）**：

```bash
export AVALON_BOT_MODE="heuristic"
```

## 运行

执行：

```bash
python -m avalon.main
```

服务器运行地址：

```text
http://0.0.0.0:8010
```

## 测试

执行：

```bash
python -m pytest
```

测试套件覆盖：

- 阿瓦隆规则引擎
- 投票秘密机制
- 游戏结束后的角色公开
- localhost / Token 身份验证
- 湖中仙女流程
- 机器人延迟机制
- LLM 输出解析
- Prompt 构建
- 数据存储

测试使用**启发式机器人**和临时数据库运行，**不需要 LLM**。

## GUI 图形界面

打开：

```text
http://localhost:8010
```

即可进入控制界面。

真人玩家应该打开自己的玩家链接：

```text
/play?player_id=...
```

其中 `player_id` 会由控制界面生成。

**每个真人玩家应该使用自己对应的 `player_id` 链接进入游戏。**

## API

### 创建游戏

```bash
curl -X POST http://localhost:8010/game/new \
  -H 'Content-Type: application/json' \
  -d '{
    "players": [
      {"id":"p1","name":"Alice","is_bot":false},
      {"id":"p2","name":"Bot1","is_bot":true},
      {"id":"p3","name":"Bot2","is_bot":true},
      {"id":"p4","name":"Bob","is_bot":false},
      {"id":"p5","name":"Bot3","is_bot":true},
      {"id":"p6","name":"Bot4","is_bot":true},
      {"id":"p7","name":"Carol","is_bot":false}
    ],
    "hammer_auto_approve": true
  }'
```

这里创建的是一个 **7 人游戏**：

- Alice：真人
- Bot1：机器人
- Bot2：机器人
- Bob：真人
- Bot3：机器人
- Bot4：机器人
- Carol：真人

### 开始游戏

```bash
curl -X POST http://localhost:8010/game/start
```

### 提交玩家操作

例如让 `p1` 发送聊天消息：

```bash
curl -X POST http://localhost:8010/game/action \
  -H 'Content-Type: application/json' \
  -d '{"player_id":"p1","action_type":"chat","payload":{"message":"hello"}}'
```

### 获取公开游戏状态

```bash
curl http://localhost:8010/game/state
```

这个接口只能看到**所有玩家都应该知道的信息**。

### 获取玩家私有状态

```bash
curl "http://localhost:8010/game/state?player_id=p1"
```

这个接口会返回 `p1` 自己才能知道的信息，例如：

- 自己的角色
- 自己拥有的身份信息
- 根据角色能够看到的其他玩家信息

因此不同玩家使用自己的 `player_id` 获取到的状态可能不同。

## 其他说明

- 控制界面可以选择：
  - 真人玩家数量
  - 机器人数量
  - 邪恶阵营数量
  - 可选角色
- **Percival（派西维尔）**启用后，会自动启用 **Morgana（莫甘娜）**。
- **Merlin（梅林）**和 **Assassin（刺客）**始终存在。
- 其他角色会替换原本的 **Loyal Servant（忠诚的仆人）/ Minion（爪牙）**位置。
- **Lady of the Lake（湖中仙女）**默认启用，可以在控制界面关闭。
- WebSocket 流：

```text
/game/stream
```

会定期发送游戏状态快照。
