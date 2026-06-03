# 个性化画像系统深度优化计划

## 目标

将用户画像系统从"静态规则+手动维护"升级为"LLM驱动、自动沉淀、可追溯、可干预"的智能画像体系，并完成科学评测验证。

**本次计划新增核心议题：解决规则与LLM的边界问题，消除规则的固有局限性。**

---

## 关键设计决策

| 决策项 | 用户选择 | 说明 |
|--------|---------|------|
| 画像增量更新触发 | **每次请求都触发** | 每次规划请求后，LLM分析query与当前画像的差异，输出增量更新。实时性强，调用成本高。 |
| 消融实验维度 | **双层消融（推荐）** | 4组核心实验，聚焦规则vsLLM和画像有无两个维度 |
| 画像历史版本 | **保留历史版本（推荐）** | 新增 `profile_versions` 表，每次更新存快照，支持画像演变追溯 |

---

## 前置讨论：规则 vs LLM 的边界与局限

### 当前系统分工

| 模块 | 规则负责 | LLM负责 |
|------|---------|---------|
| 偏好解析 | `parse_preference_from_request()`：固定6个theme，默认0.25 | `parse_preference_from_llm()`：从raw_query提取，但仍强制输出6个theme |
| 画像融合 | `fuse_preferences()`：固定α=0.7加权 | — |
| 画像演化 | `evolve_profile()`：固定EMA学习率(0.5/0.1)，固定delta(0.15/0.05/0.1) | — |
| POI评分 | `compute_poi_marginal_value()`：硬编码加分（UGC±15，场景+10，情侣+20） | — |
| 路线构造 | `preference_guided_greedy()` + 2-opt：固定策略参数 | 推荐理由生成 |
| 方案差异化 | `STRATEGY_CONFIG`：三套固定配置（体验/效率/均衡） | — |
| 约束检查 | 时间窗口、预算、距离上限等硬性约束 | — |

### 规则的五大局限性

**L1. 固定6个theme维度**
- 用户说"我喜欢安静的地方，不喜欢人多的地方"→ 只能映射到"娱乐"低分，无法表达"安静vs热闹"这个新维度
- 用户说"想要有历史感的地方"→ "历史"不在6个theme中，LLM被迫硬塞进"文化"
- **本质**：用一个低维固定向量表征高维、开放的用户偏好空间

**L2. 固定融合权重α=0.7**
- 老用户说"今天我想换个风格试试"→ 历史画像仍占30%，过度抑制临时变化
- 新用户第一次说"帮我规划"→ α=0.7没问题，但如果他说"我平时喜欢美食，但今天赶时间"→ 应该让"今天赶时间"占更高权重
- **本质**：融合比例无法根据query的"临时性vs长期性"自适应

**L3. 固定评分加成系数**
- UGC情感分固定±15分：一个"特别在意口碑"的用户和一个"无所谓"的用户，UGC权重应该不同
- 场景匹配固定+10分：情侣看到"浪漫"标签+10，但"正在求婚的情侣"和"普通约会"对这个标签的敏感度不同
- 价格敏感>0.7时免费POI+10分：这个阈值和加分值都是硬编码的
- **本质**：评分函数是"一刀切"的，没有根据用户画像动态调整各维度的敏感度

**L4. 三套固定策略配置**
- "深度体验/高效省时/均衡推荐"是产品经理预设的，不是根据用户画像动态生成的
- "亲子+悠闲+不愿走路+预算充足"的最佳策略应该是"近郊高品质亲子路线"，不是三个预设之一
- **本质**：策略空间被人为压缩到3个点，丢失了画像→策略的连续映射

**L5. 画像演化固定delta**
- 选择"深度体验"就固定+0.15文化/自然，不考虑用户已经多偏爱文化了
- 反馈"like"就固定+0.1，不区分"非常喜欢"和"还行"
- **本质**：行为反馈被量化为固定步长，丢失了反馈强度信息

### LLM的不可替代性 vs 规则的不可替代性

**LLM不可替代（理解层）**：
- 理解任意自然语言描述的偏好（包括新维度、复合维度、负面偏好）
- 判断query的临时性vs长期性，动态决定融合比例
- 根据用户画像生成个性化的评分系数和策略配置
- 从行为序列中抽象出偏好模式（"用户每次都选有水的景点→可能喜欢水景"）

**规则不可替代（执行层）**：
- 硬性约束满足：时间窗口、预算上限、距离限制 → 数学问题，规则更可靠
- 大规模POI评分：对数百个POI逐一打分 → 规则O(n)高效，LLM O(n×API调用)不可行
- 路线优化（TSP近似）：2-opt是确定性算法，LLM无法保证找到近似最优解
- 稳定性：规则输出100%可复现，LLM有随机性

### 架构演进方向：LLM生成规则参数，规则执行

核心思路：**引入"LLM策略生成器"（LLM Policy Generator）**

```
用户query + 历史画像
    ↓
[LLM策略生成器] —— 一次LLM调用
    ↓
输出个性化规则参数包：
  - dynamic_theme_weights: 不限6维，自由维度+权重
  - fusion_alpha: 本次请求的融合比例
  - scoring_coefficients: POI评分各加成项系数
  - strategy_config: 定制化策略参数（替代固定三套）
    ↓
[规则引擎] —— 纯本地计算
    ↓
POI评分 → 贪心选择 → 2-opt优化 → 输出plan
```

**优势**：
- LLM只调用一次（生成参数），而非每个POI都调用
- 规则引擎仍然高效、确定、可解释
- 策略空间从"3套固定配置"扩展为"连续可调的参数空间"
- 用户画像的每个维度都可以影响最终评分的权重

---

## 方案选择

| 方案 | 核心思路 | 工作量 | 收益 |
|------|---------|--------|------|
| **方案A：渐进修补** | 保留现有架构，逐步开放限制（theme不限6维、α可由LLM调、评分系数可配置） | 中 | 解决L1-L3，不触及路线构造层 |
| **方案B：策略生成器重构（推荐）** | 引入LLM策略生成器，LLM输出完整参数包，规则引擎消费参数 | 高 | 彻底解决L1-L5，策略空间连续化，系统最灵活 |

**用户决策：方案B — LLM策略生成器重构**

---

## 方案B 详细设计：LLM策略生成器

### 核心架构

```
用户query + 历史画像 + 候选POI统计摘要
    ↓
[LLM策略生成器] —— 每次规划请求调用1次LLM
    ↓
输出 PlanningPolicy 对象（JSON）
    ↓
[规则引擎] —— 纯本地计算，100%确定性
    ↓
POI评分(用policy.coefficients) → 贪心选择(用policy.strategy) → 2-opt优化 → 输出plan
```

### PlanningPolicy 输出格式（JSON Schema）

```json
{
  "policy_version": "1.0",
  "reasoning": "用户是亲子出游，预算中等，不想走太远。偏好自然和科普类景点，对网红打卡不太感兴趣。",
  
  "preference_space": {
    "theme_weights": {
      "美食": 0.3,
      "自然": 0.9,
      "科普": 0.85,
      "亲子互动": 0.8,
      "网红打卡": 0.1,
      "历史文化": 0.5
    },
    "negative_themes": ["网红打卡", "高强度运动"],
    "traveler_type": "亲子",
    "pace_preference": "悠闲",
    "budget_level": "标准"
  },
  
  "fusion_config": {
    "alpha": 0.6,
    "alpha_reason": "用户明确说了'今天'带孩子去，临时性较强，但亲子偏好是长期稳定的"
  },
  
  "scoring_coefficients": {
    "ugc_sentiment_weight": 0.8,
    "scene_match_weight": 1.2,
    "price_sensitivity_weight": 0.5,
    "exploration_bonus_factor": 0.3,
    "distance_penalty_factor": 1.5,
    "time_efficiency_weight": 0.4
  },
  
  "strategy_config": {
    "max_distance_from_start_km": 20,
    "candidate_count": 30,
    "pref_match_boost": 1.2,
    "time_penalty_factor": 0.8,
    "max_travel_km_per_step": 8,
    "max_total_route_km": 25,
    "min_poi_count": 4,
    "two_opt_pref_weight": 0.6,
    "distance_weight": 0.5
  },
  
  "hard_constraint_overrides": {
    "must_visit": ["杭州动物园"],
    "avoid": ["爬山", "长时间排队"]
  }
}
```

### 关键设计决策（已确认）

**Q1. 自由维度如何与POI匹配？** ✅ **已确认：LLM生成维度→关键词映射**

策略生成器输出每个自由维度对应的关键词列表：
```json
{
  "theme_keyword_map": {
    "科普": ["博物馆", "科技馆", "自然教育", "天文馆", "海洋馆"],
    "亲子互动": ["儿童乐园", "动物园", "亲子", "互动体验", "手工"],
    "网红打卡": ["打卡", "网红", "拍照圣地", "出片"]
  }
}
```
评分时：POI.tags 与关键词列表做模糊匹配（包含即命中）。

优势：新维度完全由LLM决定，无需预设关键词表；召回率高于简单字符串匹配；无需离线维护POI标签。

**Q2. 与现有三套策略的关系？** ✅ **已确认：LLM生成三套定制化策略**

PlanningPolicy 中 `strategy_config` 变为数组，每个元素对应一个方案：
```json
{
  "strategies": [
    {
      "name": "深度体验",
      "description": "专注自然与科普，允许绕路去西溪湿地或科技馆",
      "config": { "pref_match_boost": 2.2, "max_travel_km_per_step": 12, ... }
    },
    {
      "name": "高效省时",
      "description": "集中在市区，优先地铁可达的景点",
      "config": { "pref_match_boost": 0.6, "max_travel_km_per_step": 4, ... }
    },
    {
      "name": "均衡推荐",
      "description": "兼顾自然体验和交通效率",
      "config": { "pref_match_boost": 1.2, "max_travel_km_per_step": 7, ... }
    }
  ]
}
```

**Q3. 评分系数的粒度？** ✅ **已确认：混合 — 全局系数 + 关键类别覆盖**

用户核心关切：关键类别怎么确定？POI评分系统怎么设定？规则涵盖不了所有情况，怎么引入LLM同时确保可靠性？

**回答：**

```json
{
  "scoring_coefficients": {
    "global": {
      "ugc_sentiment_weight": 0.8,
      "scene_match_weight": 1.2,
      "price_sensitivity_weight": 0.5,
      "exploration_bonus_factor": 0.3,
      "distance_penalty_factor": 1.5,
      "time_efficiency_weight": 0.4
    },
    "category_overrides": {
      "博物馆": { "ugc_sentiment_weight": 1.5, "scene_match_weight": 0.8 },
      "餐厅": { "price_sensitivity_weight": 1.2 }
    }
  }
}
```

**1. 关键类别怎么确定？**
- 不由人预设，由LLM根据画像动态推断
- LLM看到画像中"自然"=0.9、"科普"=0.85 → 推断关键类别 = ["公园","植物园","博物馆","科技馆"]
- 关键类别数量限制：最多3个（防止维度爆炸）
- 不在关键类别中的POI自动使用全局系数

**2. POI评分系统怎么设定？**
- LLM**不替代**评分逻辑，只**调整评分函数的参数**
- 现有评分函数结构保持不变（加权求和 + 时间/距离惩罚 + 硬性约束过滤）
- 变化：硬编码的加分值 → 乘以LLM输出的系数

示例改造（`compute_poi_marginal_value`）：
```python
# 改造前（硬编码）
marginal_value += poi.ugc_sentiment_score * 15

# 改造后（LLM参数化）
coef = policy.scoring_coefficients
ugc_weight = coef.category_overrides.get(poi.category, {}).get("ugc_sentiment_weight", coef.global["ugc_sentiment_weight"])
marginal_value += poi.ugc_sentiment_score * 15 * ugc_weight
```

**3. 怎么确保可靠性？**

| 保障层 | 机制 |
|--------|------|
| 结构约束 | LLM只输出系数，评分公式结构不变，保证计算稳定性 |
| 值域校验 | 所有系数裁剪到 [0.1, 3.0]，防止极端值 |
| 约束兜底 | 时间窗口、预算、距离上限等硬性约束仍由规则严格检查，LLM无法绕过 |
| Fallback | LLM输出异常（无法解析、超出值域）→ 自动回退到默认系数 |
| 可解释性 | 每个系数附带 `reason`，可追溯LLM为什么给博物馆UGC权重1.5 |

**Q4. 策略生成器的Prompt设计**

输入信息：
- 用户原始query
- 当前融合后的画像（theme_weights、traveler_type、pace、budget等）
- 候选POI的统计摘要（类别分布、距离分布、评分分布、UGC情感分布）— 避免塞入全部POI详情导致token爆炸
- 当前城市、时间约束、预算约束

输出约束：
- 严格JSON Schema（用Pydantic模型定义）
- 每个字段附带 `reason` 说明决策依据（用于调试和可解释性）
- temperature=0.3 保证稳定性
- 附带 few-shot 示例（2-3个典型画像的策略输出示例）

**Q5. 评测验证策略生成器的价值**

消融实验增加一组对比：
- **基线组（当前系统）**：固定三套策略 + 固定评分系数 + α=0.7
- **实验组（策略生成器）**：LLM生成三套定制策略 + 动态评分系数 + dynamic_alpha

额外指标：
- `strategy_diversity_score`：三套策略的POI重合度是否足够低（验证差异化是否有效）
- `policy_coherence_score`：LLM输出的策略配置与画像的一致性（由LLM自评）

---

## 用户深度追问与回答

### Q1. 自由维度是什么？策略生成器怎么生成策略？是固定映射还是LLM动态调整？

**自由维度** = 不限于预定义的6个theme（美食/拍照/文化/自然/购物/娱乐），LLM可以从用户query中**自由提取**用户关心的任何偏好维度。

举例：
- 用户说"我喜欢安静的地方，不喜欢人多的地方" → LLM提取自由维度 `"安静": 0.9`, `"热闹/人群": 0.1`
- 用户说"想要有历史感的地方" → LLM提取 `"历史感": 0.85`（不再被迫塞进"文化"）
- 用户说"网红打卡地不要" → LLM提取 `"网红打卡": 0.05` 作为负面维度

**策略生成方式 = LLM动态调整，不是固定映射。**

现有系统（固定映射）：
```python
STRATEGY_CONFIG = {
    "experience": {"pref_match_boost": 2.0, "max_travel_km_per_step": 15, ...},
    "efficiency": {"pref_match_boost": 0.5, "max_travel_km_per_step": 5, ...},
    "balanced": {"pref_match_boost": 1.0, "max_travel_km_per_step": 8, ...}
}
```

新系统（LLM动态生成）：
```python
# LLM根据用户画像 + query + 候选POI统计，动态输出每个策略的参数
policy.strategies[0].config = {
    "pref_match_boost": 2.2,      # LLM认为这个用户值得更高体验权重
    "max_travel_km_per_step": 12,  # 亲子用户不宜太远，所以比默认15低
    "time_penalty_factor": 0.7     # 悠闲节奏，时间惩罚降低
}
```

同一个"亲子"画像，不同query会产生不同策略：
- query="今天时间充裕，想深度玩" → 深度体验策略的 `max_travel_km_per_step=15`
- query="今天赶时间，就近逛逛" → 深度体验策略的 `max_travel_km_per_step=8`

### Q2. 三套定制化策略的区别怎么产生？怎么评测效果？

**区别产生的机制：**

LLM在生成策略时，内部遵循"差异化原则"：
- **体验策略**：高 `pref_match_boost` + 宽松距离限制 + 低时间惩罚 + 探索奖励
- **效率策略**：低 `pref_match_boost` + 严格距离限制 + 高时间惩罚 + 近距离奖励
- **均衡策略**：中间值 + 兼顾多样性和连续性

但这些数值不是固定的（如体验不一定是2.0），而是由LLM根据画像动态调整：
- 画像中"效率偏好"高 → 体验策略的 `pref_match_boost` 可能只调到1.5（而不是默认2.0）
- 画像中"预算紧张" → 效率策略的 `max_total_route_km` 可能压缩到10km

**评测方式：**

| 指标 | 说明 |
|------|------|
| **POI重合度（Jaccard）** | 三套策略选出的POI集合的交集/并集。如果三套重合度>0.8，说明差异化不足 |
| **LLM评价者评分** | 对每套方案分别给出5维度评分（偏好对齐/路线效率/多样性/实用性/整体），看三套是否有显著差异 |
| **策略描述一致性** | 检查LLM生成的 `strategies[i].description` 是否与实际参数一致（如描述说"远距离探索"但max_travel_km_per_step=3，则不一致） |
| **消融对比** | 固定三套策略（当前系统）vs LLM定制三套策略，对比LLM评价者平均分 |

### Q3. 全局系数 + 关键类别覆盖，权重怎么分配？怎么确保有效性？全局系数怎么确定？关键类别动态调整吗？

**权重分配机制：**

```python
def get_effective_coefficient(poi, coefficient_name, policy):
    """
    获取某个POI在某个系数上的有效值。
    优先级：类别覆盖 > 全局默认值
    """
    # 1. 查该POI的类别是否有覆盖系数
    category_coef = policy.scoring_coefficients.category_overrides.get(poi.category, {})
    if coefficient_name in category_coef:
        return category_coef[coefficient_name]
    
    # 2. 没有覆盖，使用全局系数
    return policy.scoring_coefficients.global.get(coefficient_name, 1.0)

# 使用示例（在compute_poi_marginal_value中）
ugc_weight = get_effective_coefficient(poi, "ugc_sentiment_weight", policy)
marginal_value += poi.ugc_sentiment_score * 15 * ugc_weight
```

**全局系数怎么确定？**

由LLM根据用户画像整体推断：
- 画像中 `willingness_to_queue=0.9`（不怕排队）→ LLM推断用户可能更信任网红店 → `ugc_sentiment_weight=1.2`
- 画像中 `price_sensitivity=0.8`（价格敏感）→ LLM推断用户对价格在意 → `price_sensitivity_weight=1.5`
- 画像中 `pace_preference="悠闲"` → LLM推断用户不赶时间 → `time_efficiency_weight=0.3`

**关键类别怎么确定？**

由LLM根据画像动态推断，每次规划请求重新计算：
1. LLM查看画像中theme_weights最高的2-3个维度
2. 将这些维度映射到POI类别（如"自然"→["公园","植物园","风景名胜区"]）
3. 为这些类别输出覆盖系数

例如：
```json
{
  "category_overrides": {
    "博物馆": { "ugc_sentiment_weight": 1.5, "scene_match_weight": 0.8 },
    "公园": { "exploration_bonus_factor": 1.3 }
  }
}
```

关键类别数量限制最多3个，防止维度爆炸。不在关键类别中的POI自动使用全局系数。

**怎么确保有效性？**

- 所有系数裁剪到 `[0.1, 3.0]`，防止极端值
- 评分公式中的基础加分值（15, 20, 10等）保持不变，系数只是缩放
- 即使LLM输出全部系数=0.1，评分仍然有效（只是所有个性化加成被抑制）
- 硬性约束（时间窗口、预算、距离上限）不受系数影响，始终严格检查

### Q4. 现有评分公式结构？LLM系数怎么改变它？默认系数怎么保证合理？"喜欢"vs"很喜欢"怎么量化？新维度怎么动态引入？LLM是否实际读取POI并参与选取？

**现有评分公式结构（基于route_engine.py代码）：**

```python
def compute_poi_marginal_value(poi, pref_match, travel_time, dist_m, user_pref, budget, strategy):
    # Layer 1: 基础评分（POI质量 + 偏好匹配 + 价格适配）
    base_score = (poi.rating or 3.5) / 5.0
    poi_value = (
        weights["experience"] * base_score +
        weights["preference_match"] * pref_match * pref_boost +
        weights["cost"] * (1 - poi.price / budget)
    )
    
    # Layer 2: 时间惩罚
    time_penalty = travel_time * pace_penalty * time_factor
    
    # Layer 3: 边际价值 = 综合价值 - 时间惩罚
    marginal_value = poi_value * 100 - time_penalty
    
    # Layer 4: 策略差异化加成（距离奖励/惩罚，硬编码）
    if strategy == "experience": ...  # 远距离探索奖励 +15, 高评分+15
    elif strategy == "efficiency": ...  # 近距离+25, 远距离惩罚
    else: ...  # 均衡微调
    
    # Layer 5: 个性化加成（硬编码）—— 这是最大问题！
    if user_pref.traveler_type == "情侣" and "浪漫" in poi.tags: marginal_value += 20
    if user_pref.traveler_type == "亲子" and "儿童" in poi.tags: marginal_value += 20
    if user_pref.price_sensitivity > 0.7 and poi.price == 0: marginal_value += 10
    
    # Layer 6: UGC加成（硬编码）
    if poi.ugc_sentiment_score != 0: marginal_value += poi.ugc_sentiment_score * 15
    if poi.ugc_scene_tags匹配人群: marginal_value += 10
    
    return marginal_value
```

**核心问题：Layer 5 的个性化加成是硬编码的条件判断，无法引入新维度。**

例如：LLM提取了新维度 `"安静": 0.9`，但现有代码中没有 `if "安静" in poi.tags: ...` 的判断，这个新维度就被丢弃了。

**解决方案：把Layer 5从"硬编码条件判断"重构为"动态维度匹配"。**

**改造后的Layer 5（动态维度评分）：**

```python
# 改造前（硬编码，无法引入新维度）
if user_pref.traveler_type == "情侣" and "浪漫" in poi.tags: marginal_value += 20
if user_pref.traveler_type == "亲子" and "儿童" in poi.tags: marginal_value += 20

# 改造后（动态，自动处理任意维度）
for dimension, weight in user_pref.theme_weights.items():
    # 查该维度对应的关键词（由LLM策略生成器提供）
    keywords = policy.theme_keyword_map.get(dimension, [dimension])
    
    # 计算POI与该维度的匹配度
    match_score = 0
    for kw in keywords:
        if kw in poi.tags or kw in (poi.category or "") or kw in (poi.sub_category or ""):
            match_score = 1.0  # 命中一个关键词即算匹配
            break
    
    if match_score > 0:
        # 维度权重越高、匹配度越高，加分越多
        # 基础加分值 = 25，由LLM系数缩放
        scene_weight = get_effective_coefficient(poi, "scene_match_weight", policy)
        marginal_value += weight * match_score * 25 * scene_weight
```

**这样新维度怎么引入？**

1. LLM解析query时提取新维度：`"安静": 0.9`
2. LLM策略生成器输出关键词映射：`"安静": ["安静", "清幽", "独处", "小众", "人少"]`
3. 评分公式自动遍历所有维度（包括新维度），无需修改代码
4. 如果POI的tags中有"清幽" → 匹配成功 → 加分

**哪些维度保留硬编码？**

- **必去点/避免点**：精确名称匹配，不需要动态维度
- **UGC情感分**：有专门的数值字段（-1~+1），计算逻辑特殊，保留专门处理
- **价格敏感度**：有阈值判断逻辑（>0.7才触发），保留但阈值可由LLM调整
- **时间/距离惩罚**：数学计算，不是维度匹配

**LLM系数怎么改变评分公式？**

公式结构不变，每个"硬编码值"变成 `"硬编码值 × LLM系数"`：

| 原有 | 改造后 |
|------|-------|
| `+20`（情侣浪漫加成） | `动态维度匹配`（已被统一处理） |
| `+15`（排队意愿加成） | `+15 * coef.global["queue_bonus_weight"]` |
| `+ poi.ugc_sentiment_score * 15` | `+ poi.ugc_sentiment_score * 15 * ugc_weight` |
| `pref_match_boost = 2.0` | `pref_match_boost = policy.strategies[0].config["pref_match_boost"]` |
| `time_penalty_factor = 2.0` | `time_penalty_factor = policy.strategies[1].config["time_penalty_factor"]` |

**默认系数怎么保证合理？**

- 默认系数 = `1.0`，即保持现有系统的行为完全不变
- 当LLM输出缺失、无法解析、或超出值域 `[0.1, 3.0]` 时，自动fallback到 `1.0`
- 动态维度匹配的默认行为：LLM不提供keyword_map → 用维度名本身作为关键词（如"安静"就匹配"安静"）

**"喜欢"vs"很喜欢"怎么量化？**

在**画像解析层面**解决，不在评分层面：

- LLM解析query时区分语言强度：
  - "我喜欢美食" → `theme_weights["美食"] = 0.75`
  - "我超级喜欢美食！一定要吃！" → `theme_weights["美食"] = 0.95`
  - "美食还行吧" → `theme_weights["美食"] = 0.5`

- 评分公式只把0.75或0.95这个数字转成POI得分
- 策略生成器看到 `美食=0.95` → 推断美食重度爱好者 → 调高相关系数

### Q5. LLM策略生成器是怎么生成策略的？LLM是否实际读取POI并参与选取？

这是方案B最核心的架构问题。需要分三层回答：

**（1）当前系统的POI评价完整流程**

```
用户query → LLM解析偏好(theme_weights等)
    ↓
候选POI池（数十~数百个）
    ↓
[规则评分] compute_preference_match() —— 计算POI tags与theme_weights的匹配度
    ↓
[规则评分] compute_poi_marginal_value() —— 综合评分（基础评分+偏好匹配+时间惩罚+策略加成+个性化加成+UGC加成）
    ↓
[规则选择] preference_guided_greedy() —— 按marginal_value排序，贪心选最高分POI
    ↓
[规则优化] preference_guided_two_opt() —— 2-opt调整顺序
    ↓
输出plan
```

**关键事实**：当前系统中，LLM**只参与第一步**（解析偏好），后续的POI评分、选择、优化全部由规则完成。LLM**不知道**候选POI具体有哪些，**不参与**任何POI的选取决策。

**（2）方案B中LLM策略生成器的角色**

方案B中LLM的位置：

```
用户query + 历史画像 + 候选POI统计摘要
    ↓
[LLM策略生成器] —— 调用1次LLM
    ↓
输出参数包（系数、策略配置、维度映射）
    ↓
[规则评分] 用LLM参数计算每个POI的分数
    ↓
[规则选择] 贪心 + 2-opt
    ↓
输出plan
```

**LLM读取什么？**
- **不读取**每个POI的详细信息（名称、地址、具体tags等）
- **读取**候选POI的**统计摘要**：
  ```json
  {
    "total_candidates": 87,
    "category_distribution": {"公园": 12, "博物馆": 8, "餐厅": 15, "景点": 22},
    "distance_distribution": {"0-3km": 35, "3-8km": 32, "8-15km": 15, "15km+": 5},
    "rating_distribution": {"4.5+": 45, "4.0-4.5": 30, "<4.0": 12},
    "ugc_sentiment_avg": 0.62,
    "top_tags": ["拍照", "自然", "美食", "文化", "亲子"]
  }
  ```

**为什么LLM不读取每个POI？**
1. **Token限制**：候选POI可能数百个，每个POI有名称、地址、tags、评分等，塞不进LLM上下文
2. **成本**：每次规划请求都要为数百个POI调LLM，成本不可接受
3. **延迟**：LLM推理慢，路线规划需要秒级响应
4. **可靠性**：路线优化涉及精确的时间/预算/距离约束，LLM容易出错

**（3）但用户的核心关切：LLM能不能更深入地参与POI选取？**

这是一个好问题。现有方案中LLM是"参数生成器"，但还有一种架构："粗排+精排"。

**架构对比：**

| 架构 | LLM角色 | 规则角色 | 优点 | 缺点 |
|------|---------|---------|------|------|
| **方案B-1（纯参数生成器）** | 生成评分系数和策略参数 | 为所有POI打分并选择 | 快、稳定、成本低 | LLM不了解具体POI的细节 |
| **方案B-2（粗排+精排）** | 在规则粗排后的Top-20中做最终选择 | 快速粗排出Top-20候选 | LLM能考虑具体POI特性 | 增加1次LLM调用，延迟增加 |
| **方案B-3（混合）** | 参数生成器 + 关键决策点精排 | 大部分POI评分和选择 | 平衡灵活性和效率 | 复杂度最高 |

**方案B-2（粗排+精排）的详细设计：**

```
用户query + 画像
    ↓
[LLM策略生成器] —— 输出参数包
    ↓
[规则粗排] 用LLM参数为所有POI打分，选出Top-20候选
    ↓
[LLM精排] 把Top-20 POI的详细信息 + 用户画像 输入LLM
    ↓
LLM输出：对这20个POI的个性化评分 + 推荐理由 + 排除理由
    ↓
[规则融合] 规则分数 × 0.6 + LLM精排分数 × 0.4 = 最终分数
    ↓
贪心选择 + 2-opt
```

**LLM精排的输入示例：**

```
用户画像：亲子出游，偏好自然和科普，预算300元，不想走太远

候选POI（Top-20）：
1. 杭州动物园 - tags:["亲子","动物","户外"] - rating:4.6 - price:20 - dist:5km - UGC:"孩子很喜欢，但周末人很多"
2. 浙江自然博物馆 - tags:["科普","博物馆","亲子"] - rating:4.8 - price:0 - dist:3km - UGC:"互动体验很好，适合小学生"
3. 西湖断桥 - tags:["拍照","文化","景点"] - rating:4.5 - price:0 - dist:8km - UGC:"人太多，不推荐节假日"
...

请根据用户画像，对每个POI给出：
- 个性化评分（0-100）：综合考虑画像匹配度、用户特殊需求、UGC中的负面信息
- 推荐理由（如果有）
- 排除理由（如果有）
- 输出严格JSON
```

**LLM精排的价值：**
- 能处理规则无法处理的复杂判断：如"西湖断桥评分4.5但UGC说人太多，对于带孩子的用户应该降分"
- 能考虑POI之间的协同关系：如"动物园和自然博物馆都在一个方向，可以一起去"
- 能识别规则遗漏的负面信息：如UGC中的"排队2小时"、"最近在装修"

**但LLM精排的挑战：**
- 增加1次LLM调用，延迟+2~5秒
- LLM可能产生幻觉（给不存在的POI高分）
- 需要校验LLM输出与规则输出的一致性

**推荐方案：B-3 混合架构**

默认使用**B-1（纯参数生成器）**，但在以下场景触发**B-2（LLM精排）**：
- 规则粗排后Top-20的分数差异很小（竞争激烈）
- 用户query中包含复杂的排除条件（如"不要人多的地方，但要有互动体验"）
- 候选POI中有大量UGC负面信息需要LLM综合判断

这样平衡了效率和灵活性：大多数请求走快速路径，复杂请求走精排路径。

### Q6. 参数生成了但POI tags里没有对应关键词怎么办？LLM既然调了搜索API为什么不能读取POI？

**问题1：参数生成了但POI里没有对应关键词**

这是一个真实风险。例如：
- LLM生成了维度 `"安静": 0.9`，关键词映射 `["安静", "清幽", "独处", "小众"]`
- 但候选POI的tags只有 `["风景", "自然", "公园", "西湖", "拍照"]`
- "清幽"没命中 → "安静"维度失效

**解决方案：**

1. **关键词映射要覆盖POI tags的常见同义词**
   - LLM策略生成器输出关键词时，不仅输出"安静"的近义词，还要输出POI数据中可能出现的相关词
   - 例如：`"安静": ["安静", "清幽", "独处", "小众", "人少", "宁静", "淡雅", "禅意", "隐居"]`

2. **利用现有同义词映射表**
   - 当前系统已有 `THEME_SYNONYMS`（自然→风景/山水/户外，文化→历史/古迹/博物馆等）
   - LLM生成的关键词映射可以与现有同义词表合并使用

3. **LLM精排作为兜底**
   - 如果关键词匹配召回率低，LLM精排阶段直接读取POI的完整信息（包括名称、描述、UGC内容）
   - LLM可以从POI名称"灵隐寺"推断出"清幽"，即使tags里没有这个词

**问题2：LLM既然调了搜索API获取POI，为什么不能读取POI？**

需要澄清两个不同的LLM调用阶段：

| 阶段 | LLM做什么 | 规则做什么 | 产生的数据 |
|------|----------|-----------|-----------|
| **阶段1：动态抓取** | 生成高德搜索查询（如"杭州 亲子 博物馆"） | 调用高德API获取POI原始数据 | 候选POI池（名称、位置、类别、评分、tags） |
| **阶段2：路线规划** | （当前）不参与；（方案B）生成评分参数 | 为POI评分、选择、构造路线 | 最终plan |

**LLM在阶段1并没有"读取"POI**。LLM只是把用户query翻译成搜索关键词，真正获取POI的是高德API。LLM看到的是用户query，不是POI列表。

**那能不能让LLM在阶段1之后、阶段2之前读取POI？**

可以，但受限于：
- 候选POI可能50~200个，每个POI有名称(10字)+地址(20字)+tags(5个)+评分+评论摘要(50字) ≈ 100字
- 200个POI = 20000字 ≈ 15000 tokens
- MiniMax-M3的上下文窗口可能只有8K或16K，塞不下全部POI详情

**解决方案：分层读取**

```
阶段1：动态抓取 → 候选POI池（200个）
    ↓
[规则粗筛] 按硬性约束过滤（时间窗口、预算、距离）→ 剩余80个
    ↓
[规则粗排] 用基础评分公式快速打分 → Top-20
    ↓
[LLM精排] 只读取Top-20的完整信息（名称、tags、UGC摘要、评分、距离）
           ≈ 20 × 100字 = 2000字 ≈ 1500 tokens ✓ 可以塞入LLM
    ↓
LLM输出20个POI的个性化评分和推荐理由
    ↓
融合规则分数和LLM分数 → 最终选择
```

这样LLM**确实读取了POI**，但不是全部200个，而是经过规则两轮筛选后的Top-20。这20个是"有资格进入路线"的POI，LLM只需要在这20个中做精细化判断。

**LLM精排能做什么规则做不到的事？**

| 能力 | 规则 | LLM精排 |
|------|------|---------|
| 根据tags匹配关键词 | ✅ 精确匹配 | ✅ 语义理解（如"灵隐寺"→"清幽"） |
| 理解UGC评论中的负面信息 | ❌ 只能看sentiment_score | ✅ 能理解"排队2小时""最近在装修" |
| 考虑POI之间的协同关系 | ❌ 独立打分 | ✅ "动物园和博物馆在同一方向" |
| 处理复杂排除条件 | ❌ 简单关键词匹配 | ✅ "不要人多的，但要有互动体验" |
| 考虑用户的隐含需求 | ❌ 只看显性画像 | ✅ "带孩子去博物馆，最好有休息区" |

**结论**：
- 如果追求**速度**（<3秒响应）：纯参数生成器（B-1），LLM不读取POI
- 如果追求**质量**（允许5~8秒响应）：粗排+精排（B-2/B-3），LLM读取Top-20 POI做精细化判断
- **用户决策**：**所有情况都使用LLM精排**（见下方Q7）

---

### Q7. 用户最终决策汇总

**决策1：架构模式 —— LLM策略生成器 + 规则粗筛 + LLM精排（全部请求）**

所有规划请求都走完整流程：
```
用户query + 画像
    ↓
[LLM策略生成器] —— 输出参数包（自由维度、系数、策略配置）
    ↓
[规则粗筛] 硬性约束过滤（时间、预算、距离）
    ↓
[规则粗排] 用LLM参数快速打分 → Top-20
    ↓
[LLM精排] —— 所有请求都触发
    读取Top-20 POI完整信息，输出个性化评分 + 推荐理由
    ↓
融合分数 → 贪心选择 → 2-opt → 输出plan
```

**决策2：自由维度 —— LLM动态提取，不限6个固定theme**

LLM从query中自由提取用户关心的维度，输出 `theme_keyword_map` 用于POI匹配。评分公式改为动态维度遍历。

**决策3：三套策略 —— LLM动态生成三套定制化策略配置**

每个策略的参数（pref_match_boost、max_travel_km_per_step等）都由LLM根据画像动态输出，不是固定值。

**决策4：评分系数 —— 混合：全局系数 + 关键类别覆盖（最多3个）**

全局系数由LLM根据画像整体推断，关键类别由LLM根据高权重维度动态推断。

**决策5：动态维度评分 —— 把Layer 5从硬编码条件改为动态维度遍历**

```python
for dimension, weight in user_pref.theme_weights.items():
    keywords = policy.theme_keyword_map.get(dimension, [dimension])
    match_score = 1.0 if any(kw in poi.tags for kw in keywords) else 0
    if match_score > 0:
        marginal_value += weight * match_score * 25 * scene_weight
```

**决策6：精排触发 —— 全部请求都走LLM精排**

不再区分快速路径和精排路径。每次规划请求，规则粗排后Top-20都送入LLM精排。

**关于subagent/多子进程：**

Top-20 POI精排只需要1次LLM调用（约1500 tokens），不需要拆分成多个子进程。如果未来POI池扩展到500+，可以考虑：
- 规则粗排分片并行（多线程处理不同区域的POI）
- 但LLM精排始终只处理Top-20，保持单调用

---

### Q8. 备选池功能 + 方案卡片增强

**新增需求1：Top-40备选池，用户可查看并手动选择**

**设计：**

```
规则粗排 → 产出Top-40备选POI
    ↓
其中Top-20送入LLM精排 → 生成路线
    ↓
Top-40全部返回给前端作为"备选池"
    ↓
用户可：
  - 查看备选池中的POI（含评分、距离、价格、UGC摘要）
  - 勾选想加入的POI（自动加入must_visit）
  - 取消已选中的POI（加入avoid）
    ↓
重新规划（调用已有 /api/plan/{requestId}/adjust 接口）
```

**API扩展：**
- `GET /api/plan/{requestId}/candidates`：返回本次规划的Top-40备选POI列表
- `POST /api/plan/{requestId}/adjust`：已有接口，增强为支持两种模式：
  - `mode="replan"`：用新约束重新跑完整规划（现有行为）
  - `mode="arrange"`（默认）：在已有方案基础上增量编排，只调整局部

**增量编排（arrange模式）设计：**

当用户从备选池选择/取消POI时，不重新生成整个方案，只在已有路线上做局部调整：

```
已有方案：A → B → C → D
    ↓
用户从备选池选中E
    ↓
[增量编排]
  1. 找到已有方案中距离E最近的POI（假设是B）
  2. 将E插入到B之后：A → B → E → C → D
  3. 对插入点前后做局部2-opt优化
  4. 重新计算时间（到达/离开时间）
  5. 检查约束（预算、结束时间）
    ↓
更新后的方案：A → B → E → C → D
```

**删除POI**：直接从路线中移除，重新计算后续时间，不做路线重排。

**替换POI**：删除旧POI，新POI插入到相同或最近位置。

**为什么用增量编排而不是重新规划？**
- 用户可能对方案大部分满意，只想微调1~2个POI
- 重新规划可能导致用户喜欢的POI被替换掉（方案"大变样"）
- 增量编排更符合"编辑"心理，用户有掌控感

**备选池POI信息：**
```json
{
  "candidate_pool": [
    {
      "poi": { /* POI完整信息 */ },
      "rule_score": 85.3,
      "llm_score": 78.5,
      "is_selected": true,
      "is_in_plan": true,
      "reason": "匹配你的自然偏好，距离适中"
    }
  ]
}
```

**新增需求2：方案卡片包含景点图片**

**现状：**
- POI模型已有 `photos: List[str]` 字段
- 前端已有图片展示逻辑（`poi.photos[0]`），但可能有缺失或fallback不美观

**优化方案：**
- 后端确保每个POI返回时 `photos` 字段非空（已有图片URL或默认占位图）
- 前端卡片增加图片展示区域，含懒加载和错误fallback
- 备选池中的POI卡片同样展示图片
- 图片尺寸统一，适配移动端和桌面端

**卡片信息增强（从简陋到丰富）：**

| 信息 | 当前 | 增强后 |
|------|------|-------|
| 图片 | 可能有，可能空白 | 必有图片（或优雅占位图） |
| 名称 | ✅ 有 | ✅ 有 |
| 评分 | ✅ 有 | ✅ 有 + 星级可视化 |
| 价格 | ✅ 有 | ✅ 有 + "免费"/"¥XX"标签 |
| 距离 | ❌ 无 | 增加距离起点距离 |
| UGC摘要 | ❌ 无 | 增加UGC情感标签 + 近期预警 |
| 推荐理由 | ✅ 有 | 增加LLM精排的个性化推荐理由 |
| 标签 | ✅ 有 | 增加用户匹配标签高亮 |

---

---

## 阶段A：画像初始化集成注册 + 画像CRUD（第1轮）

### A1. 注册接口扩展

**文件**: `backend/models/auth_schemas.py`
- `RegisterRequest` 新增可选字段 `profile_text: Optional[str]`

**文件**: `backend/main.py`（`/api/auth/register`）
- 注册成功后，若 `profile_text` 非空：
  1. 调用 `engine.init_profile_from_text(profile_text)` 生成 `UserPreference`
  2. 调用 `engine.save_profile_to_db(user_id, "registered", preference)` 持久化
  3. 记录日志 `[Register] 用户{user_id}通过文本初始化画像`
- 若 `profile_text` 为空：保持现有行为（创建空画像）

### A2. 画像可查看可修改API

**文件**: `backend/models/schemas.py`
- 新增 `ProfileUpdateRequest(BaseModel)`：包含所有 `UserPreference` 字段，全部可选

**文件**: `backend/main.py`
- 新增 `PUT /api/user/profile`：
  - 接收 `ProfileUpdateRequest`，校验字段范围
  - 直接覆盖更新 `user_profiles` 表中对应记录
  - 同时向 `profile_versions` 插入旧版本快照（见阶段B）
  - 返回更新后的完整画像
- 新增 `GET /api/user/profile/history`：
  - 返回该用户的画像版本历史列表（时间、变更摘要）

**文件**: `backend/db/models.py`
- `UserProfileDAO` 新增 `update_fields(user_id, user_type, **kwargs)` 方法

---

## 阶段B：对话画像沉淀 + 版本历史（第2轮）

### B1. 增量画像提取引擎

**文件**: `backend/core/personalization.py`

新增方法 `extract_profile_delta(raw_query: str, current_pref: UserPreference) -> ProfileDelta`：

1. **LLM Prompt设计**：
   - 输入：用户原始query + 当前画像JSON
   - 任务：分析本次query是否透露出新的长期偏好，或修正了旧偏好
   - 输出格式：
     ```json
     {
       "has_change": true,
       "theme_weights_delta": {"美食": 0.15},
       "traveler_type": null,
       "pace_preference": null,
       "budget_level": null,
       "price_sensitivity_delta": 0,
       "willingness_to_queue_delta": 0,
       "willingness_to_walk_delta": 0,
       "reason": "用户再次提到想吃当地特色，美食偏好提升"
     }
     ```
   - 约束：只输出有意义的变更，无变化时 `has_change=false`；delta范围 [-0.3, 0.3]

2. **增量应用策略**（平滑更新）：
   - 新值 = 旧值 + delta × `learning_rate`
   - `learning_rate = 0.3`（每次更新只吸收30%的增量，避免震荡）
   - 结果裁剪到合理范围（如 theme_weights 归一化到和为1或各自0-1）

3. **触发位置**：
   - 在 `backend/services/planner.py` 的规划流程末尾（plan生成成功后）
   - 调用链：`extract_profile_delta(raw_query, historical_pref)` → 若 `has_change` → `save_profile_to_db` + `save_version`

### B2. 画像版本历史表

**文件**: `backend/db/models.py`

新增表 `profile_versions`：
```sql
CREATE TABLE IF NOT EXISTS profile_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    user_type TEXT NOT NULL,
    theme_weights_json TEXT,
    traveler_type TEXT,
    pace_preference TEXT,
    budget_level TEXT,
    price_sensitivity REAL,
    willingness_to_queue REAL,
    willingness_to_walk REAL,
    change_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

新增 `ProfileVersionDAO`：
- `create(user_id, user_type, profile_dict, change_reason)`
- `list_by_user(user_id, user_type, limit=20)`

### B3. 画像演化的双轨制

最终画像更新来源有两个，合并为统一接口 `update_profile(user_id, user_type, delta_dict, source, reason)`：

| 来源 | 更新方式 | 触发时机 | learning_rate |
|------|---------|---------|--------------|
| 行为驱动（EMA） | `evolve_profile()` | 用户选择plan/反馈POI | 0.5（新）/ 0.1（旧） |
| 对话驱动（LLM增量） | `extract_profile_delta()` | 每次规划请求后 | 0.3 |
| 手动修改 | `PUT /api/user/profile` | 用户主动调用 | 1.0（直接覆盖） |

两个自动来源的更新都通过 `update_profile` 接口写入，并自动创建版本快照。

---

## 阶段C：评测增强 — LLM评价者 + 消融实验 + 文档化（第3轮）

### C1. 评测结果持久化

**文件**: `backend/core/personalization_eval.py`

重构 `run_batch_evaluation()`：
1. 每次运行生成唯一的 `eval_run_id = uuid4().hex[:8]` + 时间戳
2. 结果写入两个文件：
   - `data/eval_runs/{eval_run_id}_detail.json`：每条测试用例的完整输入输出（query、画像、三套plan的POI列表和得分）
   - `data/eval_runs/{eval_run_id}_summary.md`：Markdown汇总报告

**目录结构**：
```
data/eval_runs/
  20240602_143022_a7f3b2d1_detail.json
  20240602_143022_a7f3b2d1_summary.md
```

### C2. LLM自动评价者

**文件**: `backend/core/personalization_eval.py`

新增 `evaluate_plan_with_llm(plan, query, profile_name) -> PlanQualityScore`：

1. **输入**：一条规划方案（POI列表+推荐理由+tips）、原始query、用户画像描述
2. **LLM Prompt**：
   - 角色：旅行规划质量评估专家
   - 评估维度（1-5分）：
     - `preference_alignment`：方案是否符合用户偏好
     - `route_efficiency`：路线是否合理（不走回头路、时间分配得当）
     - `diversity`：POI类型是否丰富不重复
     - `practicality`：交通、预算、排队等现实约束是否满足
     - `overall`：整体满意度
   - 要求：每个维度给出分数（1-5）和一句话理由
   - 输出：严格JSON

3. **集成到评测流程**：
   - 对每组实验（规则/LLM/融合）生成的plan，都调用LLM评价
   - 汇总各维度平均分，作为plan质量的第二指标（第一指标仍是POI重合度Jaccard）

### C3. 消融实验设计

**双层消融，4组实验**：

控制变量：固定相同的候选POI池、相同的query、相同的约束条件

| 组号 | 偏好解析 | 画像融合 | 说明 |
|------|---------|---------|------|
| A（基线） | 规则（preferences=[]） | ❌ | 纯规则，无画像 |
| B | LLM解析 | ❌ | LLM理解query，无历史画像 |
| C | 规则 | ✅ | 规则+画像融合 |
| D（完整） | LLM解析 | ✅ | LLM+画像融合（生产环境配置） |

**评测指标**：
1. **POI差异度**：Jaccard距离衡量各组plan之间的POI集合差异
2. **路线质量分**：LLM评价者的5维度平均分
3. **画像增益**：D组 vs B组 的质量分差（衡量画像带来的提升）
4. **LLM增益**：B组 vs A组 的质量分差（衡量LLM解析带来的提升）

**运行方式**：
```python
run_ablation_study(
    test_queries=MOCK_QUERIES,  # 6种模拟画像 × 2条query = 12条
    candidates=FIXED_CANDIDATES,  # 固定候选池
    output_dir="data/eval_runs"
)
```

### C4. 评测报告格式

**Markdown报告模板**：
```markdown
# 个性化消融实验报告
**运行ID**: {eval_run_id}  
**时间**: {timestamp}  
**测试用例数**: {n_cases}

## 1. 整体统计
| 实验组 | 平均POI数 | 偏好对齐分 | 路线效率分 | 多样性分 | 实用性分 | 综合分 |
|--------|----------|-----------|-----------|---------|---------|-------|
| A 规则无画像 | ... | ... | ... | ... | ... | ... |
| B LLM无画像 | ... | ... | ... | ... | ... | ... |
| C 规则有画像 | ... | ... | ... | ... | ... | ... |
| D LLM+画像 | ... | ... | ... | ... | ... | ... |

## 2. 关键发现
- **LLM增益**: D vs B = +{x}分（画像带来的提升）
- **画像增益**: B vs A = +{y}分（LLM解析带来的提升）
- **画像与LLM的协同效应**: ...

## 3. 典型案例分析
### 案例1: {profile_name} - {query}
- A组选中: [POI列表]
- B组选中: [POI列表]
- D组选中: [POI列表]
- LLM评价理由: ...

## 4. 附录：详细数据
[链接到 detail.json]
```

---

## 阶段D：端点集成与测试（第4轮）

### D1. Planner集成画像增量更新

**文件**: `backend/services/planner.py`
- 在 `plan()` 方法末尾（plan生成成功且 `user_id` 非空时）：
  ```python
  # 对话画像沉淀
  delta = self.personalization.extract_profile_delta(
      raw_query=request.raw_query,
      current_pref=historical_pref
  )
  if delta and delta.has_change:
      self.personalization.update_profile(
          user_id=user_id,
          user_type=user_type,
          delta=delta,
          source="conversation",
          reason=delta.reason
      )
  ```

### D2. 测试验证

1. **单元测试**：
   - `test_extract_profile_delta()`：验证LLM增量提取的JSON解析和delta应用逻辑
   - `test_profile_versioning()`：验证版本历史正确记录
   - `test_register_with_profile_text()`：验证注册带画像文本的完整流程

2. **端到端测试**：
   - 注册用户并传入 `profile_text`
   - 查询画像API确认LLM正确生成
   - 发起两次不同的规划请求
   - 查询画像历史，确认有版本记录
   - 手动PUT修改画像，确认版本再增一条

3. **评测运行**：
   - 运行消融实验，确认4组结果均产出
   - 检查 `data/eval_runs/` 下有正确的JSON和Markdown文件

---

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/models/auth_schemas.py` | 修改 | `RegisterRequest` 加 `profile_text` |
| `backend/models/schemas.py` | 修改 | 新增 `ProfileUpdateRequest`, `ProfileDelta` |
| `backend/db/models.py` | 修改 | 新增 `profile_versions` 表, `ProfileVersionDAO`, `UserProfileDAO.update_fields` |
| `backend/core/personalization.py` | 修改 | 新增 `extract_profile_delta`, `update_profile`, 双轨画像更新 |
| `backend/core/personalization_eval.py` | 重写 | LLM评价者、消融实验、结果文档化 |
| `backend/services/planner.py` | 修改 | 集成对话画像沉淀 |
| `backend/main.py` | 修改 | 注册画像初始化、画像CRUD端点 |
| `tests/test_personalization.py` | 新增 | 单元测试（增量提取、版本历史、注册流程） |

---

## 风险与回退

| 风险 | 缓解措施 |
|------|---------|
| LLM调用过多（每次请求+评测）导致429 | 画像增量提取使用轻量prompt，限制max_tokens；评测可配置跳过LLM评价者 |
| 画像漂移（LLM过度更新） | `learning_rate=0.3` + delta范围限制 + 版本历史可追溯，可随时回滚 |
| 注册时LLM生成画像失败 | fallback：创建空画像，前端提示用户后续完善 |
| 画像版本表膨胀 | `ProfileVersionDAO` 提供 `prune_old_versions(keep=50)` 定期清理 |
| 评测LLM评价者主观不稳定 | 同一plan多次评价取平均；人工抽查校验 |

---

## 验收标准

- [ ] 注册接口支持 `profile_text`，空画像 → LLM生成 → 数据库存储，全流程通
- [ ] `GET/PUT /api/user/profile` 可查看和修改画像，PUT后版本历史+1
- [ ] 每次规划请求后，画像若有变化自动记录到版本历史
- [ ] 消融实验运行完成，产出4组对比数据 + Markdown报告
- [ ] LLM评价者对plan给出5维度评分，评分有区分度
- [ ] 所有新增代码通过单元测试和至少1次端到端测试

---

## 附录：开发提示词（用于下一个会话）

### 项目背景

- **项目**：智能旅行规划系统（杭州本地游）
- **技术栈**：FastAPI + Python 3.12 + SQLite + 高德Web API + MiniMax-M3 LLM
- **当前状态**：已有完整的路线规划系统（贪心+2-opt），但个性化依赖固定规则
- **目标**：引入LLM策略生成器，让LLM动态生成个性化参数，规则引擎用参数执行

### 核心架构

```
用户query + 历史画像 + 候选POI统计摘要
    ↓
[LLM策略生成器] —— 1次LLM调用
    ↓
输出 PlanningPolicy（参数包）
    ↓
[规则粗筛] 硬性约束过滤
    ↓
[规则粗排] 用LLM参数为所有POI打分 → Top-40
    ↓
Top-20 送入 [LLM精排] —— 读取POI详情，输出个性化评分
    ↓
融合分数 → 贪心选择 → 2-opt → 输出plan + Top-40备选池
```

### 已确认的设计决策

1. **自由维度**：不限6个固定theme，LLM从query自由提取任何维度，输出 `theme_keyword_map`
2. **动态维度评分**：把Layer 5从硬编码条件改为遍历所有维度做动态匹配
3. **三套策略**：LLM动态生成三套定制化策略配置（体验/效率/均衡），参数由画像决定
4. **评分系数**：混合 — 全局系数 + 关键类别覆盖（最多3个关键类别）
5. **LLM精排**：所有请求都触发，读取Top-20 POI详细信息做精细化判断
6. **备选池**：保留Top-40返回给前端，用户可手动选择/取消
7. **增量编排**：`mode="arrange"` 在已有方案基础上局部插入/删除，不重新规划
8. **卡片增强**：图片必展示 + 距离 + UGC摘要 + LLM推荐理由 + 标签高亮

### 实施优先级

**P0（核心 — 必须先做）**
1. **LLM策略生成器**：`backend/core/policy_generator.py`
   - Prompt设计（输入：query+画像+POI统计摘要）
   - 输出：PlanningPolicy Pydantic模型
   - 包含：自由维度权重、fusion_alpha、全局系数、关键类别覆盖、三套策略配置
2. **动态维度评分**：改造 `compute_poi_marginal_value()`
   - 把硬编码条件改为遍历theme_weights的动态匹配
   - 保留UGC情感分、价格敏感度等特殊维度的专门处理
3. **LLM精排**：`backend/core/llm_reranker.py`
   - 输入：Top-20 POI详细信息 + 用户画像
   - 输出：20个POI的个性化评分 + 推荐理由/排除理由

**P1（重要 — 做完P0后做）**
4. **备选池API**：`GET /api/plan/{requestId}/candidates`
5. **增量编排**：改造 `POST /api/plan/{requestId}/adjust` 支持 `mode=arrange`
6. **卡片增强**：前端POI卡片增加图片、距离、UGC摘要、推荐理由

**P2（增强 — 有余力时做）**
7. **画像初始化集成注册**：注册时支持 `profile_text` 生成初始画像
8. **画像CRUD**：`GET/PUT /api/user/profile` + 版本历史
9. **对话画像沉淀**：每次规划请求后提取增量更新
10. **评测增强**：LLM评价者 + 消融实验 + 报告文档化

### 关键技术细节

**PlanningPolicy 输出格式：**
```python
class PlanningPolicy(BaseModel):
    reasoning: str  # LLM决策理由
    preference_space: dict  # 自由维度权重 + keyword_map
    fusion_config: dict  # alpha + alpha_reason
    scoring_coefficients: dict  # global + category_overrides
    strategies: List[StrategyConfig]  # 三套定制化策略
```

**动态维度评分公式：**
```python
for dimension, weight in user_pref.theme_weights.items():
    keywords = policy.theme_keyword_map.get(dimension, [dimension])
    match_score = 1.0 if any(kw in poi.tags for kw in keywords) else 0
    if match_score > 0:
        scene_weight = get_coefficient(poi, "scene_match_weight", policy)
        marginal_value += weight * match_score * 25 * scene_weight
```

**系数有效性保障：**
- 所有系数裁剪到 `[0.1, 3.0]`
- 默认系数 = 1.0（保持现有行为）
- LLM输出异常时自动fallback

**增量编排算法：**
```python
def arrange_plan(existing_segments, add_poi, remove_poi_names):
    # 1. 删除指定POI
    segments = [s for s in existing_segments if s.poi.name not in remove_poi_names]
    # 2. 添加新POI：找到距离最近的插入点
    if add_poi:
        best_idx = find_nearest_insert_position(segments, add_poi)
        segments.insert(best_idx, create_segment(add_poi))
    # 3. 局部2-opt优化（只优化插入点附近）
    local_optimize(segments, window=5)
    # 4. 重新计算时间
    recalculate_times(segments)
    return segments
```

### 需要注意的问题

1. **Token限制**：策略生成器输入用POI统计摘要，精排只处理Top-20
2. **LLM返回think标签**：需增加清理逻辑
3. **Windows编码**：控制台输出中文可能显示为�，文件读写用utf-8
4. **LLM速率限制**：MiniMax 429 TPM限制，注意调用间隔
5. **POI图片**：POI模型已有 `photos: List[str]`，确保返回时非空

### 验收标准

- [ ] 策略生成器输出有效参数包，且参数与画像一致
- [ ] 动态维度评分能处理LLM新提取的自由维度
- [ ] LLM精排给出有区分度的评分（最高分和最低分差>20分）
- [ ] 备选池API返回Top-40，含rule_score和llm_score
- [ ] 增量编排能在已有方案基础上插入POI，不破坏已有POI顺序
- [ ] 卡片展示图片、距离、UGC摘要、推荐理由
