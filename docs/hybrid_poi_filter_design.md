# 混合 POI 筛选架构设计文档

## 目标

将**规则化筛选**（硬约束、速度快）与 **LLM 语义筛选**（软偏好、理解力强）有机结合，实现：
- 简单场景：纯规则，毫秒级响应
- 复杂场景：规则+LLM，兼顾速度与精准度
- 自动决策：系统自行判断应该走哪条路径

---

## 一、两种筛选能力的分工

| 维度 | 规则化筛选 | LLM 语义筛选 |
|------|-----------|-------------|
| **处理对象** | 硬约束（距离、预算、营业时间、必去/避开） | 软偏好（"吃辣""人少""适合发朋友圈""有历史感"） |
| **响应速度** | < 10ms | 2-10s（取决于batch size） |
| **成本** | 零 API 成本 | 每次调用消耗 Token |
| **可解释性** | 极高（条件明确） | 高（有推荐理由） |
| **准确率** | 100%（确定性逻辑） | ~90%（需校验） |
| **适用场景** | 结构化输入、常规需求 | 自然语言、复杂/个性化需求 |

---

## 二、三层决策架构

```
用户输入
    │
    ▼
┌─────────────────────────────────────────┐
│  Layer 1: 需求解析器 (Query Analyzer)    │
│  判断用户需求的复杂度，决定后续路径        │
└─────────────────────────────────────────┘
    │
    ├─ 简单需求 ──→ 路径A: 纯规则筛选
    │
    ├─ 中等需求 ──→ 路径B: 规则粗筛 → LLM精筛
    │
    └─ 复杂需求 ──→ 路径C: 规则硬约束 + LLM全量重排
```

### 2.1 Layer 1: 需求复杂度判定

```python
class QueryComplexity(Enum):
    SIMPLE = "simple"      # 纯规则即可
    HYBRID = "hybrid"      # 规则+LLM
    COMPLEX = "complex"    # LLM主导

def analyze_query_complexity(request: PlanRequest) -> QueryComplexity:
    """
    判定需求复杂度，决定筛选路径
    """
    # 有自然语言query且包含规则外关键词 → 复杂
    if request.raw_query:
        hidden_needs = extract_hidden_needs(request.raw_query)
        if len(hidden_needs) > 0:
            return QueryComplexity.COMPLEX
        # 自然语言但只包含规则内关键词 → 中等
        return QueryComplexity.HYBRID
    
    # 无自然语言，只有结构化标签
    if request.preferences and len(request.preferences) > 0:
        # 检查是否全是预设标签
        known_tags = {"美食", "拍照", "文化", "自然", "购物", "娱乐"}
        if set(request.preferences).issubset(known_tags):
            return QueryComplexity.SIMPLE
        return QueryComplexity.HYBRID
    
    # 无任何偏好 → 最简单
    return QueryComplexity.SIMPLE
```

**复杂度判定规则：**

| 条件 | 复杂度 | 说明 |
|------|--------|------|
| 无 raw_query，preferences 为空 | SIMPLE | 默认推荐 |
| 无 raw_query，preferences 全是预设标签 | SIMPLE | 规则匹配足够 |
| 有 raw_query，但只包含预设标签同义词 | HYBRID | 先用规则，LLM辅助验证 |
| 有 raw_query，包含规则外需求 | COMPLEX | LLM主导筛选 |
| 有 must_visit / avoid 且 raw_query 复杂 | COMPLEX | 多约束混合 |

**规则外关键词示例：**
```python
HIDDEN_NEED_KEYWORDS = [
    "吃辣", "不吃辣", "清淡", "重口味",
    "人少", "安静", "不拥挤", "避开人流",
    "适合发朋友圈", "网红", "出片", "拍照好看",
    "有历史感", "古老", "传统", "文化底蕴",
    "适合约会", "浪漫", "私密",
    "带娃", "适合孩子", "亲子互动",
    "便宜", "性价比高", "实惠", "不贵",
    "高端", "豪华", "有档次",
    "夜景", "晚上", "夜生活",
]
```

---

## 三、三条筛选路径详解

### 路径A: 纯规则筛选（SIMPLE）

```python
def filter_pois_rule_only(
    pois: List[POI],
    user_pref: UserPreference,
    constraints: RouteConstraints
) -> List[POI]:
    """
    纯规则筛选，零LLM调用
    流程：硬约束过滤 → 偏好匹配打分 → 排序取TopN
    """
    # Step 1: 硬约束过滤
    candidates = [p for p in pois if hard_constraint_check(p, constraints)]
    
    # Step 2: 偏好匹配打分
    scored = []
    for p in candidates:
        match = compute_preference_match(p.tags, user_pref.theme_weights)
        crowd = compute_crowd_match(p.suitable_for, user_pref.traveler_type)
        score = match * 0.6 + crowd * 0.4 + (p.rating or 3.5) / 5.0 * 0.3
        scored.append((p, score))
    
    # Step 3: 排序取Top 30
    scored.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in scored[:30]]
```

**适用场景：**
- 用户只点了"美食+拍照"两个标签
- 没有自然语言描述
- 常规出行，无特殊要求

**性能：** 10ms 内完成

---

### 路径B: 规则粗筛 → LLM精筛（HYBRID）

```python
def filter_pois_hybrid(
    pois: List[POI],
    request: PlanRequest,
    user_pref: UserPreference,
    constraints: RouteConstraints
) -> List[POI]:
    """
    混合筛选：规则先过滤硬约束，LLM只处理软偏好
    """
    # Step 1: 规则硬约束过滤（快速排除大量POI）
    rule_filtered = hard_constraint_filter(pois, constraints)
    # 结果：250条 → 80条
    
    # Step 2: 规则偏好预打分，取Top 50
    rule_scored = rule_pre_score(rule_filtered, user_pref)
    candidates = [p for p, _ in rule_scored[:50]]
    
    # Step 3: LLM精筛（只处理软偏好）
    llm_results = call_llm_filter(
        pois=candidates,
        user_query=request.raw_query,
        context=build_context(request),
        focus="soft_preference_only"  # 告诉LLM只关注软偏好
    )
    
    # Step 4: 融合分数
    # 最终分数 = 规则分数 × 0.4 + LLM分数 × 0.6
    final_scored = []
    for p in candidates:
        rule_score = rule_scored_dict.get(p.poi_id, 50)
        llm_score = llm_results_dict.get(p.poi_id, 50)
        final_score = rule_score * 0.4 + llm_score * 0.6
        final_scored.append((p, final_score))
    
    final_scored.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in final_scored[:30]]
```

**适用场景：**
- 用户输入了自然语言，但需求不算特别复杂
- 例如："北京好吃的地方，不要太贵"
- "好吃"→规则可处理（美食标签），"不要太贵"→规则可处理（预算约束）

**性能：** 规则10ms + LLM 3-5s = 总体3-5s

**LLM Prompt 调整（路径B专用）：**
```
## 特别注意
- 硬约束（距离/预算/营业时间）已经由规则处理，你只需关注软偏好匹配
- 重点评估：口味偏好、氛围偏好、体验偏好、隐性需求
```

---

### 路径C: LLM主导全量重排（COMPLEX）

```python
def filter_pois_llm_dominant(
    pois: List[POI],
    request: PlanRequest,
    constraints: RouteConstraints
) -> List[POI]:
    """
    LLM主导：规则只过滤极端不符合的，LLM对所有POI重排
    """
    # Step 1: 规则只过滤极端情况（如：已关门、超出预算2倍以上）
    loosely_filtered = loose_hard_filter(pois, constraints)
    # 结果：250条 → 150条（只排除明显不合适的）
    
    # Step 2: 分批调用LLM（避免超长prompt）
    batch_size = 30
    all_llm_results = []
    for i in range(0, len(loosely_filtered), batch_size):
        batch = loosely_filtered[i:i+batch_size]
        results = call_llm_filter(
            pois=batch,
            user_query=request.raw_query,
            context=build_context(request),
            focus="full_evaluation"  # 全面评估
        )
        all_llm_results.extend(results)
    
    # Step 3: 按LLM分数排序
    all_llm_results.sort(key=lambda x: x["match_score"], reverse=True)
    
    # Step 4: 后处理：规则校验Top结果
    final = []
    for result in all_llm_results:
        poi = find_poi_by_id(result["poi_id"])
        if hard_constraint_check(poi, constraints):
            final.append(poi)
        if len(final) >= 30:
            break
    
    return final
```

**适用场景：**
- 用户输入复杂自然语言："周末带女朋友去成都，想吃正宗川菜但不要网红店，想去有历史感的地方拍照，不要太累"
- 包含多个规则外维度：口味偏好（川菜/非网红）、体验偏好（历史感/拍照）、体力偏好（不要太累）

**性能：** 5-10 batch × 3s = 15-30s（需要loading动画）

---

## 四、核心接口设计

### 4.1 统一筛选入口

```python
# backend/core/hybrid_filter.py

from enum import Enum
from typing import List, Tuple, Optional
from backend.models.schemas import POI, PlanRequest, UserPreference, RouteConstraints

class FilterStrategy(Enum):
    RULE_ONLY = "rule_only"
    HYBRID = "hybrid"
    LLM_DOMINANT = "llm_dominant"

class HybridPOIFilter:
    """
    混合POI筛选器
    自动选择最优筛选策略，兼顾速度与精准度
    """
    
    def __init__(self):
        self.rule_filter = RuleBasedFilter()
        self.llm_filter = LLMBasedFilter()
        self.query_analyzer = QueryAnalyzer()
    
    def filter(
        self,
        pois: List[POI],
        request: PlanRequest,
        user_pref: UserPreference,
        constraints: RouteConstraints,
        force_strategy: Optional[FilterStrategy] = None
    ) -> Tuple[List[POI], FilterStrategy, Dict]:
        """
        统一筛选入口
        
        Returns:
            filtered_pois: 筛选后的POI列表
            strategy_used: 实际使用的策略
            metadata: 筛选过程元数据（用于调试和展示）
        """
        # 确定策略
        if force_strategy:
            strategy = force_strategy
        else:
            strategy = self._select_strategy(request)
        
        # 执行筛选
        if strategy == FilterStrategy.RULE_ONLY:
            result = self.rule_filter.filter(pois, user_pref, constraints)
        elif strategy == FilterStrategy.HYBRID:
            result = self._hybrid_filter(pois, request, user_pref, constraints)
        else:
            result = self._llm_dominant_filter(pois, request, constraints)
        
        metadata = {
            "strategy": strategy.value,
            "input_count": len(pois),
            "output_count": len(result),
            "has_raw_query": bool(request.raw_query),
            "hidden_needs": self.query_analyzer.extract_hidden_needs(request.raw_query or ""),
        }
        
        return result, strategy, metadata
    
    def _select_strategy(self, request: PlanRequest) -> FilterStrategy:
        """自动选择筛选策略"""
        if not request.raw_query:
            # 无自然语言，检查preferences
            if not request.preferences or set(request.preferences).issubset(KNOWN_TAGS):
                return FilterStrategy.RULE_ONLY
            return FilterStrategy.HYBRID
        
        hidden_needs = self.query_analyzer.extract_hidden_needs(request.raw_query)
        if len(hidden_needs) >= 2:
            return FilterStrategy.LLM_DOMINANT
        elif len(hidden_needs) == 1:
            return FilterStrategy.HYBRID
        
        # 有raw_query但没有规则外需求
        return FilterStrategy.HYBRID
    
    def _hybrid_filter(self, pois, request, user_pref, constraints):
        """路径B实现"""
        # 规则粗筛
        rule_filtered = self.rule_filter.hard_constraint_filter(pois, constraints)
        rule_scored = self.rule_filter.score_by_preference(rule_filtered, user_pref)
        candidates = [p for p, _ in rule_scored[:50]]
        
        # LLM精筛
        llm_results = self.llm_filter.filter_batch(
            candidates, 
            request.raw_query or "",
            focus="soft_preference"
        )
        
        # 融合
        return self._fuse_scores(rule_scored, llm_results, alpha=0.4)
    
    def _llm_dominant_filter(self, pois, request, constraints):
        """路径C实现"""
        loosely_filtered = self.rule_filter.loose_filter(pois, constraints)
        llm_results = self.llm_filter.filter_all(loosely_filtered, request)
        return self._post_validate(llm_results, constraints)
```

### 4.2 LLM筛选器接口

```python
# backend/core/llm_filter.py

class LLMBasedFilter:
    """
    LLM语义筛选器
    负责理解自然语言需求，对POI输出匹配分数
    """
    
    def __init__(self, batch_size: int = 30):
        self.batch_size = batch_size
        self.client = get_llm_client()
    
    def filter_batch(
        self,
        pois: List[POI],
        user_query: str,
        context: Dict,
        focus: str = "full_evaluation"
    ) -> List[Dict]:
        """
        对一批POI进行LLM筛选
        
        Args:
            pois: 候选POI列表（建议20-50个）
            user_query: 用户自然语言需求
            context: 出行上下文
            focus: 评估重点
                - "full_evaluation": 全面评估
                - "soft_preference": 只评估软偏好（硬约束已由规则处理）
        """
        prompt = self._build_prompt(pois, user_query, context, focus)
        response = self.client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            timeout=30,
        )
        return self._parse_response(response.choices[0].message.content)
    
    def filter_all(
        self,
        pois: List[POI],
        request: PlanRequest
    ) -> List[Dict]:
        """
        全量POI筛选（分批处理）
        """
        all_results = []
        for i in range(0, len(pois), self.batch_size):
            batch = pois[i:i + self.batch_size]
            results = self.filter_batch(
                batch,
                request.raw_query or "",
                build_context(request),
                focus="full_evaluation"
            )
            all_results.extend(results)
            if i + self.batch_size < len(pois):
                time.sleep(1)  # 礼貌延迟
        
        return all_results
```

---

## 五、提示词设计（分路径）

### 5.1 路径A（纯规则）

无需LLM提示词，完全由代码逻辑处理。

### 5.2 路径B（规则+LLM）Prompt

```
## 角色
你是 POI 软偏好匹配专家。硬约束（距离/预算/营业时间）已由规则处理，你只需关注软偏好。

## 任务
对以下候选POI，根据用户的软偏好需求，输出匹配分数（0-100）和推荐理由。

## 用户软偏好
{user_query}

## 出行上下文
{context}

## 候选POI（已过滤硬约束）
{pois_json}

## 评分重点
1. 口味/风格偏好（如"吃辣""清淡""正宗"）
2. 氛围/体验偏好（如"安静""浪漫""热闹"）
3. 社交属性（如"适合发朋友圈""网红""小众"）
4. 情感/场景匹配（如"约会""亲子""独自思考"）

## 输出格式
JSON数组，每个元素：
{
  "poi_id": "...",
  "match_score": 0-100,
  "recommendation_reason": "一句话，聚焦软偏好匹配",
  "soft_matched": ["吃辣", "安静"]
}
```

### 5.3 路径C（LLM主导）Prompt

使用完整版提示词（见 `docs/llm_poi_filter_prompt.md`）。

---

## 六、前端交互设计

### 6.1 筛选过程可视化

```
用户点击"生成路线"
    │
    ▼
┌──────────────────────────────────────┐
│ 分析需求复杂度...                      │ ← 100ms
│   └─ 检测到规则外需求："吃辣""人少"     │
│   └─ 策略：混合筛选（规则+LLM）        │
├──────────────────────────────────────┤
│ 规则硬约束过滤：250 → 80条             │ ← 10ms
├──────────────────────────────────────┤
│ LLM软偏好评估中... ⏳                  │ ← 3-5s
│   进度：[████░░░░░░] 3/5 batch        │
├──────────────────────────────────────┤
│ 生成3套差异化方案 ✓                    │ ← 500ms
└──────────────────────────────────────┘
```

### 6.2 结果解释

每条路线的推荐理由中，标注哪些来自规则，哪些来自LLM：

```
🤖 AI推荐理由：
  ├─ [规则] 匹配你的"美食"偏好（标签匹配度85%）
  ├─ [LLM] 正宗川菜满足你的"吃辣"需求（麻辣指数高）
  └─ [LLM] 非网红老店，符合"人少安静"的期望
```

---

## 七、性能与成本预估

| 路径 | 规则耗时 | LLM耗时 | 总耗时 | API成本 | 适用占比 |
|------|---------|--------|--------|---------|---------|
| A. 纯规则 | 10ms | 0 | **10ms** | ¥0 | ~60% |
| B. 混合 | 10ms | 3s | **3s** | ¥0.05 | ~30% |
| C. LLM主导 | 10ms | 15s | **15s** | ¥0.3 | ~10% |

**优化建议：**
- 路径C可以异步化：先生成路径A/B的方案展示给用户，后台异步用LLM优化
- 缓存LLM结果：同一query+同一城市的结果缓存24小时

---

## 八、实现优先级

| 优先级 | 任务 | 预估工时 |
|--------|------|---------|
| P0 | 实现 `QueryAnalyzer` 需求复杂度判定 | 2h |
| P0 | 实现路径A（纯规则，已存在，需封装） | 1h |
| P1 | 实现路径B（规则粗筛+LLM精筛） | 4h |
| P1 | 编写路径B专用Prompt | 2h |
| P2 | 实现路径C（LLM分批全量） | 4h |
| P2 | 前端筛选过程可视化 | 3h |
| P3 | LLM结果缓存机制 | 2h |
| P3 | 异步优化（先展示规则结果，后台LLM优化） | 4h |
