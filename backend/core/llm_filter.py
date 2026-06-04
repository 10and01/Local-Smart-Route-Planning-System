# -*- coding: utf-8 -*-
"""
LLM 语义筛选器
负责理解自然语言需求，对 POI 输出匹配分数和推荐理由
"""

import json
import time
from typing import List, Dict, Optional

from backend.models.schemas import POI, PlanRequest, UserPreference, RouteConstraints
from backend.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, check_llm_config

# API 配置
API_KEY = LLM_API_KEY
BASE_URL = LLM_BASE_URL
MODEL_NAME = LLM_MODEL_NAME

_client: Optional[object] = None


def get_client() -> object:
    """获取 LLM 客户端（延迟初始化）"""
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


# System Prompt（路径C：LLM主导 / 全面评估）
SYSTEM_PROMPT_FULL = """你是「旅行路线规划系统」的 POI 智能筛选专家。

你的任务：根据用户的自然语言需求，对一批候选 POI 逐一评估匹配度，输出结构化评分结果。

## 核心能力
- 理解规则外的复杂/隐性需求（如"吃辣""人少安静""适合发朋友圈""有历史感"）
- 结合出行上下文（人群、时间、预算、节奏）综合判断
- 对每个 POI 给出 0-100 的匹配分数和一句话推荐理由

## 评分原则
1. 不要只看 POI 的现有标签，要根据名称、分类、地址、评分等信息综合推断
2. 隐性需求要深入理解：
   - "吃辣"→优先川湘菜/火锅；"人少"→避开网红打卡地；"历史感"→古迹/老街/博物馆
   - "爬山/户外/徒步"→优先山地、森林公园、自然风景区
   - "拍照/摄影/打卡"→优先风景名胜（如西湖、断桥、雷峰塔）、古迹、地标建筑，避免给KTV/影院等室内娱乐场所高分
   - "美食/吃"→优先餐厅、小吃街、夜市，风景名胜类的餐厅可适当加分但不应高于纯景点
3. 考虑 POI 的适合人群：情侣/亲子/独自/朋友/家庭/老人/商务/学生
4. 考虑时间合理性：上午适合户外拍照，中午适合用餐，晚上适合夜景/酒吧
5. 考虑地理连续性：远距离的 POI 如果没有特殊价值，适当降分
6. 排除规则：如果用户明确说"不要去宾馆/酒店/住宿"，任何住宿类 POI 必须打 0 分

## 输出要求
- 只输出纯 JSON，不要 markdown 代码块，不要任何解释文字
- 每个 POI 必须包含：poi_id、match_score、recommendation_reason、is_recommended
- match_score 是 0-100 的整数
- is_recommended 为 true 当且仅当 match_score >= 60
"""

# System Prompt（路径B：混合筛选 / 只评估软偏好）
SYSTEM_PROMPT_SOFT = """你是 POI 软偏好匹配专家。硬约束（距离/预算/营业时间）已由规则处理，你只需关注软偏好。

## 任务
对以下候选POI，根据用户的软偏好需求，输出匹配分数（0-100）和推荐理由。

## 评分重点
1. 口味/风格偏好（如"吃辣""清淡""正宗"）
2. 氛围/体验偏好（如"安静""浪漫""热闹"）
3. 社交属性（如"适合发朋友圈""网红""小众"）
4. 情感/场景匹配（如"约会""亲子""独自思考"）
5. 活动类型匹配（如"爬山""徒步""骑行""露营""户外"→优先自然风景/山地/森林公园；"博物馆""历史"→优先文化古迹）

## 重要规则
- 如果用户说"不要去宾馆/酒店/住宿"，任何 category 包含"住宿""酒店""宾馆"的 POI 必须打 0 分
- 如果用户说"喜欢爬山/户外/徒步"，优先给山地、森林公园、自然风景区高分，即使标签里没有"爬山"二字
- 不要只看 POI 的现有标签，要根据名称、分类、地址综合推断其实际体验

## 输出要求
- 只输出纯 JSON，不要 markdown 代码块，不要任何解释文字
- 每个 POI 必须包含：poi_id、match_score、recommendation_reason、is_recommended、matched_themes、hidden_matched
- match_score 是 0-100 的整数
- is_recommended 为 true 当且仅当 match_score >= 60
"""


def _build_poi_json(pois: List[POI]) -> List[Dict]:
    """将 POI 对象列表转为精简的 JSON 格式（减少 token）"""
    result = []
    for p in pois:
        item = {
            "poi_id": p.poi_id,
            "name": p.name,
            "category": p.category,
            "sub_category": p.sub_category or "",
            "address": p.address or "",
            "rating": p.rating,
            "price": p.price if p.price is not None else 0,
            "tags": p.tags[:6] if p.tags else [],
            "highlights": p.highlights or "",
            "suitable_for": p.suitable_for or [],
            "business_hours": p.business_hours or "",
        }
        # 添加坐标（如果有）
        if p.location:
            item["location"] = {"lat": p.location.lat, "lng": p.location.lng}
        result.append(item)
    return result


def _build_context(request: PlanRequest) -> Dict:
    """构建出行上下文"""
    return {
        "city": request.city,
        "travelers": request.travelers,
        "preferences": request.preferences,
        "pace": request.pace,
        "budget": request.budget,
        "must_visit": request.must_visit,
        "avoid": request.avoid,
        "transport_mode": request.transport_mode,
        "start_time": request.start_time,
        "end_time": request.end_time,
    }


def _build_user_prompt(
    pois: List[POI],
    user_query: str,
    context: Dict,
    focus: str = "full_evaluation"
) -> str:
    """构建用户 prompt"""
    poi_json = json.dumps(_build_poi_json(pois), ensure_ascii=False, indent=None)
    
    prompt = f"""## 用户需求

{user_query}

## 出行上下文

- 城市：{context.get('city', '')}
- 出行人群：{context.get('travelers', '')}
- 偏好标签：{context.get('preferences', [])}
- 节奏：{context.get('pace', '')}
- 预算级别：{context.get('budget', '未指定')} 元
- 必去点：{context.get('must_visit', [])}
- 避开点：{context.get('avoid', [])}
- 交通方式：{context.get('transport_mode', '')}

## 候选 POI 列表（共 {len(pois)} 个）

{poi_json}
"""
    
    if focus == "soft_preference":
        prompt += """
## 评分任务

请对上述每个 POI，根据用户的软偏好需求，输出匹配分数（0-100）和推荐理由。

## 输出格式

返回 JSON 数组，每个元素对应一个 POI：
[
  {
    "poi_id": "B0FFxxxx",
    "match_score": 85,
    "recommendation_reason": "川菜老字号，麻辣口味正宗，人均消费适中",
    "is_recommended": true,
    "matched_themes": ["美食", "地方特色"],
    "hidden_matched": ["吃辣", "老字号"]
  }
]
"""
    else:
        prompt += """
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
"""
    
    return prompt


def _parse_llm_response(content: str) -> List[Dict]:
    """
    解析 LLM 返回的 JSON 内容
    处理常见的格式问题（markdown 代码块、多余文字等）
    """
    if not content:
        return []
    
    content = content.strip()
    
    # 去除 markdown 代码块标记
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    
    content = content.strip()
    
    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict) and "results" in parsed:
            return parsed["results"]
        elif isinstance(parsed, dict):
            # 可能是 {poi_id: {...}} 格式
            results = []
            for k, v in parsed.items():
                if isinstance(v, dict):
                    if "poi_id" not in v:
                        v["poi_id"] = k
                    results.append(v)
            return results
    except json.JSONDecodeError:
        # 尝试提取 JSON 数组部分
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(content[start:end+1])
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
    
    return []


class LLMBasedFilter:
    """
    LLM 语义筛选器
    负责理解自然语言需求，对 POI 输出匹配分数和推荐理由
    【优化】batch_size 增大到 30，支持 LLM 一次性处理更多POI，实现主导排序
    """
    
    def __init__(self, batch_size: int = 70):
        self.batch_size = batch_size
    
    def filter_batch(
        self,
        pois: List[POI],
        user_query: str,
        context: Dict,
        focus: str = "full_evaluation"
    ) -> List[Dict]:
        """
        对一批 POI 进行 LLM 筛选
        
        Args:
            pois: 候选 POI 列表（建议 20-50 个）
            user_query: 用户自然语言需求
            context: 出行上下文
            focus: 评估重点
                - "full_evaluation": 全面评估
                - "soft_preference": 只评估软偏好（硬约束已由规则处理）
        
        Returns:
            LLM 筛选结果列表，每个元素包含 poi_id, match_score 等
        """
        if not pois or not user_query:
            return []
        
        if not check_llm_config():
            print("[LLM Filter Warning] LLM 配置不完整，跳过 LLM 筛选")
            return []
        
        system_prompt = SYSTEM_PROMPT_SOFT if focus == "soft_preference" else SYSTEM_PROMPT_FULL
        prompt = _build_user_prompt(pois, user_query, context, focus)
        
        try:
            client = get_client()
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                timeout=90,
            )
            
            content = response.choices[0].message.content
            results = _parse_llm_response(content)
            
            # 验证结果完整性
            valid_results = []
            poi_ids = {p.poi_id for p in pois}
            for r in results:
                if isinstance(r, dict) and r.get("poi_id") in poi_ids:
                    valid_results.append(r)
            
            # 为缺失的 POI 补充默认分数
            returned_ids = {r["poi_id"] for r in valid_results}
            for p in pois:
                if p.poi_id not in returned_ids:
                    valid_results.append({
                        "poi_id": p.poi_id,
                        "match_score": 50,
                        "recommendation_reason": "未获得明确评估",
                        "is_recommended": True,
                        "matched_themes": [],
                        "hidden_matched": [],
                    })
            
            return valid_results
            
        except Exception as e:
            print(f"[LLM Filter Warning] LLM 筛选失败: {e}")
            # fallback：返回默认分数
            return [
                {
                    "poi_id": p.poi_id,
                    "match_score": 50,
                    "recommendation_reason": "LLM 筛选异常，默认保留",
                    "is_recommended": True,
                    "matched_themes": [],
                    "hidden_matched": [],
                }
                for p in pois
            ]
    
    def filter_all(
        self,
        pois: List[POI],
        request: PlanRequest
    ) -> List[Dict]:
        """
        全量 POI 筛选（分批处理）
        
        Args:
            pois: 候选 POI 列表
            request: 规划请求
        
        Returns:
            所有 POI 的 LLM 筛选结果
        """
        if not pois:
            return []
        
        context = _build_context(request)
        all_results = []
        
        for i in range(0, len(pois), self.batch_size):
            batch = pois[i:i + self.batch_size]
            results = self.filter_batch(
                batch,
                request.raw_query or "",
                context,
                focus="full_evaluation"
            )
            all_results.extend(results)
            
            # 批次间礼貌延迟
            if i + self.batch_size < len(pois):
                time.sleep(0.5)
        
        return all_results
