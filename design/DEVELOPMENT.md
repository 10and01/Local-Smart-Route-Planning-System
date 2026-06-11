# 本地智能路线规划系统 - 开发文档

> **目标**：一周+时间完成可运行的偏好驱动路线规划系统  
> **状态**：代码骨架已完成，可直接进入开发阶段

---

## 一、项目概述

### 1.1 核心创新点

本系统区别于传统路线规划的最大特点是**偏好内嵌而非外挂**：

- 用户偏好不是对生成结果的"筛选器"，而是嵌入在POI召回、贪心选择、2-opt优化每一步决策中的"引导信号"
- 生成的路线不是"被选中"的，而是"被设计出来"的
- 每条推荐理由都有规划阶段记录的决策依据，不是事后编造的

### 1.2 已完成骨架

```
backend/
├── main.py              # FastAPI入口（已完成）
├── models/
│   └── schemas.py       # Pydantic数据模型（已完成）
├── core/
│   ├── preference.py    # 偏好量化+匹配计算（已完成）
│   └── route_engine.py  # 偏好驱动规划引擎（已完成）
├── services/
│   └── planner.py       # 业务编排服务（已完成）
└── data/
    └── loader.py        # 数据加载（已完成）

frontend/
└── index.html           # Leaflet地图页面（已完成）

data/
├── 杭州_pois_mock.json  # 20个Mock POI（已生成）
└── distance_matrix_haversine.json  # 20×20距离矩阵（已生成）
```

---

## 二、技术栈

| 层级 | 技术 | 版本 | 说明 |
|------|------|------|------|
| 后端框架 | FastAPI | ^0.100 | 异步API框架，自动OpenAPI文档 |
| 数据校验 | Pydantic | v2 | 强类型数据模型 |
| 地图前端 | Leaflet.js | 1.9.4 | 开源免费，零API Key |
| 地图底图 | OpenStreetMap | - | 免费瓦片服务 |
| 数据存储 | JSON文件 | - | 比赛期间足够，无需数据库 |
| HTTP服务 | Uvicorn | - | ASGI服务器 |
| 向量检索 | FAISS (可选) | - | 如有余力接入 |

---

## 三、按天开发计划

### Day 1：环境搭建 + 数据层验证

**目标**：项目能跑起来，API能返回数据

```bash
# 任务清单

[ ] 检查安装依赖：pip install fastapi uvicorn pydantic
[ ] 运行后端：python -m backend.main
[ ] 访问 http://localhost:8000/docs 确认API文档正常
[ ] 调用 POST /api/plan 测试返回结果
[ ] 确认data/目录下的Mock数据能正确加载
```

**验收标准**：
- `curl http://localhost:8000/` 返回 `{"status": "ok"}`
- POST /api/plan 返回包含3条路线的JSON，无报错
- 每条路线包含至少2个POI节点

**预计耗时**：3-4小时

---

### Day 2：偏好量化 + POI召回调优

**目标**：偏好解析准确，召回的POI与用户偏好高度相关

```bash
# 任务清单
[ ] 完善 preference.py 中的偏好权重映射规则
[ ] 调优 compute_preference_match() 的算法
[ ] 测试不同偏好输入下的召回结果差异
[ ] 添加日志，输出每个POI的 preference_match_score
[ ] 确保"情侣+拍照"的输入优先召回断桥、Arabica等POI
```

**关键调试点**：
```python
# 在 planner.py 的 _recall_pois() 中添加调式日志
for poi in candidates[:10]:
    print(f"{poi.name}: pre_score={poi.pre_score:.2f}, "
          f"pref_match={poi.preference_match_score:.2f}, "
          f"crowd_match={poi.crowd_match_score:.2f}")
```

**验收标准**：
- 输入 `preferences=["美食"]` 时，餐饮类POI排名靠前
- 输入 `travelers="情侣"` 时，"浪漫"标签POI得分提升
- 召回数量控制在15-25个之间

**预计耗时**：4-5小时

---

### Day 3：路线规划引擎核心调优

**目标**：生成的路线合理、无回头路、时间可行

```bash
# 任务清单
[ ] 验证贪心构造算法的POI选择逻辑
[ ] 调优 compute_poi_marginal_value() 中各项权重
[ ] 测试2-opt优化效果（对比优化前后的路线形状）
[ ] 确保时间窗约束正确工作（营业时间过滤）
[ ] 测试3套方案确实有不同的侧重（体验/效率/均衡）
```

**调优策略**：
- 如果路线总是绕远路 → 增大 `time_efficiency` 权重
- 如果路线总是去低评分POI → 增大 `experience` 权重
- 如果路线不包含用户偏好POI → 增大 `preference_match` 权重
- 如果必去点没被包含 → 检查 must_visit 的加分逻辑

**验收标准**：
- 路线中相邻POI的距离不超过5km（杭州范围内）
- 总时间不超过用户设定的 end_time - start_time
- 3套方案的POI组合有明显差异

**预计耗时**：5-6小时（核心算法，需要反复调试）

---

### Day 4：解释生成 + 前端联调

**目标**：前端页面能完整展示路线，推荐理由自然可信

```bash
# 任务清单
[ ] 打开 frontend/index.html，确认地图加载正常
[ ] 前后端联调：前端调用后端API获取路线
[ ] 调试地图上路线绘制和标记点展示
[ ] 优化推荐理由的文案质量
[ ] 调整前端UI样式（响应式、美观度）
```

**前端调试技巧**：
```javascript
// 浏览器控制台直接测试API
fetch('http://localhost:8000/api/plan', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        city: "杭州", start_time: "09:00", end_time: "18:00",
        preferences: ["美食", "拍照"], travelers: "情侣", pace: "适中"
    })
}).then(r => r.json()).then(console.log);
```

**验收标准**：
- 前端表单填写后能正确调用后端
- 地图正确显示POI标记和路线连线
- 3条方案卡片可切换，切换时地图和详情同步更新
- 推荐理由包含"因为你想...所以安排..."的句式

**预计耗时**：5-6小时

---

### Day 5：LLM意图理解接入（可选增强）

**目标**：自然语言输入能自动提取偏好权重

```bash
# 任务清单
[ ] 注册OpenAI API（或使用国内大模型API）
[ ] 实现LLM调用模块：backend/core/llm_parser.py
[ ] 设计Prompt：输入自然语言 → 输出UserPreference JSON
[ ] 接入 planner.py：有raw_query时走LLM解析，无则走规则解析
[ ] 测试："周末带女朋友去杭州玩，喜欢拍照和吃辣" → 正确提取偏好
```

**LLM Prompt模板**：
```python
LLM_PROMPT = """
你是一位本地出行规划专家。请从用户输入中提取结构化偏好信息。

用户输入：{raw_query}

请输出JSON格式：
{
  "theme_weights": {"美食":0.0~1.0, "拍照":..., ...},
  "traveler_type": "独自/情侣/亲子/朋友/家庭",
  "pace_preference": "紧凑/适中/悠闲",
  "price_sensitivity": 0.0~1.0
}
"""
```

**验收标准**：
- 自然语言输入能正确解析出主题权重
- LLM解析失败时有降级策略（fallback到规则解析）
- 响应时间 < 3秒（建议异步调用）

**预计耗时**：4-5小时

---

### Day 6：动态调整 + 真实数据接入

**目标**：支持用户修改约束后快速重算，接入真实POI数据

```bash
# 任务清单
[ ] 实现 POST /api/plan/{request_id}/adjust 接口
[ ] 测试动态调整：缩短时间、增加必去点、调整偏好权重
[ ] 申请高德地图API Key
[ ] 运行 scripts/fetch_pois_amap.py 获取真实POI数据
[ ] 对比Mock数据和真实数据的效果差异
[ ] 如有问题，回退到Mock数据保证Demo稳定
```

**验收标准**：
- 调整约束后1秒内返回新方案
- 新方案与旧方案有合理差异（不是完全重来）
- 真实POI数据能正确加载和规划

**预计耗时**：4-5小时

---

### Day 7：测试 + 优化 + 演示准备

```bash
# 任务清单
[ ] 设计3-5个典型Demo Case（不同用户场景）
[ ] 端到端测试每个Case
[ ] 性能测试：并发请求、大数据量POI
[ ] 准备演示脚本（说什么、展示什么）
[ ] 准备应对提问的话术（技术亮点、扩展性等）
```

**推荐Demo Case**：

| Case | 输入 | 预期亮点 |
|------|------|---------|
| Case 1 | 情侣+拍照+悠闲+杭州 | 路线包含断桥、Arabica、雷峰塔，上午安排拍照点 |
| Case 2 | 亲子+美食+紧凑+杭州 | 路线高效，包含楼外楼等老字号，时间紧凑 |
| Case 3 | 独自+文化+经济+杭州 | 低成本路线，免费景点优先，包含博物馆 |
| Case 4 | 朋友+娱乐+标准+杭州 | 均衡路线，购物+美食+景点兼顾 |

**验收标准**：
- 每个Case生成的路线有显著差异
- 推荐理由能准确对应用户的输入偏好
- 演示流畅，无卡顿

**预计耗时**：4-5小时

---

## 四、API接口文档

### 4.1 核心接口

#### POST /api/plan - 创建路线规划

**请求体** (`PlanRequest`)：
```json
{
  "raw_query": "周末带女朋友去杭州玩，喜欢拍照和吃辣",
  "city": "杭州",
  "date": "2024-06-15",
  "start_time": "09:00",
  "end_time": "18:00",
  "budget": 500,
  "must_visit": ["西湖断桥残雪"],
  "avoid": [],
  "travelers": "情侣",
  "preferences": ["美食", "拍照"],
  "transport_mode": "步行",
  "pace": "适中"
}
```

**响应体** (`PlanResponse`)：
```json
{
  "request_id": "abc123",
  "user_preference": {
    "theme_weights": {"美食": 0.85, "拍照": 0.92, ...},
    "traveler_type": "情侣",
    "pace_preference": "适中",
    "price_sensitivity": 0.4
  },
  "plans": [
    {
      "plan_id": "plan_a",
      "theme": "深度体验",
      "description": "专注你最感兴趣的偏好...",
      "total_time": "6小时30分",
      "total_cost": 350,
      "poi_count": 5,
      "segments": [...],
      "overall_reasoning": "..."
    }
  ],
  "candidate_pois_count": 20
}
```

#### POST /api/plan/{request_id}/adjust - 动态调整

**请求体** (`AdjustRequest`)：
```json
{
  "end_time": "16:00",
  "preference_shift": {"美食": 0.2}
}
```

**响应**：同 `PlanResponse`

---

## 五、数据模型速查

| 模型 | 用途 | 关键字段 |
|------|------|---------|
| `POI` | POI数据 | name, location(lat,lng), category, tags, rating, price, business_hours |
| `UserPreference` | 用户偏好 | theme_weights, traveler_type, pace_preference, price_sensitivity |
| `RouteConstraints` | 约束条件 | city, start_time, end_time, budget, must_visit, avoid |
| `PlanSegment` | 路线节点 | poi, arrive_time, leave_time, selection_reasons, tips |
| `RoutePlan` | 完整方案 | theme, description, segments, overall_reasoning |

---

## 六、快速开始

### 6.1 环境准备

```bash
# 1. 进入项目目录
cd d:/美团hackthon_5

# 2. 创建虚拟环境
python -m venv venv

# 3. 激活虚拟环境
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 4. 安装依赖
pip install fastapi uvicorn pydantic

# 5. 启动后端
python -m backend.main

# 6. 打开前端
# 直接用浏览器打开 frontend/index.html
# 或使用 Live Server 等工具
```

### 6.2 验证运行

```bash
# 测试健康检查
curl http://localhost:8000/

# 测试路线规划
curl -X POST http://localhost:8000/api/plan \
  -H "Content-Type: application/json" \
  -d '{"city":"杭州","start_time":"09:00","end_time":"18:00","preferences":["美食","拍照"],"travelers":"情侣","pace":"适中"}'
```

---

## 七、调试指南

### 7.1 常见问题

| 问题 | 排查方法 | 解决方案 |
|------|---------|---------|
| 后端启动失败 | 检查端口8000是否被占用 | `uvicorn backend.main:app --port 8001` |
| POI数据加载失败 | 检查data/目录下是否有JSON文件 | 运行 `python scripts/generate_mock_data.py` |
| 前端调用API失败 | 检查CORS配置和API地址 | 确认后端运行在localhost:8000 |
| 路线为空 | 检查约束是否过于严格 | 放宽时间或预算约束 |
| 路线总是绕远路 | 检查time_efficiency权重 | 在UserPreference中调大该权重 |

### 7.2 关键日志点

在以下位置添加print日志可帮助调试：

```python
# backend/services/planner.py _recall_pois()
# → 查看召回的POI及其预评分

# backend/core/route_engine.py preference_guided_greedy()
# → 查看每步贪心选择的POI和边际价值

# backend/core/route_engine.py preference_guided_two_opt()
# → 查看2-opt交换次数和效果
```

---

## 八、扩展方向（比赛后）

| 方向 | 实现思路 | 优先级 |
|------|---------|--------|
| 真实地图API | 接入高德/百度距离矩阵和路径规划 | P0 |
| 实时数据 | 接入排队API、营业状态API | P1 |
| 用户画像 | 记录历史偏好，长期学习 | P1 |
| 多人协同 | 多个用户的偏好融合 | P2 |
| 语音交互 | 接入语音识别+TTS | P2 |
| 分享功能 | 生成路线分享卡片/链接 | P2 |

---

## 九、关键文件修改记录

| 文件 | 状态 | 说明 |
|------|------|------|
| `backend/models/schemas.py` | ✅ 完成 | 所有数据模型 |
| `backend/core/preference.py` | ✅ 完成 | 偏好量化+匹配计算 |
| `backend/core/route_engine.py` | ✅ 完成 | 贪心+2-opt+多方案 |
| `backend/services/planner.py` | ✅ 完成 | 业务编排 |
| `backend/main.py` | ✅ 完成 | FastAPI入口 |
| `frontend/index.html` | ✅ 完成 | Leaflet地图页面 |
| `backend/core/llm_parser.py` | ⏳ Day 5 | LLM意图理解（可选） |
| `scripts/fetch_pois_amap.py` | ⏳ Day 6 | 真实数据获取（可选） |
