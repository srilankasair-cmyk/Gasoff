# Gas-off 🔬

全球首款基于 Telegram 生态、采用心理学学术理论支撑的 **"人际关系毒性匿名诊断与沟通辅助"** AI 机器人。

---

## 🚀 一键部署

### 选项 1: Render.com（推荐 · 免费）

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

1. 点击上方按钮 → 连接 GitHub 仓库 → 填入环境变量
2. 部署完成后，设置 Telegram Webhook：

```bash
./scripts/deploy.sh webhook https://gasoff.onrender.com
```

### 选项 2: Docker

```bash
# 构建并运行
docker compose up -d

# 设置 Webhook（把 URL 换成你的域名或 IP）
./scripts/deploy.sh webhook https://your-domain.com
```

### 选项 3: Railway

```bash
# 安装 Railway CLI
brew install railway
railway login

# 部署
railway init
railway up

# 设置 Webhook
railway domains        # 查看域名
./scripts/deploy.sh webhook https://your-app.railway.app
```

### 选项 4: 本地开发 + ngrok 测试

```bash
# 终端 1: 启动服务
./scripts/deploy.sh dev

# 终端 2: 暴露公网地址
ngrok http 8000

# 终端 3: 设置 Webhook（ngrok URL）
./scripts/deploy.sh webhook https://xxxx.ngrok-free.app
```

---

## 🧪 验证部署

```bash
# 测试 Bot 连接
./scripts/deploy.sh test

# 查看 Webhook 状态
curl -s https://api.telegram.org/bot<TOKEN>/getWebhookInfo | python3 -m json.tool
```

---

## 📦 项目结构

```
Gasoff/
├── backend/
│   ├── main.py              # Flask 入口
│   ├── wsgi.py              # Gunicorn 入口
│   ├── config/settings.py   # 配置加载
│   ├── handlers/bot_handler.py  # Webhook + API
│   ├── models/schemas.py    # 数据模型
│   ├── services/deidentifier.py # 脱敏
│   ├── services/analyzer.py # DeepSeek 分析
│   └── .env                 # 环境变量
├── frontend/build/web/
│   └── index.html           # TWA 关系看板
├── Dockerfile
├── docker-compose.yml
├── render.yaml
└── scripts/deploy.sh        # 部署管理脚本
```

## 🧠 核心技术

- **戈特曼"末日四骑士"**：批评 · 轻蔑 · 防御 · 冷暴力
- **人际环状结构模型**：8 轴雷达图可视化
- **DeepSeek API**：高维语义分析
- **Regex 脱敏**：名称/电话/地址/日期本地脱敏

## 🔒 隐私

所有消息在本地完成去标识化后上传云端，不存储原始聊天记录。
