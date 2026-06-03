# 项目上下文提示词

> 复制以下全部内容到新对话的第一条消息，AI 即可理解整个项目上下文继续开发。

---

## 【项目概述】

这是一个「本地智能路线规划系统」，美团 AI Hackthon 项目。
- **核心功能**：根据用户自然语言输入（如"周末带女朋友去北京，喜欢拍照和吃辣"），生成 3 套差异化的旅行路线方案
- **技术栈**：FastAPI (Python) + Pydantic v2 后端，单文件 Leaflet.js 前端
- **数据**：已从 Mock 数据迁移为高德 API 真实数据 + LLM 丰富化，支持任意中国城市的动态构建
- **LLM API**：智谱 AI (BigModel)，`https://open.bigmodel.cn/api/paas/v4`，模型 `glm-4`，配置在 `.env` 文件
- **高德 API**：`https://restapi.amap.com/v3/place/text`，Key 配置在 `.env` 文件

---

## 【目录结构】

```
d:\美团hackthon_5
├── backend/
│   ├── main.py              # FastAPI 入口，扩展了城市管理接口
│   ├── models/
│   │   └── schemas.py       # Pydantic 模型
│   ├── core/
│   │   ├── route_engine.py  # 核心规划引擎（三层策略 + 贪心 + 2-opt）
│   │   ├── preference.py    # 偏好解析、POI偏好匹配度计算
│   │   ├── llm_parser.py    # LLM意图理解（从 .env 加载配置）
│   │   ├── llm_reasoner.py  # LLM推荐理由生成（从 .env 加载配置）
│   │   └── config.py        # 统一配置加载（.env）
│   ├── services/
│   │   └── planner.py       # 业务编排：召回→规划→LLM理由→缓存
│   └── data/
│       ├── loader.py        # POI加载（按城市隔离）+ DistanceMatrixProvider
│       └── city_builder.py  # 城市数据自动构建（高德拉取→fallback→矩阵→LLM）
├── frontend/
│   └── index.html           # 单文件前端：任意城市输入、地图、三方案、进度显示
├── data/
│   ├── {city}_pois.json              # LLM丰富化后的最终数据
│   ├── {city}_pois_fallback.json     # fallback规则临时数据
│   ├── {city}_pois_amap_raw.json     # 高德原始数据
│   ├── distance_matrix_osrm_foot_{city}.json  # 城市距离矩阵
│   ├── distance_matrix_osrm_foot.json  # 杭州旧矩阵（兼容）
│   └── distance_matrix_haversine.json  # Haversine备用矩阵
├── scripts/
│   ├── fetch_pois_amap.py           # 高德API拉取（从.env读取Key）
│   ├── enrich_pois_by_llm.py        # LLM丰富化（从.env读取配置）
│   ├── compute_distance_matrix_osrm_table.py  # OSRM距离矩阵计算
│   └── build_real_pois_pipeline.py  # 一键整合脚本
├── tests/
│   ├── e2e_test.py          # 端到端测试（需适配真实数据特性）
│   └── locustfile.py        # 性能测试
├── docs/
│   ├── llm_enrichment_prompt.md      # LLM丰富化提示词
│   └── project_context_prompt.md     # 本文件
└── .env                     # 环境变量配置文件（LLM Key / 高德 Key）
```

---

## 【当前已实现的功能】

### 后端
1. **任意城市支持**：出现新城市时自动从高德拉取POI，fallback丰富化立即可用，后台异步完成LLM丰富化
2. **城市数据缓存**：`{city}_pois.json` / `{city}_pois_fallback.json` / `{city}_pois_amap_raw.json`
3. **动态城市接口**：
   - `GET /api/cities` — 返回已有城市列表（含中心坐标、构建状态）
   - `POST /api/cities/{city}/init` — 触发城市数据初始化
   - `GET /api/cities/{city}/status` — 查询构建进度
4. **多城市路线规划**：起点自动使用城市POI平均坐标，避免硬编码杭州中心
5. **距离矩阵按城市隔离**：`distance_matrix_osrm_foot_{city}.json`，无矩阵时回退Haversine
6. **LLM配置外部化**：所有LLM相关配置从 `.env` 读取，当前使用智谱AI

### 前端
1. **任意城市输入**：`<input>` + `<datalist>` 自动补全，支持 `/api/cities` 动态加载
2. **城市构建进度条**：调用 `init` 后显示蓝色进度条 + 状态文字，轮询 `status` 接口
3. **地图自适应城市中心**：根据城市坐标自动 `setView`，全国任意城市均可显示
4. **真实图片**：直接使用高德 `photos` URL，无图片时显示分类emoji

### 数据流程
```
用户输入城市 → 检查 {city}_pois.json
    ├── 存在 → 直接加载（最高质量）
    ├── 存在 fallback → 加载fallback（可用，质量一般）
    └── 都不存在 → 触发自动构建
        Step 1: 高德API拉取 → {city}_pois_amap_raw.json (~20s)
        Step 2: fallback丰富化 → {city}_pois_fallback.json (~1s，立即可用)
        Step 3: OSRM距离矩阵 → distance_matrix_osrm_foot_{city}.json (~1-2min)
        Step 4: LLM丰富化 → {city}_pois.json (~40-50min，后台完成)
```

---

## 【验证状态】

| 功能 | 状态 |
|------|------|
| 杭州路线规划 | ✅ 正常（3/5/5 POIs） |
| 北京路线规划 | ✅ 正常（3/3/4 POIs，使用fallback数据） |
| 北京LLM丰富化 | ❌ 未完成（`北京_pois.json` 不存在） |
| 北京距离矩阵 | ❌ 未计算（使用Haversine估算） |
| 城市自动构建流程 | ✅ 正常 |
| 前端城市输入+进度 | ✅ 正常 |
| 地图任意城市定位 | ✅ 正常 |

---

## 【后续优化方向（待实现）】

### P0 - 数据完善
1. **完成北京LLM丰富化**：重新启动后台任务，生成 `北京_pois.json`
2. **计算北京距离矩阵**：运行 `compute_distance_matrix_osrm_table.py` 生成 `distance_matrix_osrm_foot_北京.json`

### P1 - 数据质量控制
3. **POI过滤**：当前249条包含大量偏远小众POI，建议按以下条件过滤：
   - 评分 ≥ 3.5 且评价数暗示的热度
   - 距离城市中心 ≤ 20km（或根据城市规模调整）
   - 排除 "地名地址信息"、"商务住宅" 等非旅游类POI
4. **高德图片下载**：部分POI的 `photos` 为空，需要批量下载或提供默认占位图

### P2 - 前端体验
5. **构建进度WebSocket**：用 WebSocket/SSE 替代轮询，减少请求数
6. **城市搜索联想**：输入时实时调用高德城市搜索API，提供准确的城市名补全
7. **地图POI预览**：城市初始化完成后，在地图上预展示所有候选POI点位

### P3 - 测试与稳定性
8. **e2e测试适配**：更新断言以适配真实数据特性（距离分布更广、价格更高）
9. **缓存热更新**：城市数据更新后自动清除 `loader.py` 中的 `_poi_cache` 和 `_matrix_providers`
10. **构建失败重试**：`city_builder.py` 中增加指数退避重试机制

### P4 - 性能优化
11. **LLM丰富化并发提速**：当前 batch_size=5 串行执行，可改为 asyncio 并发
12. **多城市并发构建**：同时初始化多个城市的数据

---

## 【关键文件路径】

- 后端入口：`backend/main.py`
- 数据模型：`backend/models/schemas.py`
- 规划引擎：`backend/core/route_engine.py`
- 业务编排：`backend/services/planner.py`
- 城市构建：`backend/data/city_builder.py`
- POI加载：`backend/data/loader.py`
- 配置加载：`backend/core/config.py`
- 前端：`frontend/index.html`
- LLM丰富化：`scripts/enrich_pois_by_llm.py`
- 高德拉取：`scripts/fetch_pois_amap.py`
- 距离矩阵：`scripts/compute_distance_matrix_osrm_table.py`
- 环境变量：`.env`

---

## 【关键配置】

`.env` 文件格式：
```env
LLM_API_KEY=你的_智谱_API_Key
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL_NAME=glm-4
AMAP_KEY=你的_高德_Key
```

---

## 【开发注意事项】

1. **Windows 编码**：`scripts/` 下的文件有 UTF-8 编码修复代码，后台线程执行时需检查 `hasattr(sys.stdout, 'buffer')`
2. **高德API限制**：每类最多返回100条（25条/页×4页），建议 `max_per_type=30`
3. **OSRM限流**：公共OSRM服务器建议 batch_size=70，调用间隔 ≥1秒
4. **LLM超时**：智谱API响应约10-50秒，timeout 设为 120s
5. **不要硬编码API Key**：所有密钥必须从 `.env` 或环境变量读取
