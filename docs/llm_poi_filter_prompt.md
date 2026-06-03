# LLM POI 智能筛选提示词

## 用途

将用户自然语言需求（含规则外复杂需求）直接作用于 POI 筛选，让 LLM 对每个候选 POI 输出匹配分数和推荐理由。替代传统的固定标签匹配，实现真正的语义级偏好理解。

---

## System Prompt

```
你是「旅行路线规划系统」的 POI 智能筛选专家。

你的任务：根据用户的自然语言需求，对一批候选 POI 逐一评估匹配度，输出结构化评分结果。

## 核心能力
- 理解规则外的复杂/隐性需求（如"吃辣""人少安静""适合发朋友圈""有历史感"）
- 结合出行上下文（人群、时间、预算、节奏）综合判断
- 对每个 POI 给出 0-100 的匹配分数和一句话推荐理由

## 评分原则
1. 不要只看 POI 的现有标签，要根据名称、分类、地址、评分等信息综合推断
2. 隐性需求要深入理解："吃辣"→优先川湘菜/火锅；"人少"→避开网红打卡地；"历史感"→古迹/老街/博物馆
3. 考虑 POI 的适合人群：情侣/亲子/独自/朋友/家庭/老人/商务/学生
4. 考虑时间合理性：上午适合户外拍照，中午适合用餐，晚上适合夜景/酒吧
5. 考虑地理连续性：远距离的 POI 如果没有特殊价值，适当降分

## 输出要求
- 只输出纯 JSON，不要 markdown 代码块，不要任何解释文字
- 每个 POI 必须包含：poi_id、match_score、recommendation_reason、is_recommended
- match_score 是 0-100 的整数
- is_recommended 为 true 当且仅当 match_score >= 60
```

---

## User Prompt Template

```
## 用户需求

{user_query}

## 出行上下文

- 城市：{city}
- 出行人群：{travelers}
- 偏好标签：{preferences}
- 节奏：{pace}
- 预算级别：{budget_level}
- 必去点：{must_visit}
- 避开点：{avoid}
- 交通方式：{transport_mode}

## 候选 POI 列表（共 {n} 个）

{pois_json}

## 评分任务

请对上述每个 POI，结合用户的自然语言需求和出行上下文，输出匹配分数（0-100）和推荐理由。

评分维度参考：
1. 主题匹配度（30%）：是否符合用户显性/隐性偏好
2. 人群适配度（20%）：是否适合当前出行人群
3. 体验质量（20%）：评分、口碑、特色
4. 时间合理性（15%）：当前时段是否合适
5. 地理可达性（15%）：距离、交通便利性

## 输出格式

返回 JSON 数组，每个元素对应一个 POI：
[
  {
    "poi_id": "B0FFxxxx",
    "match_score": 85,
    "recommendation_reason": "川菜老字号，麻辣口味正宗，人均消费适中，适合情侣尝鲜",
    "is_recommended": true,
    "matched_themes": ["美食", "地方特色"],
    "hidden_matched": ["吃辣", "老字号"]
  }
]
```

---

## 输入 POI 字段说明

发送给 LLM 的 POI 应包含以下精简字段（减少 token）：

```json
{
  "poi_id": "B0FFH2K2K2",
  "name": "宽窄巷子",
  "category": "风景名胜",
  "sub_category": "人文古迹",
  "address": "成都市青羊区长顺上街127号",
  "rating": 4.5,
  "price": 0,
  "tags": ["历史", "文化", "拍照", "免费"],
  "highlights": "成都遗留下来的较成规模的清朝古街道",
  "suitable_for": ["情侣", "朋友", "独自"],
  "business_hours": "全天开放",
  "location": {"lat": 30.669, "lng": 104.055}
}
```

---

## 完整示例

### 输入

```
## 用户需求

周末带女朋友去成都玩，喜欢吃辣，想拍好看的照片发小红书，不想人太多

## 出行上下文

- 城市：成都
- 出行人群：情侣
- 偏好标签：["美食", "拍照"]
- 节奏：适中
- 预算级别：标准
- 必去点：[]
- 避开点：[]
- 交通方式：步行

## 候选 POI 列表（共 5 个）

[
  {"poi_id": "P1", "name": "老码头火锅", "category": "餐饮服务", "sub_category": "火锅", "address": "武侯区", "rating": 4.7, "price": 120, "tags": ["火锅", "老字号", "排队王"], "highlights": "正宗牛油火锅，辣度可选", "suitable_for": ["朋友", "情侣"]},
  {"poi_id": "P2", "name": "锦里古街", "category": "风景名胜", "sub_category": "特色街区", "address": "武侯区", "rating": 4.2, "price": 0, "tags": ["古街", "夜景", "热闹"], "highlights": "成都著名仿古商业街", "suitable_for": ["游客", "家庭"]},
  {"poi_id": "P3", "name": "近慈寺", "category": "风景名胜", "sub_category": "寺庙道观", "address": "双流区", "rating": 4.0, "price": 0, "tags": ["安静", "佛教", "古建"], "highlights": "唐代古刹，环境清幽", "suitable_for": ["情侣", "独自", "老人"]},
  {"poi_id": "P4", "name": "建设路小吃街", "category": "餐饮服务", "sub_category": "小吃快餐", "address": "成华区", "rating": 4.3, "price": 30, "tags": ["小吃", "网红", "排队", "夜生活"], "highlights": "网红小吃聚集地", "suitable_for": ["朋友", "学生"]},
  {"poi_id": "P5", "name": "西蜀廊桥古镇", "category": "风景名胜", "sub_category": "人文古迹", "address": "金牛区", "rating": 3.8, "price": 0, "tags": ["古桥", "拍照", "人少"], "highlights": "明清古廊桥建筑群", "suitable_for": ["情侣", "摄影爱好者"]}
]
```

### 期望输出

```json
[
  {
    "poi_id": "P1",
    "match_score": 82,
    "recommendation_reason": "正宗牛油火锅满足吃辣需求，老字号品质有保障，辣度可选适合不同接受度",
    "is_recommended": true,
    "matched_themes": ["美食"],
    "hidden_matched": ["吃辣", "老字号", "品质稳定"]
  },
  {
    "poi_id": "P2",
    "match_score": 45,
    "recommendation_reason": "虽然适合拍照，但网红商业街人多嘈杂，与"不想人太多"冲突，且过于商业化",
    "is_recommended": false,
    "matched_themes": ["拍照"],
    "hidden_matched": []
  },
  {
    "poi_id": "P3",
    "match_score": 78,
    "recommendation_reason": "唐代古刹环境清幽，完全符合"人少安静"需求，古建筑拍照有质感，适合情侣慢逛",
    "is_recommended": true,
    "matched_themes": ["拍照", "文化"],
    "hidden_matched": ["人少", "安静", "古建质感", "情侣浪漫"]
  },
  {
    "poi_id": "P4",
    "match_score": 38,
    "recommendation_reason": "小吃虽多但网红属性强，排队严重，与"不想人太多"直接冲突，且环境嘈杂不适合情侣",
    "is_recommended": false,
    "matched_themes": ["美食"],
    "hidden_matched": []
  },
  {
    "poi_id": "P5",
    "match_score": 75,
    "recommendation_reason": "明清古桥建筑群拍照出片，人少清静，满足拍照+安静双重需求，适合情侣散步",
    "is_recommended": true,
    "matched_themes": ["拍照"],
    "hidden_matched": ["人少", "古建质感", "情侣散步"]
  }
]
```

---

## 接入方式

### 方案A：实时筛选（每次规划时调用）

```python
def llm_filter_pois(pois: List[Dict], user_query: str, context: Dict) -> List[Dict]:
    prompt = build_filter_prompt(pois, user_query, context)
    result = call_llm(prompt)
    # 按 match_score 排序，取前N个
    return sorted(result, key=lambda x: x["match_score"], reverse=True)
```

**优点**：最精准，能理解当前query的特殊需求
**缺点**：每次规划都调LLM，成本高、延迟大

### 方案B：离线预筛（丰富化时预计算）

在 `enrich_pois_by_llm.py` 的 LLM 丰富化阶段，同时对每个 POI 生成一组**通用匹配特征**：

```json
{
  "poi_id": "B0FFH2K2K2",
  "name": "宽窄巷子",
  "llm_matched_attributes": {
    "适合拍照": 0.9,
    "适合发朋友圈": 0.85,
    "有历史感": 0.9,
    "人多拥挤": 0.7,
    "适合情侣": 0.75,
    "适合独自": 0.8,
    "美食丰富": 0.6,
    "夜景漂亮": 0.8,
    "安静程度": 0.3,
    "性价比": 0.9
  }
}
```

规划时根据用户 query 提取关键词，与预计算的属性做向量匹配。

**优点**：规划时无需调LLM，速度快
**缺点**：无法处理非常特殊的个性化需求

### 方案C：混合策略（推荐）

1. **日常规划**：使用方案B的预计算属性 + 规则匹配，秒级响应
2. **特殊需求**：当用户输入自然语言且包含规则外需求时，使用方案A实时LLM筛选

---

## 与现有系统的集成点

| 现有模块 | 集成方式 |
|---------|---------|
| `backend/core/preference.py` | 新增 `llm_filter_pois()` 函数 |
| `backend/core/route_engine.py` | 在 `filter_candidates_by_strategy()` 前调用 LLM 筛选 |
| `scripts/enrich_pois_by_llm.py` | 方案B：丰富化时同时生成 `llm_matched_attributes` |
| `backend/models/schemas.py` | POI模型新增 `llm_matched_attributes` 字段 |
