# 🗺️ 本地智能路线规划系统

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Python-3.12-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Leaflet-199900?style=flat-square&logo=leaflet&logoColor=white" alt="Leaflet">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
</p>

<p align="center">
  <b>偏好驱动的智能本地路线规划 —— 你的行程，不是被筛选出来的，而是被设计出来的</b>
</p>

---

## ✨ 核心创新

传统路线规划将用户偏好当作**结果筛选器**，先生成路线再过滤。本系统将偏好内嵌为**决策引导信号**，在 POI 召回、贪心选择、2-opt 优化的每一步中持续发挥作用：

- 🎯 **偏好内嵌**：主题权重直接参与路线构造的每一步决策
- 🧠 **LLM 意图理解**：自然语言输入自动提取结构化偏好
- 🗣️ **可解释规划**：每条推荐理由都有规划阶段的决策依据，非事后编造
- 🔄 **动态调整**：支持在已有方案基础上快速重算，响应约束变化

---

## 🚀 功能特性

| 特性 | 说明 |
|------|------|
| 📝 自然语言输入 | "周末带女朋友去杭州玩，喜欢拍照和吃辣" → 自动提取偏好权重 |
| 🗺️ 多城市支持 | 已覆盖杭州、北京、上海、广州、成都、南京等城市的真实 POI 数据 |
| 🧮 三套方案生成 | 深度体验 / 效率优先 / 均衡兼顾，满足不同场景需求 |
| ⏰ 智能时间规划 | 自动考虑营业时间、游览时长、交通时间，避免时间冲突 |
| 🚫 必去&避开 | 支持指定必去景点和排除不感兴趣的地点 |
| 🔄 方案动态调整 | 修改时间、预算或偏好后 1 秒内获得新方案 |
| 👤 用户画像 & 历史 | 注册登录后记录历史偏好，长期学习优化推荐 |
| 📊 可视化前端 | 基于 Leaflet 的交互式地图，路线、标记、方案卡片一目了然 |

---

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端层                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Leaflet.js  +  Vanilla JS  +  CSS3                 │    │
│  │  交互式地图 · 方案卡片 · 表单输入 · 动态渲染          │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / CORS
┌──────────────────────────▼──────────────────────────────────┐
│                        API 层                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  FastAPI  +  Pydantic v2  +  Uvicorn                │    │
│  │  /api/plan  ·  /api/plan/{id}/adjust  ·  /api/auth  │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                       业务引擎层                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ LLM Parser  │  │ Query       │  │ Hybrid POI Filter   │  │
│  │ 意图理解    │  │ Analyzer    │  │ 规则+模型混合召回    │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Policy      │  │ Route       │  │ LLM Reasoner        │  │
│  │ Generator   │  │ Engine      │  │ 推荐理由生成        │  │
│  │ 策略生成    │  │ 贪心+2-opt  │  │                     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                        数据层                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ SQLite      │  │ JSON POI    │  │ Distance Matrix     │  │
│  │ (用户/历史) │  │ (城市数据)  │  │ (OSRM/Haversine)    │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 📦 快速开始

### 环境要求

- Python 3.12+
- （可选）高德地图 API Key — 用于获取真实 POI 数据
- （可选）LLM API Key — 用于自然语言意图理解

### 安装与启动

```bash
# 1. 克隆项目
git clone <repo-url>
cd local-route-planner

# 2. 创建虚拟环境
python -m venv venv

# 3. 激活虚拟环境
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 4. 安装依赖
pip install fastapi uvicorn pydantic requests

# 5. 配置环境变量（可选）
cp .env.example .env
# 编辑 .env，填入你的 LLM API Key 和 高德 API Key

# 6. 启动后端服务
python -m backend.main

# 7. 打开前端
# 直接用浏览器打开 frontend/index.html
# 或使用 Live Server 等工具
```

### 验证运行

```bash
# 健康检查
curl http://localhost:8000/

# 路线规划测试
curl -X POST http://localhost:8000/api/plan \
  -H "Content-Type: application/json" \
  -d '{
    "city": "杭州",
    "start_time": "09:00",
    "end_time": "18:00",
    "preferences": ["美食", "拍照"],
    "travelers": "情侣",
    "pace": "适中"
  }'
```

访问 http://localhost:8000/docs 查看完整的交互式 API 文档。

---

## 🌐 API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 健康检查 |
| `POST` | `/api/auth/register` | 用户注册 |
| `POST` | `/api/auth/login` | 用户登录 |
| `GET` | `/api/auth/profile` | 获取用户画像 |
| `POST` | `/api/plan` | 创建路线规划 |
| `POST` | `/api/plan/{request_id}/adjust` | 动态调整方案 |
| `POST` | `/api/plan/{request_id}/feedback` | 提交方案反馈 |
| `GET` | `/api/cities` | 获取支持的城市列表 |
| `POST` | `/api/cities/{city}/build` | 构建城市数据 |

---

## 📁 项目结构

```
.
├── backend/
│   ├── main.py                 # FastAPI 入口
│   ├── models/
│   │   ├── schemas.py          # 核心数据模型 (Pydantic)
│   │   └── auth_schemas.py     # 认证相关模型
│   ├── core/
│   │   ├── route_engine.py     # 路线规划引擎 (贪心 + 2-opt)
│   │   ├── preference.py       # 偏好量化与匹配
│   │   ├── llm_parser.py       # LLM 意图解析
│   │   ├── llm_reasoner.py     # LLM 推荐理由生成
│   │   ├── hybrid_filter.py    # 混合 POI 召回过滤
│   │   ├── policy_generator.py # 规划策略生成
│   │   ├── personalization.py  # 用户个性化引擎
│   │   └── evaluator.py        # 方案评估器
│   ├── services/
│   │   ├── planner.py          # 业务编排服务
│   │   └── auth.py             # 认证服务
│   ├── data/
│   │   ├── loader.py           # 数据加载
│   │   └── city_builder.py     # 城市数据构建
│   └── db/
│       ├── database.py         # SQLite 连接管理
│       └── models.py           # DAO 层
├── frontend/
│   └── index.html              # Leaflet 地图前端 (单页应用)
├── scripts/
│   ├── fetch_pois_amap.py      # 高德 POI 数据采集
│   ├── enrich_pois_by_llm.py   # LLM POI 数据富化
│   ├── compute_distance_matrix.py
│   ├── generate_mock_data.py
│   └── run_full_eval.py        # 全量评估脚本
├── data/                       # 城市 POI 数据 & 距离矩阵
├── docs/                       # 设计文档与 Prompt 模板
├── tests/                      # 单元测试与 E2E 测试
└── DEVELOPMENT.md              # 详细开发文档
```

---

## 🛠️ 核心技术实现

### 偏好驱动的路线规划

```python
# 1. 偏好量化 → 结构化权重
user_pref = parse_preference_from_request(request)
# e.g. {"美食": 0.85, "拍照": 0.92, "文化": 0.30}

# 2. POI 召回 + 混合过滤
candidates = hybrid_filter.recall(city, user_pref, constraints)

# 3. 策略生成 → 三套方案配置
policies = generate_planning_policy(user_pref, strategy_types)

# 4. 偏好引导的贪心构造 + 2-opt 优化
for policy in policies:
    route = preference_guided_greedy(candidates, policy)
    route = preference_guided_two_opt(route, policy)

# 5. LLM 生成可解释推荐理由
apply_llm_reasons_to_plan(route, user_pref)
```

### 多方案差异化策略

| 方案 | 策略侧重 | 适用场景 |
|------|---------|---------|
| 🟣 **深度体验** | 偏好匹配 + 体验质量权重高 | 时间充裕，想深度游玩 |
| 🟢 **效率优先** | 时间效率 + 紧凑行程权重高 | 时间紧张，想多打卡 |
| 🟡 **均衡兼顾** | 三者均衡，考虑综合评分 | 通用场景，不确定偏好 |

---

## 🗺️ 支持城市

本项目已内置以下城市的真实 POI 数据（通过高德地图 API 采集并经过 LLM 富化处理）：

- 杭州
- 北京
- 上海
- 广州
- 成都
- 南京

可通过 `POST /api/cities/{city}/build` 接口为新增城市构建数据。

---

## 🧪 测试与评估

```bash
# 运行混合过滤器测试
python tests/test_hybrid_filter.py

# 运行 API 测试
python tests/test_hybrid_filter_api.py

# 运行全量评估（生成 eval_report）
python scripts/run_full_eval.py

# 压力测试
locust -f tests/locustfile.py
```

---

## 📋 开发路线图

- [x] 偏好驱动的路线规划核心引擎
- [x] 三套差异化方案生成
- [x] 自然语言 LLM 意图解析
- [x] 可解释推荐理由生成
- [x] 混合 POI 召回过滤（规则 + Embedding）
- [x] 用户画像与长期偏好学习
- [x] 多城市真实 POI 数据接入
- [x] 交互式 Leaflet 地图前端
- [ ] 接入高德/百度实时路径规划
- [ ] 实时排队与营业状态数据
- [ ] 多人协同偏好融合
- [ ] 语音交互

---

## 🤝 贡献指南

欢迎 Issue 和 PR！

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交改动 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开一个 Pull Request

---

## 📄 许可证

[MIT](LICENSE) © 2025

---

> 🏆 本项目诞生于美团 AI Hackathon，旨在探索 LLM 与经典算法结合的新一代本地生活服务体验。
