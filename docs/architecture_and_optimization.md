# 项目架构全景与优化分析

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              前端 (Frontend)                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ 偏好表单面板  │  │ 三方案总览   │  │ 路线详情+对比 │  │ 侧边栏面板   │ │
│  │ (Leaflet地图)│  │ (POI卡片)    │  │ (时间轴)     │  │ (画像/历史)  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘ │
│                          Vanilla JS + Leaflet.js                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │ HTTP/REST (CORS)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              后端 (Backend)                               │
│  FastAPI + Uvicorn │ SQLite │ 同步线程池 (def handler)                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌──────────┐ │
│  │ main.py     │───▶│ planner.py  │───▶│ route_engine│───▶│ 返回响应  │ │
│  │ (REST入口)  │    │ (编排服务)   │    │ (核心算法)   │    │          │ │
│  └─────────────┘    └──────┬──────┘    └─────────────┘    └──────────┘ │
│                            │                                           │
│         ┌──────────────────┼──────────────────┐                        │
│         ▼                  ▼                  ▼                        │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐                  │
│  │ preference  │   │ hybrid_filter│   │ personalization               │ │
│  │ (偏好解析)   │   │ (POI筛选)    │   │ (用户画像)    │                  │
│  └─────────────┘   └──────┬──────┘   └─────────────┘                  │
│                           │                                           │
│         ┌─────────────────┼─────────────────┐                         │
│         ▼                 ▼                 ▼                         │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐      │
│  │ llm_parser │  │ llm_filter │  │ llm_reranker│  │semantic_matcher│  │
│  │ (意图理解)  │  │ (语义打分)  │  │ (精排融合)   │  │ (BGE嵌入)     │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘      │
│                                                                         │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐      │
│  │ policy_gen │  │ llm_reasoner│  │dynamic_fetch│  │ data/loader  │  │
│  │ (策略生成)  │  │ (推荐理由)  │  │ (动态抓取)   │  │ (数据加载)   │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              外部依赖                                     │
│  MiniMax-M3 / openai-next (LLM)    高德API (POI+天气+路线)    OSRM (距离) │
└─────────────────────────────────────────────────────────────────────────┘
```

## 二、核心数据流（/api/plan）

```
POST /api/plan
│
├─▶ 1. 画像描述注入（可选）        ~0s
│   └─ 把用户长期画像拼接到 raw_query
│
├─▶ 2. 偏好解析                    ~5-15s
│   ├─ LLM 解析 raw_query → UserPreference (timeout=15s)
│   └─ fallback: 规则解析偏好标签
│
├─▶ 3. 历史画像融合                 ~0s
│   └─ load_profile() + fuse_preferences()
│
├─▶ 4. POI 召回                     ~0-20s
│   ├─ 加载本地缓存城市数据 (~0s)
│   └─ DynamicFetch 动态抓取 (~20s，LLM生成查询+高德API)
│
├─▶ 5. 混合 POI 筛选                 ~8-70s  ★ 核心瓶颈
│   ├─ loose_filter: 硬约束过滤 (~0s)
│   ├─ score_by_preference: BGE语义打分 (~7s，首次)
│   └─ llm_filter.filter_batch: LLM精排20个POI (~70s) ★★
│
├─▶ 6. 天气感知调整                 ~0s
│
├─▶ 7. Policy + Reranker 并行       ~25-45s  ★ 核心瓶颈
│   ├─ Policy Generator (LLM, timeout=25s, 实际~40s)
│   └─ LLM Reranker (LLM, timeout=30s, 实际~40s)
│
├─▶ 8. LLM 骨架规划                 ~20s     ★ 可跳过
│   └─ 从候选池选6-8个核心POI (timeout=20s)
│
├─▶ 9. 路线规划引擎                 ~1-5s
│   ├─ 去重过滤 → 贪心构造 → 2-opt优化 → 强制插餐
│   └─ 生成3套方案（深度/高效/均衡）
│
├─▶ 10. LLM 推荐理由生成            ~10-30s  ★ 可跳过
│   └─ 3个方案并行，每个timeout=10s (实际~30s)
│
├─▶ 11. 缓存写入 + 画像更新          ~0s
│   └─ SQLite plan_cache + 双轨画像更新
│
└─▶ 返回 PlanResponse

总耗时: 120s+ (首请求，MiniMax)
         90s+ (首请求，openai-next，LLM Filter 占70s)
```

## 三、当前问题诊断

### P0 阻塞问题：请求超时导致前端"刷新才显示"

| 问题 | 根因 | 影响 |
|------|------|------|
| **后端 handler 是同步的** | `def create_plan` 而非 `async def`，FastAPI 在线程池中运行，处理时间长会阻塞线程 | 单请求 >60s，浏览器 fetch 超时断开 |
| **OpenAI 库 timeout 不精确** | MiniMax 尤为严重：`timeout=15` 实际等 30-45s，`timeout=30` 实际等 60-90s | 所有 LLM 调用都远超预期超时 |
| **LLM 调用次数过多** | 单次 /api/plan 触发 6-8 次 LLM 调用（解析、抓取、筛选、策略、精排、骨架、推荐理由×3） | 串行/并行累积，总时间爆炸 |
| **LLM Filter prompt 过长** | 20个POI的完整JSON描述送入LLM，单次处理70s | hybrid_filter 成为最大瓶颈 |
| **前端 fetch 无超时** | `apiCall()` 未设置 `AbortController` 或超时 | 用户看到无限"生成中" |

### P1 稳定性问题

| 问题 | 根因 | 影响 |
|------|------|------|
| **ThreadPoolExecutor 嵌套** | FastAPI 线程池 → planner ThreadPool(max_workers=2) → 推荐理由 ThreadPool(max_workers=3) | 线程资源竞争，Windows 下偶发死锁/卡死 |
| **BGE 模型逐条推理** | `score_by_preference` 中每个POI单独调用 `embed_text()` | 219个POI × 单条推理 overhead = 7s |
| **DynamicFetch 每次都触发** | 有 raw_query 就无条件调用，即使本地已有219个POI | 增加 20s 无意义开销 |
| **SQLite 线程安全** | `threading.local()` 连接，但多线程并发写入可能竞争 | 高并发时可能锁冲突 |

### P2 体验问题

| 问题 | 根因 | 影响 |
|------|------|------|
| **无进度反馈** | 后端一次性返回，前端看不到"正在做哪一步" | 用户焦虑，容易刷新 |
| **无请求去重/防抖** | 用户多次点击"生成"会发多个请求 | 后端资源浪费，线程池更快占满 |
| **地图路线不同步** | overview/compare 视图只显示单条路线 | 用户无法直观对比三套方案的空间差异 |

## 四、优化建议（按优先级）

### 🔴 P0 - 立即修复（解决"刷新才显示"）

#### 1. 后端改为异步 + Streaming SSE（最彻底）
```python
# main.py
@app.post("/api/plan")
async def create_plan(request: PlanRequest):
    # 使用 BackgroundTasks 或 Celery 异步执行
    task_id = await submit_plan_task(request)
    return {"task_id": task_id, "status": "processing"}

@app.get("/api/plan/task/{task_id}")
async def get_plan_status(task_id: str):
    # 轮询返回进度 + 结果
```
**收益**: 请求 100ms 内返回，前端轮询进度，用户知道"还在跑"，不会刷新。  
**成本**: 需引入 Redis/Celery 或 SQLite 任务表，架构改动较大。

#### 2. 前端增加超时 + 自动轮询（最快落地）
```javascript
// 方案A: 超时后自动轮询缓存
const controller = new AbortController();
const timeoutId = setTimeout(() => controller.abort(), 30000);

// 方案B: 改为分步加载
// Step 1: 快速返回规则方案 (~5s)
// Step 2: 后台LLM增强，前端轮询更新
```
**收益**: 30秒内有响应，LLM增强异步补全。  
**成本**: 纯前端改动，1-2小时。

#### 3. 跳过/压缩 LLM Filter（效果最显著）
```python
# hybrid_filter.py
# 选项A: 完全跳过 llm_filter.filter_batch (节省70s)
# 选项B: 输入从20个POI压缩到5个，timeout压到5s (节省60s+)
```
**收益**: 总时间从 120s 降到 30-40s。  
**成本**: 零架构改动，只需改配置/条件。

#### 4. 用 `requests` 替换 OpenAI 库的 timeout（精确控制）
```python
# 放弃 openai.ChatCompletion.create(timeout=...)
# 改用 requests.post(url, json=payload, timeout=(3, 8))  # (connect, read)
```
**收益**: timeout 精确生效，不再出现"设置15s实际等70s"。  
**成本**: 需封装一个 `safe_llm_call()` 统一替换所有 LLM 调用点。

---

### 🟡 P1 - 架构优化（提升稳定性 & 吞吐量）

#### 5. 预计算 BGE Embedding（启动时一次）
```python
# city_builder.py / main.py startup
# 城市数据加载后，批量计算所有POI embedding，序列化到 .pkl
semantic_matcher.batch_compute_poi_embeddings(all_pois)
semantic_matcher.save_poi_embeddings(city)
```
**收益**: 请求时 `score_by_preference` 从 7s → 0.1s。  
**成本**: 启动多花 7s（一次性），增加 ~5MB 磁盘缓存/城市。

#### 6. LLM 结果多级缓存（避免重复调用）
```python
# 对 parse_preference_from_llm / generate_planning_policy 等加缓存
# key = hash(raw_query + city + preferences)
# TTL = 1小时，命中直接返回
```
**收益**: 相同/相似请求直接命中缓存，0s 响应。  
**成本**: 用 SQLite 或内存 dict 即可实现。

#### 7. 限制 ThreadPoolExecutor 嵌套深度
```python
# planner.py
# 把 ThreadPoolExecutor(max_workers=2/3) 改为单线程串行 + 更短timeout
# 或改用 asyncio.gather() + httpx.AsyncClient (如果handler改为async)
```
**收益**: 消除线程死锁风险，减少上下文切换开销。  
**成本**: 中等，需重构部分调用链。

#### 8. DynamicFetch 按需触发（本地充足时不抓）
```python
# planner.py
if len(all_pois) < 100:  # 本地数据不足才抓
    dynamic_pois = fetch_city_pois_dynamic(...)
```
**收益**: 杭州已有219个POI，完全跳过DynamicFetch，省20s。  
**成本**: 一行代码。

---

### 🟢 P2 - 体验优化（锦上添花）

#### 9. 后端 Streaming 进度推送
```python
# 用 SSE (Server-Sent Events) 推送每一步进度
yield json.dumps({"step": "parsing", "progress": 10})
yield json.dumps({"step": "filtering", "progress": 40})
# ...
yield json.dumps({"step": "done", "result": plan_response})
```
**收益**: 前端显示"正在解析偏好...""正在筛选POI..."，用户有预期。  
**成本**: 中等，需改前端为 EventSource。

#### 10. 前端请求防抖 + 加载状态锁定
```javascript
// 生成按钮点击后锁定，防止重复提交
// 显示"已提交，预计30秒内完成"
```
**收益**: 防止用户焦虑刷新/重复点击。  
**成本**: 纯前端，30分钟。

#### 11. 路线规划结果缓存到 localStorage
```javascript
// 刷新后先从 localStorage 恢复上次结果
// 同时后台静默检查是否有新结果
```
**收益**: 刷新后瞬间看到旧结果，不空白。  
**成本**: 纯前端，1小时。

---

## 五、推荐落地路径（Hackathon 决赛版）

如果只剩 1 天时间准备决赛演示，按这个顺序做：

| 优先级 | 改动 | 预期效果 | 耗时 |
|--------|------|----------|------|
| 1 | **跳过 LLM Filter + DynamicFetch** | 120s → 30s | 10分钟 |
| 2 | **前端 fetch 加 25s 超时 + 提示文案** | 超时后提示"服务器繁忙，请稍后刷新查看结果" | 30分钟 |
| 3 | **预计算 BGE Embedding** | 30s → 20s | 1小时 |
| 4 | **LLM 结果内存缓存** | 重复请求 0s | 1小时 |
| 5 | **前端防抖 + 加载锁定** | 防止重复提交 | 30分钟 |
| 6 | **用 requests 替换 OpenAI timeout** | timeout 精确生效，稳定性提升 | 2小时 |

**底线目标**: 单次请求 **<30s** 稳定返回，前端不再"刷新才显示"。
