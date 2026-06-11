# 旅行规划系统优化计划

> 当前评估得分：2-3/10（LLM 5维度评分）
> 目标得分：6-7/10
> 原则：所有优化必须具备泛化性，不写死任何关键词或规则

---

## 阶段一：泛化性偏好对齐 + 高德多模式路线规划（P0）

### 1.1 泛化性偏好对齐
**问题**：用户说"吃辣"，但路线中出现的是江南菜。当前系统只支持固定的6个维度（美食/拍照/文化/自然/购物/娱乐），无法处理"辣/安静/亲子/网红打卡"等任意偏好关键词。

**方案**：复用现有的 Policy Generator 架构。
- Policy Generator 的 `_SYSTEM_PROMPT` 已经要求 LLM 输出 `theme_keyword_map`
- 当前 `theme_keyword_map` 只在 `route_engine.py` 的 `compute_poi_marginal_value` 中被简单使用
- **需要增强**：在 `compute_poi_marginal_value` 中，对每个POI计算其 `name + tags` 与 `theme_keyword_map` 中对应维度关键词的**匹配度**
- 匹配度越高，该维度的偏好分加成越大

**关键代码位置**：
- `backend/core/route_engine.py` 的 `compute_poi_marginal_value()` 函数
- `backend/core/policy_generator.py` 的 `theme_keyword_map` 生成逻辑（已存在，可能需要增强）

### 1.2 高德多模式路线规划
**问题**：当前固定单一交通方式（如"步行"），灵隐寺到西湖36分钟步行被硬塞进路线。实际用户会坐公交/打车。

**方案**：
- 新增 `backend/data/gaode_direction.py`，封装高德路径规划API（`v3/direction`）
- 修改 `backend/core/route_engine.py` 的 `estimate_travel_time()`
- 对每段 POI-to-POI，查询步行/骑行/公交/驾车四种方式的真实时间
- 如果用户偏好步行，但步行时间>30分钟，自动降级为"公交/打车"
- 在 `PlanSegment` 中记录每段的实际交通方式

**关键代码位置**：
- `backend/core/route_engine.py` 的 `estimate_travel_time()` 和 `_update_segment_times()`
- `backend/models/schemas.py` 的 `PlanSegment`（可能需要新增 `transport_mode` 字段）

**预期效果**：路线合理从 4-6分 → 7-8分

---

## 阶段二：预算硬约束（P1）

### 2.1 LLM批量补齐价格数据
**问题**：POI的 `price` 字段大量为 null/0。西湖景区门票、餐厅人均消费都没有录入。

**方案**：
- 新增 `scripts/enrich_poi_prices.py`
- 遍历所有POI，对 price 为 null/0 的，调用LLM批量查询真实价格
- 风景名胜类：查询门票价格
- 餐饮类：查询人均消费
- 结果写回 `data/{city}_pois.json`

### 2.2 候选池预过滤 + 引擎累加检查
**问题**：引擎在选POI时不检查累计花费，导致500元预算的路线花费1061元。

**方案**：
- **候选池层**：在 `_build_plan` 之前，过滤掉明显超预算的POI（如人均>300元的餐厅对于500元预算直接排除）
- **引擎层**：在 `preference_guided_greedy` 中维护 `current_total_cost`，加入新POI前检查 `current_total_cost + poi.price <= budget * 0.9`

**关键代码位置**：
- `backend/core/route_engine.py` 的 `preference_guided_greedy()` 和 `_build_plan()`

**预期效果**：预算控制从 1分 → 6-7分

---

## 阶段三：动态停留时间 + 用户超时选择（P1）

### 3.1 动态停留时间
**问题**：所有POI固定停留60分钟。寺庙60分钟合理，但观景台30分钟就够了，博物馆需要90分钟。

**方案**：
- 在 `parse_poi()` 或数据加载阶段，根据POI子类别设置 `suggested_duration`
- 规则：`寺庙=60, 公园=45, 博物馆=90, 观景台=30, 餐饮=60, 购物=45`
- 可由 Policy Generator 覆盖（通过 `hard_constraint_overrides` 或新增字段）

### 3.2 用户超时选择
**问题**：路线超时时系统不处理，直接返回超时的路线。

**方案**：
- 在 `build_route_plan()` 中，计算完成后检查是否超出 `end_time`
- 如果超时：标记 `is_overtime=True`，计算"需要删减X分钟"
- 在API返回中增加 `overtime_candidates` 字段：列出可删减的POI（按优先级排序，优先删减低匹配度/高时间的POI）
- 前端展示"路线超出X分钟，请选择删减"面板
- 用户勾选后调用已有的 `/api/plan/{id}/adjust?mode=arrange` 接口

**关键代码位置**：
- `backend/core/route_engine.py` 的 `build_route_plan()`
- `backend/main.py` 的 `/api/plan/{id}` 返回接口
- `frontend/index.html` 的新增超时删减面板

**预期效果**：时间可行从 2分 → 6-7分

---

## 阶段四：POI多样性软惩罚（P1）

**问题**：9个POI中7个是风景名胜，类型高度重复。

**方案**：
- 在 `compute_poi_marginal_value()` 中加入多样性惩罚
- 如果已选POI中同一类别占比 > 60%，则该类别新POI得分 × 0.7
- 不限制具体类别，任何类别过度集中都会被抑制
- 配合时段自然引导（午餐时段倾向餐饮）

**关键代码位置**：
- `backend/core/route_engine.py` 的 `compute_poi_marginal_value()`

**预期效果**：POI多样性从 1-3分 → 5-6分

---

## 验证方式

每阶段完成后运行：
```bash
python scripts/run_full_eval.py
```

对比5维度评分变化：
- 偏好对齐、路线合理、POI多样性、预算控制、时间可行
- 目标：综合评分从 2-3/10 → 6-7/10

---

## 关键设计原则（贯穿全部阶段）

1. **泛化性**：所有优化通过 Policy Generator 的参数化实现，不写死任何关键词或规则
2. **用户需求驱动**：引擎读取 `user_pref.theme_weights` 和 `policy.theme_keyword_map` 动态决策
3. **最小侵入**：优先修改单一函数（`compute_poi_marginal_value`、`estimate_travel_time`、`build_route_plan`），不重构核心贪心算法
