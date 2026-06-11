# 🗺️ 本地智能路线规划系统

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Python-3.12-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Leaflet-199900?style=flat-square&logo=leaflet&logoColor=white" alt="Leaflet">
  <img src="https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite">
</p>

<p align="center">
  <a href="README.en.md">English</a> | 简体中文
</p>

<p align="center">
  <b>偏好驱动的智能本地路线规划 —— LLM + 经典算法 + 用户画像的长期进化</b>
</p>

---

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| 📝 **自然语言规划** | "周末带女朋友去杭州玩，喜欢拍照和吃辣" → LLM自动提取结构化偏好 |
| 🧠 **混合AI召回** | 本地BGE语义模型（零网络依赖）粗排 + LLM细排 + 规则兜底 |
| 🗺️ **手绘路线图** | 分享卡片内嵌Canvas手绘路线（发光节点 + 贝塞尔曲线 + 方向箭头） |
| 👤 **用户画像演化** | 双轨更新：行为EMA学习 + 对话LLM增量提取，含规则回退防429 |
| 🎯 **三套差异化方案** | 深度体验 / 高效省时 / 均衡推荐，物理隔离候选集保证差异 |
| 📊 **交互式画像面板** | 动态雷达图 + 关键词权重条形图 + 更新历史 + 版本溯源 |
| 🔄 **备选池增量编排** | Top-40候选池支持点击勾选，实时重算个性化路线 |
| 📤 **精美分享卡片** | Canvas生成9:16卡片，真实POI图片 + 路线图 + 统计信息 |

---

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端层                                │
│  Leaflet.js + Vanilla JS (单页应用，~3700行)                │
│  ├─ 交互式地图（高德瓦片：地图/卫星/简图）                  │
│  ├─ 三套方案卡片 + 时间线详情 + 方案对比                    │
│  ├─ 备选池面板（Top-40候选POI，点击→地图定位）             │
│  ├─ 画像雷达面板（动态关键词 + 更新历史）                   │
│  ├─ 分享卡片生成器（Canvas手绘路线 + 真实图片）             │
│  └─ 语音输入 + 自定义偏好标签                               │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / CORS
┌──────────────────────────▼──────────────────────────────────┐
│                        API 层                                │
│  FastAPI + Pydantic v2 + Uvicorn                            │
│  ├─ /api/plan         路线规划（支持匿名/登录）              │
│  ├─ /api/plan/{id}/adjust   动态调整 / 增量编排              │
│  ├─ /api/user/profile       用户画像 GET/PUT                 │
│  ├─ /api/user/select-plan   方案选择（触发画像演化）         │
│  ├─ /api/proxy-image        图片代理（绕过CORS）             │
│  └─ /api/cities/{city}/init 城市数据异步构建                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                       业务引擎层                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ LLM Parser  │  │ HybridFilter│  │ SemanticMatcher     │  │
│  │ 意图解析    │  │ 规则+Embedding│  │ BGE-small-zh-v1.5   │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ PolicyGen   │  │ RouteEngine │  │ Personalization     │  │
│  │ 策略生成    │  │ 贪心+2-opt  │  │ 画像双轨演化        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ LLMReranker │  │ LLMReasoner │  │ Evaluator           │  │
│  │ POI重排序   │  │ 推荐理由    │  │ 五维自动评估        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                        数据层                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ SQLite      │  │ JSON POI    │  │ Distance Matrix     │  │
│  │ 用户/历史/  │  │ 城市数据    │  │ OSRM/Haversine      │  │
│  │ 画像版本    │  │             │  │                     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 本地模型: data/models/bge-small-zh-v1.5/ (184MB)    │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 环境要求

- Python 3.12+
- LLM API Key（OpenAI-compatible，如 MiniMax / Kimi）— 用于自然语言解析
- AMap Key — 用于动态抓取城市POI（可选，已有内置数据）

### 安装与启动

```bash
# 1. 克隆项目
git clone <repo-url>
cd local-route-planner

# 2. 创建虚拟环境
python -m venv venv

# 3. 激活（Windows）
venv\Scripts\activate

# 4. 安装依赖
pip install -r requirements.txt

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY 和 AMAP_KEY

# 6. 启动后端
python -m backend.main

# 7. 启动前端（新终端）
cd frontend
python -m http.server 8080
```

访问 http://localhost:8080 打开前端，http://localhost:8000/docs 查看API文档。

---

## 📁 项目结构

```
├── backend/
│   ├── main.py                 # FastAPI 入口
│   ├── core/                   # 核心引擎
│   │   ├── route_engine.py     # 路线规划（贪心 + 2-opt）
│   │   ├── hybrid_filter.py    # 混合POI召回（规则 + BGE + LLM）
│   │   ├── semantic_matcher.py # BGE语义匹配（本地模型）
│   │   ├── llm_parser.py       # LLM意图解析
│   │   ├── llm_reranker.py     # LLM POI重排序
│   │   ├── llm_reasoner.py     # 推荐理由生成
│   │   ├── personalization.py  # 用户画像引擎（双轨演化）
│   │   ├── policy_generator.py # 规划策略生成
│   │   └── evaluator.py        # 方案评估器
│   ├── services/
│   │   ├── planner.py          # 业务编排服务
│   │   └── auth.py             # JWT认证服务
│   ├── models/
│   │   ├── schemas.py          # 核心数据模型
│   │   └── auth_schemas.py     # 认证模型
│   ├── data/
│   │   ├── loader.py           # 数据加载
│   │   └── city_builder.py     # 城市数据构建
│   └── db/
│       ├── database.py         # SQLite连接
│       └── models.py           # DAO层
├── frontend/
│   └── index.html              # 单页应用（Leaflet + Canvas）
├── scripts/                    # 数据采集与处理脚本
│   ├── fetch_pois_amap.py      # 高德POI采集
│   ├── enrich_pois_by_llm.py   # LLM数据富化
│   ├── compute_distance_matrix.py
│   └── build_real_pois_pipeline.py
├── data/
│   ├── app.db                  # SQLite生产数据库
│   ├── models/                 # BGE嵌入模型（内置）
│   ├── *_pois.json             # 各城市POI数据
│   └── distance_matrix_*.json  # 距离矩阵
├── tests/                      # 单元测试与E2E测试
└── docs/                       # 设计文档与Prompt模板
```

---

## 🔧 核心技术

### 路线生成完整流程

```
用户输入（自然语言 / 偏好标签 / 约束条件）
    │
    ├──→ Step 1: 偏好解析
    │       ├── LLM Parser: raw_query → 结构化偏好（主题权重、人群、节奏、预算敏感度）
    │       └── Fallback: 规则解析（固定标签映射为权重字典）
    │
    ├──→ Step 2: 历史画像融合
    │       ├── 加载用户长期画像（SQLite: theme_weights, traveler_type, pace, 等）
    │       ├── 当前偏好 ⊗ 历史偏好 = 融合偏好（EMA加权，历史权重随规划次数衰减）
    │       └── 画像描述拼接到 raw_query（为LLM提供长期上下文）
    │
    ├──→ Step 3: POI数据召回
    │       ├── 加载城市缓存POI（JSON: name, location, category, tags, rating, price, photos, business_hours）
    │       ├── 动态抓取补充（高德API按用户query搜索 + LLM地标评分，去重后并入候选池）
    │       └── 质量过滤（排除非旅游类别、评分过低、距离过远的POI）
    │
    ├──→ Step 4: 混合POI筛选（Query复杂度决定路径）
    │       │
    │       ├── SIMPLE路径（无自然语言）
    │       │   └── 纯规则硬约束：营业时间过滤 + 距离阈值 + 必去/避开 + 类别配额
    │       │
    │       ├── HYBRID路径（简单自然语言）
    │       │   ├── 规则硬约束过滤
    │       │   └── BGE语义粗排：融合偏好关键词 ↔ POI（name+category+tags）的512维余弦相似度
    │       │
    │       └── COMPLEX路径（丰富自然语言）
    │           ├── 规则硬约束过滤
    │           ├── BGE语义粗排（Top-50）
    │           └── LLM细排（Top-20）：结合UGC情感（"适合拍照""人少"）、人群契合度、POI协同效应
    │
    ├──→ Step 5: 策略生成（PolicyGenerator）
    │       └── 基于融合偏好生成 3套 PlanningPolicy（评分权重各不相同）
    │           ├── 深度体验: preference_match 0.6 + experience 0.25 + time_efficiency 0.15
    │           ├── 高效省时: preference_match 0.2 + experience 0.2 + time_efficiency 0.6
    │           └── 均衡推荐: preference_match 0.35 + experience 0.3 + time_efficiency 0.35
    │
    ├──→ Step 6: 路线规划 × 3次（RouteEngine）
    │       ├── 贪心构造：按策略权重逐步选择边际价值最高POI（评分×偏好匹配×时间效率×距离惩罚）
    │       ├── 强制餐饮插入：午餐（11:30-13:30）/晚餐（17:00-19:00）时段自动插入餐饮POI
    │       ├── 营业时间过滤：确保到达时间在 open_hours 内
    │       ├── 2-opt优化：局部交换减少回头路，优化时间成本
    │       └── 预算约束：总花费不超过用户预算
    │
    ├──→ Step 7: LLM推荐理由生成
    │       ├── 整体理由：解释路线设计理念（"因为你喜欢拍照，所以上午安排西湖..."）
    │       └── 逐POI理由：每个节点的选择依据（评分、偏好契合、独特体验）
    │
    └──→ Step 8: 画像双轨更新（异步，不阻塞响应）
            ├── Track 1（行为EMA）: 方案选择/POI like/dislike → 推断主题偏好 → EMA平滑 → 写入SQLite
            └── Track 2（对话增量）: raw_query → LLM提取偏好变化 → 若LLM 429则规则回退提取关键词 → 写入SQLite + 版本历史
```

### 用户历史偏好如何融入

- **冷启动**：注册时可选 `profile_text`，LLM解析为初始画像；或直接填写画像描述
- **每次规划**：`fuse_preferences(current_pref, historical_pref)` 将当前请求偏好与长期画像加权融合，历史权重随 `total_plans_generated` 增加而衰减（新用户 gamma=0.5，老用户 gamma=0.1）
- **画像描述自动注入**：用户的长期画像描述（如"我喜欢摄影和小众景点"）自动拼接到 `raw_query` 头部，让LLM在解析本次请求时知道用户的长期偏好

### POI数据与服务如何结合

| 数据来源 | 内容 | 使用方式 |
|----------|------|----------|
| **高德API采集** | name, location(GCJ-02), category, rating, photos | 基础POI池，直接用于召回和展示 |
| **LLM富化** | tags, suitable_for, tips, business_hours, price | 丰富POI属性，用于语义匹配和推荐理由 |
| **动态抓取** | 按用户query实时搜索的精准POI | 补充基础池中缺失的POI，扩展候选集 |
| **用户评价语料** | UGC标签（"适合拍照""性价比高"） | COMPLEX路径的LLM细排阶段作为上下文输入，影响重排序和推荐理由 |
| **距离矩阵** | OSRM步行 / Haversine | 路线规划中计算POI间距离和时间成本 |

### 三套召回路径 vs 三套方案的区别

| | **三套召回路径**（SIMPLE/HYBRID/COMPLEX） | **三套差异化方案**（深度体验/高效省时/均衡推荐） |
|--|-------------------------------------------|--------------------------------------------------|
| **阶段** | POI筛选阶段 | 路线规划阶段 |
| **决定因素** | 用户输入的复杂度（有无自然语言） | 用户偏好类型（休闲/紧凑/均衡） |
| **输出** | 1个候选POI池（Top-40~50） | 3条不同路线 |
| **代码位置** | `hybrid_filter.py` | `policy_generator.py` + `route_engine.py` |

**关键**：无论走哪条召回路径，最终都生成3套方案。召回路径决定"候选POI质量"，方案策略决定"路线设计哲学"。

### 分享卡片生成

- **路线图**：Canvas手绘（网格背景 + 贝塞尔曲线 + 发光节点 + 方向箭头）
- **真实图片**：通过 `/api/proxy-image` 后端代理下载高德POI照片，转base64绘制到canvas
- **动态高度**：根据POI数量自动计算canvas高度，无空白

---

## 📸 项目效果

### 1. 分享卡片
真实POI图片 + Canvas手绘路线图 + 动态高度，生成9:16分享卡片。

![分享卡片](docs/screenshots/share-card.png)

### 2. 前端主界面
左侧偏好表单（自然语言 + 标签 + 约束），右侧Leaflet高德地图，支持地图/卫星/简图切换。

![前端主界面](docs/screenshots/main-interface.png)

### 3. 用户画像面板
动态雷达图展示偏好关键词，条形图展示权重，记录每次画像更新的来源和历史。

![用户画像面板](docs/screenshots/profile-panel.png)

### 4. POI详情面板
真实照片、LLM生成的推荐理由、实用信息（地址/电话/营业时间）、用户反馈（喜欢/不喜欢）。

![POI详情面板](docs/screenshots/poi-detail.png)

### 5. 三套方案对比
深度体验 / 高效省时 / 均衡推荐 三套方案并排展示，地图上同步绘制对应路线。

![三套方案对比](docs/screenshots/plan-comparison.png)
![两两对比](docs/screenshots/plan-comparison1.png)
---

## 🌐 API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 健康检查 |
| `POST` | `/api/auth/register` | 用户注册（可选画像文本初始化） |
| `POST` | `/api/auth/login` | 用户登录 |
| `GET` | `/api/user/profile` | 获取用户画像（含theme_weights雷达数据） |
| `PUT` | `/api/user/profile` | 更新画像（描述/权重/标量字段） |
| `GET` | `/api/user/profile/history` | 画像版本历史 |
| `POST` | `/api/plan` | 创建路线规划 |
| `GET` | `/api/plan/{id}` | 获取规划结果 |
| `POST` | `/api/plan/{id}/adjust` | 动态调整（replan / arrange） |
| `GET` | `/api/plan/{id}/candidates` | 获取Top-40候选池 |
| `POST` | `/api/user/select-plan` | 记录方案选择（触发画像演化） |
| `POST` | `/api/user/feedback` | POI like/dislike反馈 |
| `GET` | `/api/proxy-image?url=` | 图片代理（供canvas绕过CORS） |
| `GET` | `/api/cities` | 支持城市列表 |
| `POST` | `/api/cities/{city}/init` | 异步构建城市数据 |

---

## 🗺️ 支持城市

已内置真实POI数据（高德采集 + LLM富化）：

- 杭州（219个POI）
- 北京
- 上海
- 广州
- 成都
- 南京

可通过 `POST /api/cities/{city}/init` 为新增城市构建数据。

---

## 🧪 测试

```bash
# 混合过滤器单元测试
python tests/test_hybrid_filter.py

# API端到端测试
python tests/test_hybrid_filter_api.py

# 全量评估（生成 eval_report）
python scripts/run_full_eval.py

# 压力测试
locust -f tests/locustfile.py
```

---

## ⚠️ 已知限制

- **LLM API 429**：MiniMax TPM限制可能导致规划超时（已添加规则回退兜底）
- **高德图片CORS**：POI照片不支持跨域，通过后端代理解决
- **OSRM距离矩阵**：城市范围大时OSRM foot模式距离不够精确

---

## 📄 许可证

MIT © 2025

> 🏆 10WTW01's 美团 AI Hackathon参赛项目，探索 LLM + 经典算法 + 用户画像结合的新一代本地生活服务体验。
