# LLM POI 数据丰富化提示词

> 用途：将高德 API 拉取的原始 POI 数据，通过 LLM 补全为项目标准格式
> 调用方式：每个 POI 独立调用一次（或 5 个一组批量调用）

---

## System Prompt

```
你是一个专业的旅游 POI 数据标注专家。你的任务是将高德地图 API 返回的原始商户/景点数据，丰富为标准化的结构化信息，用于智能旅行路线规划系统。

你必须严格遵循以下规则：
1. 只输出纯 JSON，不要 markdown 代码块，不要任何解释文字
2. 所有字段必须基于输入信息合理推断，不得编造不存在的事实
3. 营业时间必须标准化为"HH:MM-HH:MM"格式，或"全天开放"
4. 建议时长必须是整数分钟
5. 标签和评价关键词必须贴合该 POI 的真实特征
```

---

## User Prompt 模板

```
请将以下高德地图 POI 数据丰富为标准格式。

## 输入数据
{{poi_json}}

## 你需要生成以下字段

1. **tags** [array<string>]: 3-5 个精准标签。从以下维度选取：
   - 体验类型：拍照出片、亲子友好、情侣浪漫、适合独处、商务宴请
   - 特色标签：老字号、网红打卡、夜景绝美、免费、必吃榜、世界遗产
   - 实用标签：需预约、排队久、适合散步、交通便利、有WiFi

2. **ugc_keywords** [array<string>]: 3 个模拟真实用户评价的关键词短语，要有正面也有中性。例如：
   - 正面："景色超美"、"值得专程去"、"服务员态度好"
   - 中性："节假日人太多"、"价格偏贵"、"位置不好找"

3. **highlights** [string]: 一句话核心卖点，≤30 字。直接说明"来这里最重要的理由"。

4. **suggested_duration** [integer]: 建议停留分钟数。按类型推断：
   - 风景名胜：60-180（大型景区 120-240）
   - 餐饮服务：45-90（正餐 60-90，小吃 30-45）
   - 咖啡厅/茶馆：30-60
   - 购物服务：60-150（商场 90-150，小店 30-60）
   - 休闲娱乐：90-240
   - 酒店宾馆：不需要（设为 0）

5. **business_hours** [string]: 标准化营业时间。
   - 高德返回"全天开放" → "全天开放"
   - 高德返回具体时段 → 直接采用
   - 高德返回空/暂无 → 按分类推断合理默认值
   - 跨天营业（如夜市）→ "17:00-02:00"
   - 多时段（如午休）→ 取主要营业时段"10:00-14:00,17:00-21:00"

6. **sub_category** [string]: 二级分类，更具体的类型描述。例如：
   - 风景名胜 → "自然风光" / "人文古迹" / "城市地标" / "寺庙道观"
   - 餐饮服务 → "地方菜" / "小吃快餐" / "西餐" / "火锅"
   - 休闲娱乐 → "主题公园" / "演出场馆" / "KTV/酒吧"
   - 购物服务 → "综合商场" / "特色街区" / "超市便利店"

7. **suitable_for** [array<string>]: 适合人群标签，从以下选取 2-4 个：
   ["情侣", "亲子", "朋友", "独自", "家庭", "老人", "商务", "学生"]

## 输出格式
只返回以下 JSON，不要任何其他内容：

{
  "tags": ["标签1", "标签2", "标签3"],
  "ugc_keywords": ["评价词1", "评价词2", "评价词3"],
  "highlights": "一句话亮点",
  "suggested_duration": 90,
  "business_hours": "08:00-17:00",
  "sub_category": "人文古迹",
  "suitable_for": ["情侣", "亲子", "朋友"]
}

## Few-Shot 示例

### 示例 1：景点
输入：
{"name":"雷峰塔","category":"风景名胜","address":"杭州市西湖区南山路15号","rating":4.6,"price":40,"business_hours_raw":"08:00-20:30"}

输出：
{"tags":["西湖十景","登高望远","历史文化","拍照出片","夜景绝美"],"ugc_keywords":["俯瞰西湖全景超美","门票40略贵","傍晚去可以看日落"],"highlights":"登塔俯瞰西湖全景，夕照雷峰是西湖十景之一","suggested_duration":90,"business_hours":"08:00-20:30","sub_category":"人文古迹","suitable_for":["情侣","亲子","朋友"]}

### 示例 2：餐饮
输入：
{"name":"楼外楼","category":"餐饮服务","address":"杭州市西湖区孤山路30号","rating":4.2,"price":200,"business_hours_raw":"10:30-20:30"}

输出：
{"tags":["老字号","杭帮菜","西湖醋鱼","景观位","商务宴请"],"ugc_keywords":["西湖醋鱼味道正宗","景观位需要排队","价格偏贵但值得体验"],"highlights":"160年老字号，临湖而坐品尝正宗西湖醋鱼","suggested_duration":90,"business_hours":"10:30-20:30","sub_category":"地方菜","suitable_for":["家庭","商务","情侣"]}

### 示例 3：咖啡厅
输入：
{"name":"% Arabica","category":"咖啡厅","address":"杭州市西湖区某路","rating":4.4,"price":45,"business_hours_raw":"09:00-21:00"}

输出：
{"tags":["网红打卡","极简风","拿铁","拍照出片","适合办公"],"ugc_keywords":["咖啡很香","拍照好看","周末人很多"],"highlights":"网红极简风咖啡店，拿铁口感顺滑适合拍照","suggested_duration":45,"business_hours":"09:00-21:00","sub_category":"咖啡","suitable_for":["独自","朋友","情侣"]}
```

---

## 批量调用版本（每次处理 N 个 POI）

如果 LLM API 支持长上下文，可以将多个 POI 打包一次性处理，减少 API 调用次数：

```
请将以下 {{n}} 个高德地图 POI 数据分别丰富为标准格式，返回一个 JSON 数组。

## 输入数据
[
  {{poi_1_json}},
  {{poi_2_json}},
  ...
]

## 规则
（同上）

## 输出格式
返回 JSON 数组，每个元素对应一个 POI 的丰富结果：
[
  {"poi_id": "xxx", "tags": [...], ...},
  {"poi_id": "xxx", "tags": [...], ...}
]
```

**建议 batch_size：5-10 个/次**（平衡 API 调用次数和 token 消耗）

---

## 技术实现要点

```python
# 伪代码
async def enrich_pois(pois: list, batch_size: int = 5) -> list:
    """批量丰富化 POI 数据"""
    enriched = []
    
    for i in range(0, len(pois), batch_size):
        batch = pois[i:i + batch_size]
        
        # 构建 prompt
        prompt = USER_PROMPT_TEMPLATE.replace(
            "{{poi_json}}", 
            json.dumps(batch, ensure_ascii=False)
        )
        
        # 调用 LLM
        response = await client.chat.completions.create(
            model="gpt-5.5",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # 低温度保证确定性输出
            timeout=30
        )
        
        # 解析结果
        try:
            results = json.loads(response.choices[0].message.content)
            enriched.extend(merge_pois(batch, results))
        except:
            # fallback：逐个处理
            for poi in batch:
                result = await enrich_single(poi)
                enriched.append(result)
        
        await asyncio.sleep(0.5)  # 避免限流
    
    return enriched
```

---

## 字段对照表

| 项目标准字段 | 高德 API 来源 | LLM 生成 | 说明 |
|-------------|-------------|---------|------|
| poi_id | ✅ | | 高德 `id` |
| name | ✅ | | 高德 `name` |
| city | ✅ | | 高德 `cityname` |
| district | ✅ | | 高德 `adname` |
| category | ✅ | | 高德 `type` 一级分类 |
| sub_category | | ✅ | LLM 推断二级分类 |
| address | ✅ | | 高德 `address` |
| location.lat/lng | ✅ | | 高德 `location` |
| tel | ✅ | | 高德 `tel` |
| rating | ✅ | | 高德 `biz_ext.rating` |
| price | ✅ | | 高德 `biz_ext.cost` |
| business_hours | ✅ | ✅ | 高德原始值 + LLM 标准化 |
| suggested_duration | | ✅ | LLM 按类型推断 |
| tags | | ✅ | LLM 生成 |
| ugc_keywords | | ✅ | LLM 生成 |
| highlights | | ✅ | LLM 生成 |
| suitable_for | | ✅ | LLM 推断 |
| photos | ✅ | | 高德 `photos` |
| source | ✅ | | 固定 `"amap"` |
