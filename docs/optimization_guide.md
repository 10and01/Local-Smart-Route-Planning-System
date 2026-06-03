# 路线规划系统优化开发指南（Handoff Document）

> **用途**：本文档供后续开发对话中的AI代理直接参考，包含完整的技术方案、代码改动清单、测评方法和通过标准。
> **项目路径**：`d:/美团hackthon_5`
> **技术栈**：FastAPI + Python 3.12 + SQLite + 高德Web API

---

## 一、项目现状与四个优化方向总览

### 1.1 现有架构

```
backend/
├── main.py                     # FastAPI入口，/api/plan /api/plan/{id}/adjust
├── services/planner.py         # RoutePlannerService，业务编排主流程
├── core/
│   ├── route_engine.py         # 核心路线算法（贪心+2-opt+强制差异化）
│   ├── preference.py           # 偏好解析与POI匹配计算
│   ├── personalization.py      # 用户画像加载/融合/演化
│   ├── llm_parser.py           # LLM意图解析（raw_query → UserPreference）
│   ├── llm_reasoner.py         # LLM推荐理由生成
│   ├── llm_filter.py           # LLM语义POI筛选
│   ├── hybrid_filter.py        # 混合POI筛选器
│   ├── dynamic_fetch_planner.py # 动态POI抓取（高德搜索API）
│   └── config.py               # 配置（LLM_KEY / AMAP_KEY / MODEL_NAME）
├── data/
│   ├── direction_api.py        # 交通路径API（当前用v3/direction）
│   └── loader.py               # POI数据加载、OSRM距离矩阵
├── db/models.py                # SQLite DAO层（含DirectionCacheDAO）
└── models/schemas.py           # Pydantic模型（POI / UserPreference / RoutePlan / PlanSegment）
```

### 1.2 四个优化方向

| # | 方向 | 当前问题 | 目标 | 核心改动文件 |
|---|------|---------|------|------------|
| 1 | **动态抓取性能** | 串行执行4查询×3页，每次timeout=10秒，无缓存，总耗时40-150秒 | 并发3 worker + 缓存，降到10-15秒 | `dynamic_fetch_planner.py`, `db/models.py` |
| 2 | **交通API升级** | 使用高德v3/direction，有INSUFFICIENT_PRIVILEGES报错 | 升级到v5/direction（路线规划2.0），支持驾车/公交/步行/骑行/电动车 | `direction_api.py` |
| 3 | **个性化评测** | 个性化算法存在但不可量化验证 | 离线模拟验证框架：构造10-20个模拟画像，对比有/无画像的差异度 | `personalization.py`（新增评测模块）, `llm_parser.py` |
| 4 | **UGC架构先行** | ugc_keywords是LLM模拟的假数据，未参与评分 | 扩展POI模型支持UGC评分字段，实现UGC参与路线评分的完整逻辑，数据先用LLM模拟 | `models/schemas.py`, `route_engine.py`, `scripts/enrich_pois_by_llm.py` |

---

## 二、阶段1：动态抓取性能优化

### 2.1 现状诊断

**瓶颈代码位置**：`backend/core/dynamic_fetch_planner.py:284-325`

```python
def execute_dynamic_fetch(queries, city, pages_per_query=3):
    all_results = []
    for i, q in enumerate(queries):          # ← 串行循环
        if i > 0:
            time.sleep(0.5)                  # ← 查询间延迟0.5秒
        pois = _fetch_single_query(...)      # ← 内部又循环3页
        # 每页调用 _search_poi_keywords() → 高德API timeout=10秒
```

**耗时估算**：
- 4查询 × 3页 × 1-3秒(API往返) + 4×0.5秒(查询间隔) + 12×0.2秒(页间隔) ≈ **15-40秒**
- 如果API响应慢（接近timeout=10秒）：4×3×10 = **120秒**

**无缓存**：每次规划请求都重新调用高德API。

### 2.2 技术方案

#### 改动1：并发化（`dynamic_fetch_planner.py`）

**原则**：用户高德Key并发上限为 **3**，所以 `max_workers=3`。

**实现**：
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def execute_dynamic_fetch(queries, city, pages_per_query=3):
    if not queries:
        return []

    def _fetch_one(q):
        try:
            pois = _fetch_single_query(
                city=city,
                keywords=q["keywords"],
                types=q.get("types", ""),
                pages=pages_per_query
            )
            print(f"[DynamicFetch] 查询 '{q['keywords']}' 获取 {len(pois)} 条POI")
            return pois
        except Exception as e:
            print(f"[DynamicFetch] 查询 '{q['keywords']}' 执行失败: {e}")
            return []

    all_results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_fetch_one, q): q for q in queries}
        for future in as_completed(futures):
            all_results.extend(future.result())

    return all_results
```

**注意**：
- 不要并发行内分页（`_fetch_single_query` 内部仍串行），因为分页有依赖（上一页不足25条则停止）
- 4个查询交给3个worker，最坏情况下有一个查询等待，但仍然远快于串行

#### 改动2：新增动态抓取缓存（`db/models.py` + `dynamic_fetch_planner.py`）

**新增表结构**（在 `db/models.py` 的 `CREATE_TABLES_SQL` 中追加）：

```sql
-- 动态抓取结果缓存
CREATE TABLE IF NOT EXISTS dynamic_fetch_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL,
    query_hash TEXT NOT NULL,  -- hash(city + keywords + types)
    results_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(city, query_hash)
);
```

**新增DAO类**：

```python
class DynamicFetchCacheDAO(BaseDAO):
    @staticmethod
    def get(city: str, query_hash: str) -> Optional[str]:
        with get_db() as conn:
            row = conn.execute(
                """SELECT results_json FROM dynamic_fetch_cache
                   WHERE city = ? AND query_hash = ?
                   AND created_at > datetime('now', '-1 day')""",
                (city, query_hash)
            ).fetchone()
            return row["results_json"] if row else None

    @staticmethod
    def save(city: str, query_hash: str, results_json: str):
        with get_db() as conn:
            conn.execute(
                """INSERT INTO dynamic_fetch_cache (city, query_hash, results_json)
                   VALUES (?, ?, ?)
                   ON CONFLICT(city, query_hash) DO UPDATE SET
                   results_json = excluded.results_json,
                   created_at = CURRENT_TIMESTAMP""",
                (city, query_hash, results_json)
            )
```

**在 `fetch_city_pois_dynamic` 中使用缓存**：

```python
import hashlib

def fetch_city_pois_dynamic(city, user_query, avoid, max_pois=80, pages_per_query=3):
    queries = generate_search_queries(user_query or "", city, avoid, max_queries=4)

    # 尝试缓存
    all_cached = []
    uncached_queries = []
    for q in queries:
        query_hash = hashlib.md5(f"{city}:{q['keywords']}:{q.get('types','')}".encode()).hexdigest()
        cached_json = DynamicFetchCacheDAO.get(city, query_hash)
        if cached_json:
            all_cached.extend(json.loads(cached_json))
        else:
            uncached_queries.append((q, query_hash))

    if uncached_queries:
        # 只抓取未缓存的查询
        raw_pois = execute_dynamic_fetch([q for q, _ in uncached_queries], city, pages_per_query)
        # 按查询分别缓存
        # ...（需要按query分组缓存，这里需要额外处理）
    
    # 合并缓存+新抓取结果
    # ...
```

**缓存分组策略**：由于 `execute_dynamic_fetch` 返回的是合并后的结果，需要改为按查询分别缓存。建议修改 `_fetch_one` 返回 `(query_hash, pois_list)`，然后外层分别存入缓存。

### 2.3 测评方法与通过标准

**测评指标**：
1. **端到端耗时**：记录 `[Perf] DynamicFetch` 耗时日志
2. **缓存命中率**：记录 `cache_hit / total_queries` 比例

**测试脚本**：

```python
# test_perf_dynamic_fetch.py
import time
import requests

payload = {
    "city": "杭州",
    "date": "2026-06-02",
    "start_time": "09:00",
    "end_time": "18:00",
    "budget": 500,
    "traveler_type": "独自",
    "transport_mode": "步行",
    "preferences": ["美食", "拍照", "自然"],
    "pace": "适中",
    "raw_query": "喜欢爬山，爬完山想吃美食"  # 触发动态抓取
}

start = time.time()
r = requests.post("http://127.0.0.1:8000/api/plan", json=payload, timeout=180)
end = time.time()

print(f"Total time: {end-start:.1f}s")
print(f"Status: {r.status_code}")
```

**通过标准**：
- [ ] 首次请求（无缓存）≤ 20秒
- [ ] 重复请求（有缓存）≤ 2秒
- [ ] 后端日志中 `[DynamicFetch]` 输出显示并发执行（多个查询的日志时间戳重叠）
- [ ] 返回的POI数量与优化前基本一致（±10%以内）

---

## 三、阶段2：交通API升级（v5/direction）

### 3.1 现状诊断

**当前代码**：`backend/data/direction_api.py:54`

```python
url = f"https://restapi.amap.com/v3/direction/{amap_mode}"
```

**问题**：
- v3/direction 对非步行模式有权限限制，日志中出现 `INSUFFICIENT_PRIVILEGES`
- v5/direction 是高德路线规划2.0，功能更全，权限策略可能不同

### 3.2 技术方案

#### 改动：替换API版本和解析逻辑（`direction_api.py`）

**URL替换**：
```python
# 旧
url = f"https://restapi.amap.com/v3/direction/{amap_mode}"

# 新
url = f"https://restapi.amap.com/v5/direction/{amap_mode}"
```

**v5/direction 支持的mode**：
- `driving` — 驾车
- `walking` — 步行
- `bicycling` — 骑行
- `transit` — 公交（v5中可能叫 `integration` 或 `transit`）
- `motor` — 电动车

**需要确认**：v5的公交模式参数名。参考高德文档：https://lbs.amap.com/api/webservice/guide/api/newroute

**响应解析调整**：

v5的响应结构可能与v3不同。以驾车为例，v5返回格式大致为：
```json
{
  "status": "1",
  "route": {
    "paths": [
      {
        "distance": "12345",
        "duration": "1800",
        "strategy": "速度优先"
      }
    ]
  }
}
```

解析逻辑需要适配。在 `_get_amap_direction` 中：
```python
# 保持现有解析框架，但适配v5字段
data = resp.json()
if data.get("status") != "1":
    # 处理错误
    return None

route = data.get("route", {})
paths = route.get("paths", [])
if not paths:
    return None

path = paths[0]
distance_m = int(path.get("distance", 0))
duration_sec = int(path.get("duration", 0))
return distance_m, duration_sec
```

**MODE_MAP扩展**（可选，如果前端需要电动车模式）：
```python
MODE_MAP = {
    "步行": "walking",
    "驾车": "driving",
    "骑行": "bicycling",
    "公交": "transit",
    "电动车": "motor",  # 新增
}
```

#### 改动：缓存TTL延长（`db/models.py`）

将 `DirectionCacheDAO.get()` 中的TTL从7天改为30天：
```python
if datetime.now(created.tzinfo) - created > timedelta(days=30):  # 从7天改为30天
    return None
```

### 3.3 测评方法与通过标准

**测评指标**：
1. **API可用性**：v5/direction 是否能成功返回（无 `INSUFFICIENT_PRIVILEGES`）
2. **距离精度**：对比v5返回的距离与v3（如果v3可用）或OSRM步行矩阵的差异
3. **多模式覆盖**：步行/驾车/骑行/公交四种模式是否都能正常返回

**测试脚本**：

```python
# test_v5_direction.py
from backend.data.direction_api import _get_amap_direction
from backend.models.schemas import Location

loc_a = Location(lat=30.2596, lng=120.1460)  # 西湖附近
loc_b = Location(lat=30.1890, lng=120.1000)  # 灵隐附近

for mode in ["步行", "驾车", "骑行", "公交"]:
    result = _get_amap_direction(loc_a, loc_b, mode)
    print(f"{mode}: {result}")
```

**通过标准**：
- [ ] v5/direction 返回状态码200，无权限错误
- [ ] 4种交通模式都能返回有效的(distance_m, duration_sec)
- [ ] 步行模式的距离与OSRM矩阵差异在±20%以内（验证合理性）
- [ ] 驾车/骑行/公交的距离大于步行距离（符合常识）

---

## 四、阶段3：个性化效果离线评测 + LLM偏好解析增强

### 4.1 现状诊断

**个性化算法存在但不可见**：
- `personalization.py` 有画像加载、融合（0.7:0.3）、EMA演化
- `route_engine.py:264-272` 有基于画像的POI加分逻辑
- 但没有任何量化指标证明"个性化真的改变了推荐结果"

**LLM偏好解析**：
- `llm_parser.py` 已支持 raw_query → UserPreference
- 但 `.env` 中模型名称可能有误（日志显示 `minimax-m3#minimax-text-01` 报错）

### 4.2 技术方案

#### 改动1：离线模拟评测框架（新增 `backend/core/personalization_eval.py`）

**构造模拟画像集**：

```python
MOCK_PROFILES = {
    "亲子型": UserPreference(
        theme_weights={"自然": 0.9, "娱乐": 0.8, "美食": 0.5, "拍照": 0.4, "文化": 0.3, "购物": 0.2},
        traveler_type="亲子",
        pace_preference="适中",
        price_sensitivity=0.3,
        willingness_to_queue=0.2,
        willingness_to_walk=0.4,
    ),
    "情侣型": UserPreference(
        theme_weights={"拍照": 0.95, "美食": 0.8, "文化": 0.6, "自然": 0.5, "购物": 0.3, "娱乐": 0.4},
        traveler_type="情侣",
        pace_preference="悠闲",
        price_sensitivity=0.4,
        willingness_to_queue=0.5,
        willingness_to_walk=0.6,
    ),
    "美食型": UserPreference(
        theme_weights={"美食": 0.95, "文化": 0.5, "拍照": 0.4, "自然": 0.2, "购物": 0.3, "娱乐": 0.5},
        traveler_type="朋友",
        pace_preference="适中",
        price_sensitivity=0.6,
        willingness_to_queue=0.7,
        willingness_to_walk=0.5,
    ),
    "户外型": UserPreference(
        theme_weights={"自然": 0.95, "拍照": 0.7, "文化": 0.3, "美食": 0.2, "购物": 0.1, "娱乐": 0.3},
        traveler_type="独自",
        pace_preference="紧凑",
        price_sensitivity=0.2,
        willingness_to_queue=0.3,
        willingness_to_walk=0.9,
    ),
    "文化型": UserPreference(
        theme_weights={"文化": 0.95, "美食": 0.6, "拍照": 0.5, "自然": 0.4, "购物": 0.3, "娱乐": 0.2},
        traveler_type="独自",
        pace_preference="适中",
        price_sensitivity=0.3,
        willingness_to_queue=0.4,
        willingness_to_walk=0.6,
    ),
    # ... 可扩展更多
}
```

**A/B对比实验函数**：

```python
def evaluate_personalization_impact(
    candidates: List[POI],
    base_request: PlanRequest,
    constraints: RouteConstraints,
    profile_name: str,
    profile_pref: UserPreference
) -> Dict:
    """
    对比"有画像"vs"无画像"的推荐差异
    返回差异度报告
    """
    from backend.core.route_engine import generate_preference_variants
    from backend.core.personalization import UserPersonalizationEngine

    engine = UserPersonalizationEngine()

    # A组：无画像（仅用当前请求偏好）
    plans_without = generate_preference_variants(candidates, base_request, constraints)

    # B组：有画像（当前请求 + 历史画像融合）
    fused = engine.fuse_preferences(base_request, profile_pref)
    plans_with = generate_preference_variants(candidates, fused, constraints)

    # 计算差异度
    report = {
        "profile": profile_name,
        "plans_without": _extract_plan_signature(plans_without),
        "plans_with": _extract_plan_signature(plans_with),
        "diff_score": _compute_plan_diff(plans_without, plans_with),
    }
    return report

def _extract_plan_signature(plans):
    """提取路线的可比较特征"""
    return [
        {
            "theme": p.theme,
            "poi_names": [s.poi.name for s in p.segments],
            "categories": [s.poi.category for s in p.segments],
            "tags": list(set(t for s in p.segments for t in s.poi.tags)),
        }
        for p in plans
    ]

def _compute_plan_diff(plans_a, plans_b):
    """计算两套方案的差异度（0=完全相同，1=完全不同）"""
    # 示例：比较POI名称的Jaccard距离
    names_a = set(s.poi.name for p in plans_a for s in p.segments)
    names_b = set(s.poi.name for p in plans_b for s in p.segments)
    intersection = len(names_a & names_b)
    union = len(names_a | names_b)
    return 1.0 - (intersection / union) if union > 0 else 0.0
```

**批量评测脚本**（`scripts/eval_personalization.py`）：

```python
# 对多个query和多个画像运行评测，输出CSV报告
queries = [
    {"city": "杭州", "preferences": ["美食", "拍照"], "raw_query": "周末带女朋友去杭州玩，喜欢拍照和吃辣"},
    {"city": "杭州", "preferences": ["自然", "文化"], "raw_query": "带小孩去杭州，想爬山和看博物馆"},
    # ... 10-20个
]

for query in queries:
    candidates = get_cached_pois(query["city"])
    for name, profile in MOCK_PROFILES.items():
        report = evaluate_personalization_impact(candidates, query, constraints, name, profile)
        print(report)
```

#### 改动2：LLM偏好解析增强（`llm_parser.py`）

**检查模型配置**：
```bash
# 检查 .env 文件
cat .env | grep LLM
```

如果模型名称有误（如 `minimax-m3#minimax-text-01`），修复为正确的模型名称。

**增强Prompt**（支持负面偏好、预算约束、人群约束）：

```python
SYSTEM_PROMPT = """你是旅行偏好解析专家。将用户的自然语言描述解析为结构化JSON。

特别注意：
1. 识别正面偏好（"我喜欢...""想..."）和负面偏好（"不喜欢...""不要...""避开..."）
2. 提取预算约束（"预算200以内""便宜点"）
3. 提取人群约束（"带小孩""和老人""情侣"）
4. 提取交通偏好（"自驾""地铁""走路"）

输出JSON格式：
{
  "theme_weights": {"美食": 0.9, "拍照": 0.8, ...},
  "traveler_type": "情侣",
  "pace_preference": "适中",
  "budget_level": "经济",
  "must_visit": [],
  "avoid": ["辣食", "排队"],
  "transport_mode": "步行",
  "notes": "用户对排队敏感，偏好拍照打卡点"
}"""
```

**回显确认**：前端在LLM解析后，展示解析结果让用户确认：
```
系统理解你的偏好：
- 喜欢：美食(90%)、拍照(80%)、自然(60%)
- 出行人群：情侣
- 节奏：适中
- 避开：辣食、排队
- 对吗？[确认] [修改]
```

### 4.3 测评方法与通过标准

**测评指标**：
1. **画像影响力分数**：不同画像类型的平均 `diff_score`
2. **人工抽查**：随机10组对比，人工判断"有画像"是否更合理

**通过标准**：
- [ ] 至少5种画像类型的平均 `diff_score > 0.2`（说明画像确实改变了推荐）
- [ ] 人工抽查中，"有画像更合理"的比例 ≥ 70%
- [ ] LLM偏好解析能正确识别负面偏好（如"不喜欢排队" → avoid: ["排队"]）

---

## 五、阶段4：UGC架构先行（模拟数据验证逻辑）

### 5.1 现状诊断

**POI模型已有字段但数据虚假**：
```python
ugc_keywords: List[str] = ["体验不错", "值得打卡", "人气很旺"]  # 批量重复，无区分度
```

**未参与评分**：`compute_poi_marginal_value` 中完全没有使用UGC字段。

### 5.2 技术方案

#### 改动1：扩展POI模型（`models/schemas.py`）

```python
class POI(BaseModel):
    # ... 现有字段 ...
    ugc_keywords: List[str] = Field(default_factory=list, description="UGC高频关键词")
    ugc_sentiment_score: float = Field(0.0, description="UGC整体情感分 -1~+1")
    ugc_scene_tags: List[str] = Field(default_factory=list, description="UGC场景标签，如'适合亲子'")
    ugc_recent_warn: Optional[str] = Field(None, description="近期负面预警，如'五一排队3小时'")
```

#### 改动2：LLM模拟UGC生成（`scripts/enrich_pois_by_llm.py`）

在现有的丰富化流程中，增加UGC字段生成步骤：

```python
UGC_PROMPT = """基于以下POI信息，模拟生成该POI的用户评价特征。

POI：{name}
城市：{city}
类别：{category}
标签：{tags}
评分：{rating}

请输出JSON：
{
  "ugc_keywords": ["真实用户常提到的3-5个关键词"],
  "ugc_sentiment_score": 0.7,  // -1.0到+1.0
  "ugc_scene_tags": ["适合亲子", "情侣约会"],  // 从评价中提炼的场景
  "ugc_recent_warn": null  // 如有近期负面信息，写在这里，否则null
}"""
```

缓存到 `poi_enrichment_cache.json`，避免重复调用。

#### 改动3：UGC参与路线评分（`route_engine.py:264+`）

在 `compute_poi_marginal_value` 中新增UGC加分项：

```python
# 在现有代码之后追加：

# UGC情感分加成（范围约-15到+15分）
if poi.ugc_sentiment_score != 0:
    marginal_value += poi.ugc_sentiment_score * 15

# UGC场景标签与人群匹配加成
if user_pref.traveler_type and poi.ugc_scene_tags:
    scene_match_map = {
        "亲子": ["亲子", "儿童", "乐园", "科普", "互动"],
        "情侣": ["情侣", "浪漫", "约会", "夜景", "私密"],
        "朋友": ["聚会", "社交", "打卡", "热闹"],
        "独自": ["安静", "独处", "治愈", "小众"],
        "家庭": ["家庭", "老人", "无障碍", "宽敞"],
    }
    match_keywords = scene_match_map.get(user_pref.traveler_type, [])
    for tag in poi.ugc_scene_tags:
        if any(kw in tag for kw in match_keywords):
            marginal_value += 10
            break  # 只加一次

# UGC近期负面预警（不直接减分，但通过tips传递给用户）
# 预警信息在生成tips时使用
```

**在tips生成中展示UGC预警**（`preference_guided_greedy.py` 或 `route_engine.py` 中生成tips的地方）：

```python
if poi.ugc_recent_warn:
    tips = f"⚠️ 网友提醒：{poi.ugc_recent_warn}"
elif arrive_dt.hour < 10 and any(t in poi.tags for t in ["拍照", "摄影"]):
    tips = "上午光线柔和，适合拍照"
# ... 现有tips逻辑
```

### 5.3 测评方法与通过标准

**测评指标**：
1. **UGC影响比例**：统计有多少POI因为UGC加分而被选入/排除
2. **人工合理性抽查**：对比"有UGC评分"和"无UGC评分"两套方案，人工判断哪套更合理

**测试脚本**：

```python
# test_ugc_impact.py
# 对同一组候选POI，分别用 ugc_sentiment_score=0（关闭）和实际值（开启）生成路线
# 对比差异
```

**通过标准**：
- [ ] UGC字段正确生成（sentiment_score在-1~+1之间，scene_tags非空）
- [ ] 至少20%的POI选择因为UGC加分发生了改变
- [ ] 人工抽查中，"有UGC更合理"的比例 ≥ 60%
- [ ] 负面预警（如"排队久"）正确展示在对应POI的tips中

---

## 六、通用注意事项

### 6.1 代码风格
- 保持现有代码风格，与周边代码一致
- 新增函数添加docstring
- 使用类型注解

### 6.2 测试要求
- 每个阶段的改动都需要编写测试脚本（放在 `tests/` 目录或根目录的 `test_xxx.py`）
- 测试脚本需要能独立运行，不依赖前端

### 6.3 回滚策略
- 每个阶段的改动保持最小化，便于回滚
- 保留原有代码作为注释或fallback

### 6.4 关键配置
- `.env` 文件中的 `AMAP_KEY` 和 `LLM_API_KEY` 是核心配置
- `backend/core/config.py` 读取环境变量

---

## 八、前端改动说明

以下前端改动与后端阶段对应，可根据需要选择性实施。

### 8.1 阶段2配套：交通模式扩展（`frontend/index.html`）

如果后端新增了电动车模式，前端交通方式下拉框需要同步：

```html
<!-- 现有选项 -->
<option value="步行">步行</option>
<option value="驾车">驾车</option>
<option value="骑行">骑行</option>
<option value="公交">公交</option>
<!-- 新增 -->
<option value="电动车">电动车</option>
```

**文件位置**：搜索 `transport_mode` 或 `transportMode` 相关的 `<select>` 元素。

### 8.2 阶段3配套：LLM偏好解析回显（`frontend/index.html`）

当用户填写 `raw_query`（自然语言描述）后，后端LLM解析出的结构化偏好可以回显给用户确认：

**交互流程**：
1. 用户输入："我喜欢爬山和拍照，不吃辣，预算200"
2. 后端LLM解析返回：`{theme_weights: {自然:0.9, 拍照:0.8}, avoid:["辣"], budget_level:"经济"}`
3. 前端展示解析结果卡片：
   ```
   📋 系统理解你的偏好：
   • 喜欢的主题：自然(90%)、拍照(80%)
   • 出行人群：独自
   • 预算级别：经济
   • 避开：辣食
   [理解正确 ✅] [需要调整 ✏️]
   ```
4. 用户点击"理解正确"后，才发送正式规划请求

**实现建议**：
- 新增API接口 `POST /api/parse-preference`，专门用于LLM解析 raw_query，不生成路线
- 前端先调用此接口，展示解析结果，用户确认后再调用 `/api/plan`

### 8.3 阶段3配套：个性化差异可视化（可选，中量版）

在三套方案对比页面，增加"个性化匹配度"小标签：

```html
<!-- 在每个POI卡片上 -->
<div class="personalization-tags">
  <span class="tag-match">🔥 匹配你的美食偏好</span>
  <span class="tag-match">👶 适合你的亲子出行</span>
</div>
```

**数据来源**：后端 `PlanSegment.selection_reasons` 字段已包含选中原因，前端只需解析并渲染为更友好的标签。

### 8.4 阶段4配套：UGC标签展示（`frontend/index.html`）

在POI详情卡片中展示UGC信息：

```html
<div class="poi-ugc">
  <div class="ugc-keywords">
    <span v-for="kw in poi.ugc_keywords" class="ugc-tag">{{kw}}</span>
  </div>
  <div class="ugc-sentiment" :class="sentimentClass">
    {{poi.ugc_sentiment_score > 0 ? '👍 好评居多' : '👎 差评较多'}}
  </div>
  <div v-if="poi.ugc_recent_warn" class="ugc-warn">
    ⚠️ {{poi.ugc_recent_warn}}
  </div>
</div>
```

**样式建议**：
- `ugc-tag`：灰色圆角小标签
- `ugc-warn`：橙色背景预警条

---

## 九、数据库迁移脚本

### 9.1 新增 `dynamic_fetch_cache` 表

**迁移SQL**（在 `backend/db/models.py` 的 `CREATE_TABLES_SQL` 中追加，或在SQLite命令行执行）：

```sql
-- 动态抓取结果缓存表
CREATE TABLE IF NOT EXISTS dynamic_fetch_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    results_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(city, query_hash)
);

-- 索引：加速按城市+query_hash查询
CREATE INDEX IF NOT EXISTS idx_dynamic_fetch_lookup 
ON dynamic_fetch_cache(city, query_hash);
```

**Python迁移脚本**（`scripts/migrate_db.py`）：

```python
#!/usr/bin/env python3
"""数据库迁移脚本：新增动态抓取缓存表"""

import sqlite3
import sys
sys.path.insert(0, 'backend')

from backend.db.database import get_db

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS dynamic_fetch_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    results_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(city, query_hash)
);

CREATE INDEX IF NOT EXISTS idx_dynamic_fetch_lookup 
ON dynamic_fetch_cache(city, query_hash);
"""

def migrate():
    with get_db() as conn:
        conn.executescript(MIGRATION_SQL)
        print("[Migrate] dynamic_fetch_cache 表创建成功")
        
        # 验证表是否存在
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dynamic_fetch_cache'"
        )
        if cursor.fetchone():
            print("[Migrate] 验证通过：dynamic_fetch_cache 表已存在")
        else:
            print("[Migrate] 验证失败：表未创建")

if __name__ == "__main__":
    migrate()
```

**运行方式**：
```bash
cd d:/美团hackthon_5
python scripts/migrate_db.py
```

### 9.2 关于POI模型扩展的说明

**注意**：`POI` 数据存储在 `data/{city}_pois.json` 文件中，不是SQLite数据库表。因此扩展 `POI` 模型（新增 `ugc_sentiment_score` 等字段）不需要SQL迁移，而是：

1. 修改 `backend/models/schemas.py` 中的 `POI` 类定义
2. 重新运行 `scripts/enrich_pois_by_llm.py` 生成新的丰富化数据
3. 新的JSON文件会自动包含新增字段

**兼容性处理**：Pydantic模型新增字段时设置默认值（如 `ugc_sentiment_score: float = 0.0`），确保旧数据也能正常解析。

### 9.3 DirectionCache 表兼容性

`DirectionCacheDAO` 的TTL从7天改为30天是**代码逻辑改动**，不需要修改表结构。SQLite表结构保持不变。

---

## 十、快速启动检查清单

如果后续开发对话中的AI代理接手，按以下顺序操作：

1. [ ] 读取 `d:/美团hackthon_5/.env` 确认 `AMAP_KEY` 和 `LLM_API_KEY` 是否存在
2. [ ] 检查后端服务是否运行：`curl http://127.0.0.1:8000/`
3. [ ] 运行基础测试：`python test_api_simple.py`（验证服务正常）
4. [ ] **运行数据库迁移**：`python scripts/migrate_db.py`（创建 dynamic_fetch_cache 表）
5. [ ] 按阶段1-4顺序实施，每阶段完成后运行对应测评脚本
6. [ ] 每个阶段结束时重启后端服务并验证
