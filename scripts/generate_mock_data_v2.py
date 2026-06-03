#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
杭州高质量Mock POI数据集 V2
包含100+真实杭州POI，覆盖西湖、灵隐、西溪、市中心、拱墅等区域
"""

import json
import random
import os
import sys
import urllib.parse
sys.stdout.reconfigure(encoding='utf-8')

OUTPUT_DIR = "data"

# 杭州市中心范围（西湖周边）
HANGZHOU_CENTER = {"lat": 30.2596, "lng": 120.1460}

# 扩展的杭州POI数据集：基于真实地理位置和标签
HANGZHOU_POIS = [
    # ===== 西湖核心景区 =====
    {"name": "西湖断桥残雪", "category": "风景名胜", "tags": ["拍照", "浪漫", "免费", "标志性", "湖景"],
     "lat": 30.2596, "lng": 120.1460, "rating": 4.8, "price": 0, "duration": 60},
    {"name": "雷峰塔", "category": "风景名胜", "tags": ["历史文化", "登高", "西湖十景", "夜景"],
     "lat": 30.2310, "lng": 120.1485, "rating": 4.6, "price": 40, "duration": 90},
    {"name": "三潭印月", "category": "风景名胜", "tags": ["西湖", "游船", "拍照", "人民币背景", "Island"],
     "lat": 30.2390, "lng": 120.1410, "rating": 4.5, "price": 55, "duration": 90},
    {"name": "苏堤春晓", "category": "风景名胜", "tags": ["漫步", "自然风光", "免费", "晨跑", "赏花"],
     "lat": 30.2450, "lng": 120.1350, "rating": 4.7, "price": 0, "duration": 60},
    {"name": "白堤", "category": "风景名胜", "tags": ["散步", "湖景", "免费", "骑行", "桃花"],
     "lat": 30.2550, "lng": 120.1500, "rating": 4.6, "price": 0, "duration": 45},
    {"name": "平湖秋月", "category": "风景名胜", "tags": ["赏月", "安静", "西湖十景", "秋天"],
     "lat": 30.2530, "lng": 120.1420, "rating": 4.5, "price": 0, "duration": 40},
    {"name": "花港观鱼", "category": "风景名胜", "tags": ["亲子", "喂鱼", "园林", "拍照", "春天"],
     "lat": 30.2330, "lng": 120.1380, "rating": 4.5, "price": 0, "duration": 50},
    {"name": "曲院风荷", "category": "风景名胜", "tags": ["荷花", "夏天", "园林", "拍照", "免费"],
     "lat": 30.2630, "lng": 120.1300, "rating": 4.6, "price": 0, "duration": 50},
    {"name": "柳浪闻莺", "category": "风景名胜", "tags": ["柳树", "鸟叫", "安静", "免费", "晨练"],
     "lat": 30.2380, "lng": 120.1550, "rating": 4.4, "price": 0, "duration": 40},
    {"name": "南屏晚钟", "category": "风景名胜", "tags": ["寺庙", "钟声", "安静", "文化", "净慈寺"],
     "lat": 30.2280, "lng": 120.1450, "rating": 4.4, "price": 10, "duration": 40},

    # ===== 灵隐/北高峰 =====
    {"name": "灵隐寺", "category": "风景名胜", "tags": ["寺庙", "祈福", "古建筑", "人气旺", "文化"],
     "lat": 30.2405, "lng": 120.0980, "rating": 4.7, "price": 75, "duration": 120},
    {"name": "飞来峰造像", "category": "风景名胜", "tags": ["石窟", "石刻", "历史", "佛教", "艺术"],
     "lat": 30.2420, "lng": 120.0950, "rating": 4.5, "price": 45, "duration": 60},
    {"name": "永福寺", "category": "风景名胜", "tags": ["寺庙", "茶园", "安静", "素面", "祈福"],
     "lat": 30.2435, "lng": 120.0960, "rating": 4.6, "price": 0, "duration": 50},
    {"name": "韬光寺", "category": "风景名胜", "tags": ["寺庙", "登山", "观潮", "安静", "小众"],
     "lat": 30.2450, "lng": 120.0930, "rating": 4.5, "price": 0, "duration": 60},
    {"name": "北高峰", "category": "风景名胜", "tags": ["登山", "观景", "财神庙", "缆车", "俯瞰"],
     "lat": 30.2480, "lng": 120.0900, "rating": 4.4, "price": 8, "duration": 90},
    {"name": "法喜寺", "category": "风景名胜", "tags": ["寺庙", "祈福", "网红", "御守", "拍照"],
     "lat": 30.2350, "lng": 120.0880, "rating": 4.6, "price": 10, "duration": 60},
    {"name": "法镜寺", "category": "风景名胜", "tags": ["寺庙", "女众道场", "安静", "三生石"],
     "lat": 30.2370, "lng": 120.0900, "rating": 4.3, "price": 10, "duration": 40},
    {"name": "三天竺", "category": "风景名胜", "tags": ["古道", "寺庙", "茶文化", "安静", "徒步"],
     "lat": 30.2360, "lng": 120.0890, "rating": 4.4, "price": 0, "duration": 90},

    # ===== 西溪湿地 =====
    {"name": "西溪湿地", "category": "风景名胜", "tags": ["自然", "湿地", "乘船", "宁静", "拍照", "生态"],
     "lat": 30.2700, "lng": 120.0650, "rating": 4.6, "price": 80, "duration": 180},
    {"name": "洪园", "category": "风景名胜", "tags": ["湿地", "古建筑", "文化", "小众", "安静"],
     "lat": 30.2750, "lng": 120.0580, "rating": 4.3, "price": 0, "duration": 60},
    {"name": "烟水渔庄", "category": "风景名胜", "tags": ["湿地", "农家乐", "捕鱼", "民俗", "亲子"],
     "lat": 30.2680, "lng": 120.0600, "rating": 4.2, "price": 0, "duration": 50},
    {"name": "深潭口", "category": "风景名胜", "tags": ["湿地", "古樟树", "非诚勿扰", "拍照"],
     "lat": 30.2720, "lng": 120.0630, "rating": 4.4, "price": 0, "duration": 40},

    # ===== 市中心/历史街区 =====
    {"name": "河坊街", "category": "风景名胜", "tags": ["古街", "小吃", "购物", "夜景", "老字号"],
     "lat": 30.2410, "lng": 120.1680, "rating": 4.3, "price": 0, "duration": 120},
    {"name": "南宋御街", "category": "风景名胜", "tags": ["古街", "历史", "建筑", "水景", "步行街"],
     "lat": 30.2430, "lng": 120.1660, "rating": 4.2, "price": 0, "duration": 60},
    {"name": "吴山广场", "category": "风景名胜", "tags": ["广场", "城隍阁", "登山", "市井", "免费"],
     "lat": 30.2380, "lng": 120.1650, "rating": 4.1, "price": 0, "duration": 40},
    {"name": "城隍阁", "category": "风景名胜", "tags": ["登高", "夜景", "俯瞰", "历史", "喝茶"],
     "lat": 30.2350, "lng": 120.1630, "rating": 4.3, "price": 30, "duration": 50},
    {"name": "胡雪岩故居", "category": "风景名胜", "tags": ["古建筑", "历史", "园林", "豪宅", "文化"],
     "lat": 30.2440, "lng": 120.1700, "rating": 4.5, "price": 20, "duration": 50},
    {"name": "南宋官窑博物馆", "category": "博物馆", "tags": ["陶瓷", "历史", "文化", "亲子", "免费"],
     "lat": 30.2100, "lng": 120.1450, "rating": 4.4, "price": 0, "duration": 60},
    {"name": "杭州博物馆", "category": "博物馆", "tags": ["历史", "文物", "免费", "文化", "镇馆之宝"],
     "lat": 30.2420, "lng": 120.1640, "rating": 4.5, "price": 0, "duration": 90},
    {"name": "中国丝绸博物馆", "category": "博物馆", "tags": ["丝绸", "时尚", "文化", "建筑美", "免费"],
     "lat": 30.2250, "lng": 120.1550, "rating": 4.6, "price": 0, "duration": 60},
    {"name": "浙江省博物馆", "category": "博物馆", "tags": ["文物", "历史", "文化", "免费", "镇馆之宝"],
     "lat": 30.2550, "lng": 120.1400, "rating": 4.5, "price": 0, "duration": 90},

    # ===== 小河/拱墅 =====
    {"name": "小河直街", "category": "风景名胜", "tags": ["文艺", "古街", "拍照", "下午茶", "运河"],
     "lat": 30.2950, "lng": 120.1550, "rating": 4.4, "price": 0, "duration": 90},
    {"name": "桥西历史街区", "category": "风景名胜", "tags": ["运河", "博物馆群", "古街", "文化", "手工艺"],
     "lat": 30.3000, "lng": 120.1500, "rating": 4.3, "price": 0, "duration": 60},
    {"name": "拱宸桥", "category": "风景名胜", "tags": ["古桥", "运河", "历史", "拍照", "免费"],
     "lat": 30.3020, "lng": 120.1480, "rating": 4.5, "price": 0, "duration": 30},
    {"name": "刀剪剑博物馆", "category": "博物馆", "tags": ["非遗", "手工艺", "亲子", "免费", "独特"],
     "lat": 30.2980, "lng": 120.1520, "rating": 4.3, "price": 0, "duration": 45},
    {"name": "中国扇博物馆", "category": "博物馆", "tags": ["非遗", "手工艺", "文化", "免费", "优雅"],
     "lat": 30.2990, "lng": 120.1510, "rating": 4.2, "price": 0, "duration": 40},
    {"name": "大兜路历史街区", "category": "风景名胜", "tags": ["运河", "夜市", "文艺", "美食", "夜景"],
     "lat": 30.2920, "lng": 120.1580, "rating": 4.2, "price": 0, "duration": 60},

    # ===== 宋城/之江 =====
    {"name": "宋城", "category": "休闲娱乐", "tags": ["演出", "穿越", "主题公园", "千古情", "表演"],
     "lat": 30.1850, "lng": 120.1050, "rating": 4.5, "price": 320, "duration": 240},
    {"name": "杭州极地海洋公园", "category": "休闲娱乐", "tags": ["海洋动物", "亲子", "表演", "企鹅", "白鲸"],
     "lat": 30.1700, "lng": 120.1200, "rating": 4.4, "price": 290, "duration": 180},
    {"name": "中国美术学院象山校区", "category": "风景名胜", "tags": ["建筑", "艺术", "拍照", "设计", "校园"],
     "lat": 30.1500, "lng": 120.0800, "rating": 4.6, "price": 0, "duration": 60},
    {"name": "之江校区", "category": "风景名胜", "tags": ["建筑", "民国", "红砖", "拍照", "安静"],
     "lat": 30.1950, "lng": 120.1100, "rating": 4.5, "price": 0, "duration": 50},

    # ===== 美食：杭帮菜老字号 =====
    {"name": "楼外楼", "category": "餐饮服务", "tags": ["杭帮菜", "西湖醋鱼", "老字号", "景观位", "历史"],
     "lat": 30.2580, "lng": 120.1400, "rating": 4.2, "price": 200, "duration": 90},
    {"name": "知味观", "category": "餐饮服务", "tags": ["小笼包", "点心", "老字号", "平价", "猫耳朵"],
     "lat": 30.2550, "lng": 120.1650, "rating": 4.4, "price": 80, "duration": 60},
    {"name": "外婆家", "category": "餐饮服务", "tags": ["杭帮菜", "排队王", "性价比高", "家庭", "麻婆豆腐"],
     "lat": 30.2680, "lng": 120.1550, "rating": 4.5, "price": 90, "duration": 75},
    {"name": "绿茶餐厅", "category": "餐饮服务", "tags": ["创意菜", "环境好", "拍照", "年轻人", "面包诱惑"],
     "lat": 30.2720, "lng": 120.1600, "rating": 4.3, "price": 100, "duration": 75},
    {"name": "新白鹿餐厅", "category": "餐饮服务", "tags": ["杭帮菜", "便宜", "排队", "必吃", "蛋黄鸡翅"],
     "lat": 30.2640, "lng": 120.1580, "rating": 4.4, "price": 70, "duration": 75},
    {"name": "老头儿油爆虾", "category": "餐饮服务", "tags": ["油爆虾", "地道", "老店", "夜宵", "干炸响铃"],
     "lat": 30.2500, "lng": 120.1700, "rating": 4.3, "price": 110, "duration": 60},
    {"name": "张生记", "category": "餐饮服务", "tags": ["杭帮菜", "老鸭煲", "老字号", "家庭", "宴请"],
     "lat": 30.2650, "lng": 120.1650, "rating": 4.3, "price": 150, "duration": 90},
    {"name": "奎元馆", "category": "餐饮服务", "tags": ["片儿川", "虾爆鳝面", "老字号", "面食", "平价"],
     "lat": 30.2560, "lng": 120.1670, "rating": 4.2, "price": 50, "duration": 45},
    {"name": "王润兴酒楼", "category": "餐饮服务", "tags": ["乾隆鱼", "杭帮菜", "老字号", "历史", "古装"],
     "lat": 30.2420, "lng": 120.1680, "rating": 4.1, "price": 120, "duration": 75},
    {"name": "山外山", "category": "餐饮服务", "tags": ["杭帮菜", "植物园", "素菜", "老字号", "环境"],
     "lat": 30.2600, "lng": 120.1250, "rating": 4.3, "price": 130, "duration": 75},

    # ===== 美食：特色/网红 =====
    {"name": "菊英面店", "category": "餐饮服务", "tags": ["片儿川", "拌川", "市井", "排队", "舌尖"],
     "lat": 30.2480, "lng": 120.1720, "rating": 4.2, "price": 30, "duration": 40},
    {"name": "方老大面", "category": "餐饮服务", "tags": ["拌川", "腰花", "市井", "排队", "地道"],
     "lat": 30.2450, "lng": 120.1750, "rating": 4.3, "price": 35, "duration": 40},
    {"name": "孙奶奶葱包桧", "category": "餐饮服务", "tags": ["小吃", "葱包桧", "市井", "路边摊", "地道"],
     "lat": 30.2400, "lng": 120.1690, "rating": 4.2, "price": 10, "duration": 20},
    {"name": "周萍粽子", "category": "餐饮服务", "tags": ["粽子", "大肉粽", "市井", "老字号", "早餐"],
     "lat": 30.2380, "lng": 120.1670, "rating": 4.3, "price": 15, "duration": 20},
    {"name": "游埠豆浆", "category": "餐饮服务", "tags": ["豆浆", "油条", "早餐", "市井", "地道"],
     "lat": 30.2520, "lng": 120.1740, "rating": 4.2, "price": 15, "duration": 25},
    {"name": "苏小柳", "category": "餐饮服务", "tags": ["小笼包", "江南点心", "精致", "拍照", "蟹粉"],
     "lat": 30.2650, "lng": 120.1600, "rating": 4.4, "price": 80, "duration": 60},
    {"name": "菲乐餐厅", "category": "餐饮服务", "tags": ["杭帮菜", "白切肉", "家常", "小众", "本地"],
     "lat": 30.2570, "lng": 120.1410, "rating": 4.3, "price": 90, "duration": 60},
    {"name": "德明饭店", "category": "餐饮服务", "tags": ["杭帮菜", "卤大肠", "市井", "排队", "苍蝇馆"],
     "lat": 30.2380, "lng": 120.1730, "rating": 4.4, "price": 100, "duration": 60},

    # ===== 咖啡厅/下午茶 =====
    {"name": "星巴克(西湖天地店)", "category": "咖啡厅", "tags": ["湖景", "下午茶", "拍照", "休息", "连锁"],
     "lat": 30.2560, "lng": 120.1420, "rating": 4.5, "price": 50, "duration": 45},
    {"name": "% Arabica(杭州店)", "category": "咖啡厅", "tags": ["网红", "拿铁", "极简风", "拍照", "品质"],
     "lat": 30.2700, "lng": 120.1500, "rating": 4.4, "price": 45, "duration": 40},
    {"name": "M Stand", "category": "咖啡厅", "tags": ["鲜椰冰咖", "设计感", "商务", "下午茶", "网红"],
     "lat": 30.2650, "lng": 120.1620, "rating": 4.3, "price": 40, "duration": 40},
    {"name": "Black Rainbow Coffee", "category": "咖啡厅", "tags": ["手冲", "蛋糕", "日系", "安静", "社区"],
     "lat": 30.2720, "lng": 120.1650, "rating": 4.5, "price": 50, "duration": 45},
    {"name": "Parking Coffee", "category": "咖啡厅", "tags": ["冠军咖啡", "手冲", "专业", "探店", "小众"],
     "lat": 30.2680, "lng": 120.1680, "rating": 4.6, "price": 45, "duration": 40},
    {"name": "SECTION COFFEE", "category": "咖啡厅", "tags": ["露营风", "拍照", "特调", "年轻人", "网红"],
     "lat": 30.2750, "lng": 120.1550, "rating": 4.4, "price": 40, "duration": 40},
    {"name": "灵隐寺慈悲咖啡", "category": "咖啡厅", "tags": ["寺庙", "禅意", "祈福", "特色", "文创"],
     "lat": 30.2410, "lng": 120.0970, "rating": 4.5, "price": 35, "duration": 30},
    {"name": "晓书馆咖啡", "category": "咖啡厅", "tags": ["书店", "文艺", "安静", "阅读", "良渚"],
     "lat": 30.4200, "lng": 120.0300, "rating": 4.4, "price": 40, "duration": 45},

    # ===== 购物 =====
    {"name": "湖滨银泰in77", "category": "购物服务", "tags": ["商场", "潮牌", "美食", "地铁直达", "年轻"],
     "lat": 30.2555, "lng": 120.1640, "rating": 4.5, "price": 0, "duration": 120},
    {"name": "武林夜市", "category": "购物服务", "tags": ["夜市", "小吃", "手作", "热闹", "平价"],
     "lat": 30.2750, "lng": 120.1650, "rating": 4.2, "price": 0, "duration": 90},
    {"name": "杭州大厦", "category": "购物服务", "tags": ["高端", "奢侈品", "老牌", "市中心", "全"],
     "lat": 30.2700, "lng": 120.1630, "rating": 4.3, "price": 0, "duration": 90},
    {"name": "万象城", "category": "购物服务", "tags": ["高端", "美食", "IMAX", "年轻", "钱塘江"],
     "lat": 30.2550, "lng": 120.2100, "rating": 4.4, "price": 0, "duration": 120},
    {"name": "嘉里中心", "category": "购物服务", "tags": ["年轻", "潮流", "美食", "市中心", "活动多"],
     "lat": 30.2600, "lng": 120.1600, "rating": 4.4, "price": 0, "duration": 90},
    {"name": "来福士中心", "category": "购物服务", "tags": ["现代", "美食", "双子塔", "年轻", "打卡"],
     "lat": 30.2500, "lng": 120.2050, "rating": 4.3, "price": 0, "duration": 90},
    {"name": "丝绸市场", "category": "购物服务", "tags": ["丝绸", "批发", "老字号", "旗袍", "伴手礼"],
     "lat": 30.2650, "lng": 120.1700, "rating": 4.1, "price": 0, "duration": 60},
    {"name": "四季青服装市场", "category": "购物服务", "tags": ["服装", "批发", "便宜", "淘宝", "量大"],
     "lat": 30.2500, "lng": 120.2200, "rating": 4.0, "price": 0, "duration": 120},
    {"name": "吴山花鸟市场", "category": "购物服务", "tags": ["花鸟", "宠物", "市井", "热闹", "生活"],
     "lat": 30.2370, "lng": 120.1620, "rating": 4.2, "price": 0, "duration": 45},

    # ===== 休闲娱乐/夜生活 =====
    {"name": "西湖音乐喷泉", "category": "休闲娱乐", "tags": ["喷泉", "夜景", "免费", "壮观", "拍照"],
     "lat": 30.2540, "lng": 120.1620, "rating": 4.3, "price": 0, "duration": 30},
    {"name": "印象西湖演出", "category": "休闲娱乐", "tags": ["演出", "夜景", "文化", "张艺谋", "震撼"],
     "lat": 30.2520, "lng": 120.1400, "rating": 4.5, "price": 340, "duration": 70},
    {"name": "杭州乐园", "category": "休闲娱乐", "tags": ["过山车", "刺激", "亲子", "水上", "尖叫"],
     "lat": 30.1600, "lng": 120.1550, "rating": 4.3, "price": 190, "duration": 240},
    {"name": "云曼温泉", "category": "休闲娱乐", "tags": ["温泉", "放松", "日式", "秋冬", "度假"],
     "lat": 30.1650, "lng": 120.1600, "rating": 4.4, "price": 198, "duration": 180},
    {"name": "清河坊夜游", "category": "休闲娱乐", "tags": ["夜景", "古街", "灯笼", "拍照", "文化"],
     "lat": 30.2410, "lng": 120.1680, "rating": 4.3, "price": 0, "duration": 60},
    {"name": "南山路酒吧街", "category": "休闲娱乐", "tags": ["酒吧", "夜生活", "文艺", "音乐", "年轻人"],
     "lat": 30.2300, "lng": 120.1500, "rating": 4.2, "price": 150, "duration": 120},
    {"name": "胜利河美食街", "category": "休闲娱乐", "tags": ["夜宵", "大排档", "热闹", "本地", "啤酒"],
     "lat": 30.2900, "lng": 120.1650, "rating": 4.3, "price": 80, "duration": 90},

    # ===== 其他文化/艺术 =====
    {"name": "西湖美术馆", "category": "博物馆", "tags": ["书画", "艺术", "免费", "安静", "文化"],
     "lat": 30.2540, "lng": 120.1380, "rating": 4.4, "price": 0, "duration": 50},
    {"name": "唐云艺术馆", "category": "博物馆", "tags": ["书画", "国画", "免费", "安静", "文化"],
     "lat": 30.2320, "lng": 120.1450, "rating": 4.3, "price": 0, "duration": 40},
    {"name": "韩美林艺术馆", "category": "博物馆", "tags": ["雕塑", "艺术", "设计", "福娃", "免费"],
     "lat": 30.2500, "lng": 120.1150, "rating": 4.5, "price": 0, "duration": 50},
    {"name": "良渚博物院", "category": "博物馆", "tags": ["史前", "玉器", "世界遗产", "文明", "免费"],
     "lat": 30.4200, "lng": 120.0300, "rating": 4.6, "price": 0, "duration": 60},
    {"name": "西泠印社", "category": "风景名胜", "tags": ["篆刻", "书法", "文化", "金石", "孤山"],
     "lat": 30.2520, "lng": 120.1360, "rating": 4.5, "price": 0, "duration": 40},
    {"name": "浙江省图书馆", "category": "文化", "tags": ["阅读", "安静", "学习", "免费", "古籍"],
     "lat": 30.2650, "lng": 120.1550, "rating": 4.3, "price": 0, "duration": 60},
    {"name": "晓风书屋", "category": "文化", "tags": ["独立书店", "文艺", "安静", "阅读", "小众"],
     "lat": 30.2570, "lng": 120.1400, "rating": 4.4, "price": 0, "duration": 40},

    # ===== 公园/自然 =====
    {"name": "太子湾公园", "category": "风景名胜", "tags": ["郁金香", "春天", "野餐", "拍照", "免费"],
     "lat": 30.2280, "lng": 120.1350, "rating": 4.6, "price": 0, "duration": 60},
    {"name": "杭州植物园", "category": "风景名胜", "tags": ["植物", "四季", "安静", "亲子", "梅花园"],
     "lat": 30.2620, "lng": 120.1220, "rating": 4.5, "price": 10, "duration": 90},
    {"name": "九溪烟树", "category": "风景名胜", "tags": ["溪流", "徒步", "茶园", "秋天", "免费"],
     "lat": 30.2050, "lng": 120.1050, "rating": 4.6, "price": 0, "duration": 120},
    {"name": "龙井村", "category": "风景名胜", "tags": ["茶园", "茶文化", "徒步", "农家菜", "采茶"],
     "lat": 30.2150, "lng": 120.1150, "rating": 4.5, "price": 0, "duration": 90},
    {"name": "满觉陇", "category": "风景名胜", "tags": ["桂花", "秋天", "民宿", "安静", "喝茶"],
     "lat": 30.2200, "lng": 120.1250, "rating": 4.4, "price": 0, "duration": 60},
    {"name": "云栖竹径", "category": "风景名胜", "tags": ["竹林", "徒步", "安静", "洗肺", "免费"],
     "lat": 30.1900, "lng": 120.0950, "rating": 4.5, "price": 8, "duration": 90},
    {"name": "虎跑公园", "category": "风景名胜", "tags": ["泉水", "李叔同", "自然", "安静", "泡茶"],
     "lat": 30.2180, "lng": 120.1450, "rating": 4.4, "price": 15, "duration": 60},
    {"name": "六和塔", "category": "风景名胜", "tags": ["古塔", "钱塘江", "登高", "历史", "视野"],
     "lat": 30.1900, "lng": 120.1300, "rating": 4.5, "price": 20, "duration": 50},
    {"name": "白塔公园", "category": "风景名胜", "tags": ["铁路", "樱花", "文艺", "拍照", "亲子"],
     "lat": 30.1950, "lng": 120.1250, "rating": 4.4, "price": 0, "duration": 60},
    {"name": "八卦田遗址公园", "category": "风景名胜", "tags": ["农耕", "亲子", "历史", "油菜花", "免费"],
     "lat": 30.2150, "lng": 120.1400, "rating": 4.3, "price": 0, "duration": 50},

    # ===== 西湖区深处 =====
    {"name": "茅家埠", "category": "风景名胜", "tags": ["湿地", "野趣", "人少", "拍照", "免费"],
     "lat": 30.2600, "lng": 120.1280, "rating": 4.5, "price": 0, "duration": 60},
    {"name": "郭庄", "category": "风景名胜", "tags": ["园林", "古典", "茶室", "安静", "小众"],
     "lat": 30.2580, "lng": 120.1320, "rating": 4.4, "price": 10, "duration": 50},
    {"name": "杭州花圃", "category": "风景名胜", "tags": ["花卉", "春天", "免费", "拍照", "亲子"],
     "lat": 30.2650, "lng": 120.1250, "rating": 4.3, "price": 0, "duration": 50},
    {"name": "岳王庙", "category": "风景名胜", "tags": ["历史", "岳飞", "爱国", "文化", "古建筑"],
     "lat": 30.2500, "lng": 120.1350, "rating": 4.5, "price": 25, "duration": 50},
    {"name": "于谦祠", "category": "风景名胜", "tags": ["历史", "古建筑", "安静", "文化", "小众"],
     "lat": 30.2480, "lng": 120.1330, "rating": 4.3, "price": 0, "duration": 40},
    {"name": "章太炎纪念馆", "category": "博物馆", "tags": ["历史", "名人", "免费", "文化", "教育"],
     "lat": 30.2490, "lng": 120.1340, "rating": 4.2, "price": 0, "duration": 40},
    {"name": "张苍水祠", "category": "风景名胜", "tags": ["历史", "古建筑", "安静", "文化", "西湖"],
     "lat": 30.2470, "lng": 120.1360, "rating": 4.2, "price": 0, "duration": 30},
    {"name": "茶叶博物馆", "category": "博物馆", "tags": ["茶文化", "免费", "建筑美", "拍照", "教育"],
     "lat": 30.2220, "lng": 120.1280, "rating": 4.5, "price": 0, "duration": 60},
    {"name": "中国茶叶博物馆龙井馆区", "category": "博物馆", "tags": ["茶文化", "龙井", "建筑美", "拍照", "安静"],
     "lat": 30.2180, "lng": 120.1250, "rating": 4.4, "price": 0, "duration": 50},
    {"name": "双峰插云", "category": "风景名胜", "tags": ["西湖十景", "登山", "云雾", "拍照", "免费"],
     "lat": 30.2680, "lng": 120.1200, "rating": 4.3, "price": 0, "duration": 60},
    {"name": "青芝坞", "category": "风景名胜", "tags": ["民宿", "文艺", "美食", "拍照", "慢生活"],
     "lat": 30.2660, "lng": 120.1230, "rating": 4.4, "price": 0, "duration": 60},
    {"name": "浙大玉泉校区", "category": "文化", "tags": ["高校", "建筑", "历史", "免费", "拍照"],
     "lat": 30.2640, "lng": 120.1260, "rating": 4.5, "price": 0, "duration": 45},

    # ===== 钱江新城/上城东部 =====
    {"name": "市民中心", "category": "文化", "tags": ["建筑", "现代", "打卡", "免费", "市政府"],
     "lat": 30.2450, "lng": 120.2100, "rating": 4.2, "price": 0, "duration": 30},
    {"name": "城市阳台", "category": "风景名胜", "tags": ["观景", "钱塘江", "夜景", "免费", "吹风"],
     "lat": 30.2480, "lng": 120.2120, "rating": 4.5, "price": 0, "duration": 40},
    {"name": "杭州大剧院", "category": "文化", "tags": ["演出", "建筑", "艺术", "现代", "地标"],
     "lat": 30.2470, "lng": 120.2080, "rating": 4.4, "price": 0, "duration": 60},
    {"name": "钱塘江夜游", "category": "休闲娱乐", "tags": ["游船", "夜景", "浪漫", "灯光", "地标"],
     "lat": 30.2500, "lng": 120.2150, "rating": 4.3, "price": 138, "duration": 60},
    {"name": "钱江新城灯光秀", "category": "休闲娱乐", "tags": ["夜景", "灯光", "免费", "震撼", "打卡"],
     "lat": 30.2490, "lng": 120.2110, "rating": 4.4, "price": 0, "duration": 30},
    {"name": "砂之船奥特莱斯", "category": "购物服务", "tags": ["outlet", "打折", "品牌", "购物", "餐饮"],
     "lat": 30.2460, "lng": 120.2130, "rating": 4.2, "price": 0, "duration": 120},
    {"name": "杭州国际会议中心", "category": "文化", "tags": ["建筑", "会议", "现代", "地标", "金球"],
     "lat": 30.2440, "lng": 120.2090, "rating": 4.1, "price": 0, "duration": 20},

    # ===== 滨江区 =====
    {"name": "星光大道", "category": "购物服务", "tags": ["商场", "电影", "美食", "年轻", "滨江"],
     "lat": 30.2100, "lng": 120.2050, "rating": 4.3, "price": 0, "duration": 90},
    {"name": "滨江龙湖天街", "category": "购物服务", "tags": ["商场", "潮牌", "美食", "亲子", "打卡"],
     "lat": 30.2050, "lng": 120.2100, "rating": 4.4, "price": 0, "duration": 120},
    {"name": "杭州印", "category": "风景名胜", "tags": ["建筑", "地标", "拍照", "现代", "钱塘江"],
     "lat": 30.2150, "lng": 120.2000, "rating": 4.2, "price": 0, "duration": 30},
    {"name": "白马湖公园", "category": "风景名胜", "tags": ["花海", "动漫", "免费", "亲子", "野餐"],
     "lat": 30.1650, "lng": 120.1950, "rating": 4.3, "price": 0, "duration": 60},
    {"name": "中国动漫博物馆", "category": "博物馆", "tags": ["动漫", "亲子", "互动", "拍照", "免费"],
     "lat": 30.1680, "lng": 120.1980, "rating": 4.5, "price": 0, "duration": 90},
    {"name": "西兴古镇", "category": "风景名胜", "tags": ["古镇", "运河", "安静", "历史", "小众"],
     "lat": 30.2000, "lng": 120.2150, "rating": 4.2, "price": 0, "duration": 50},
    {"name": "物联网小镇", "category": "文化", "tags": ["科技", "现代", "企业", "打卡", "创新"],
     "lat": 30.2080, "lng": 120.2200, "rating": 4.0, "price": 0, "duration": 30},
    {"name": "钱塘江樱花跑道", "category": "风景名胜", "tags": ["跑步", "樱花", "江景", "免费", "春天"],
     "lat": 30.2120, "lng": 120.2020, "rating": 4.4, "price": 0, "duration": 40},

    # ===== 萧山区 =====
    {"name": "奥体中心", "category": "文化", "tags": ["体育", "建筑", "地标", "演唱会", "莲花碗"],
     "lat": 30.2300, "lng": 120.2300, "rating": 4.5, "price": 0, "duration": 45},
    {"name": "钱江世纪城公园", "category": "风景名胜", "tags": ["公园", "江景", "夜景", "免费", "休闲"],
     "lat": 30.2350, "lng": 120.2350, "rating": 4.2, "price": 0, "duration": 50},
    {"name": "萧山博物馆", "category": "博物馆", "tags": ["历史", "文物", "免费", "文化", "教育"],
     "lat": 30.1800, "lng": 120.2600, "rating": 4.2, "price": 0, "duration": 50},
    {"name": "跨湖桥遗址博物馆", "category": "博物馆", "tags": ["史前", "独木舟", "考古", "免费", "教育"],
     "lat": 30.1550, "lng": 120.2500, "rating": 4.3, "price": 0, "duration": 50},
    {"name": "东方文化园", "category": "风景名胜", "tags": ["宗教", "建筑", "文化", "祈福", "大型"],
     "lat": 30.1400, "lng": 120.2400, "rating": 4.1, "price": 80, "duration": 120},
    {"name": "烂苹果乐园", "category": "休闲娱乐", "tags": ["亲子", "室内", "游乐", "互动", "彩色"],
     "lat": 30.1650, "lng": 120.1550, "rating": 4.3, "price": 160, "duration": 180},
    {"name": "浪浪浪水公园", "category": "休闲娱乐", "tags": ["水上游乐", "夏天", "刺激", "亲子", "滑梯"],
     "lat": 30.1620, "lng": 120.1580, "rating": 4.2, "price": 150, "duration": 180},
    {"name": "北干山", "category": "风景名胜", "tags": ["登山", "观景", "免费", "晨练", "城市"],
     "lat": 30.1750, "lng": 120.2650, "rating": 4.1, "price": 0, "duration": 60},
    {"name": "余暨公园", "category": "风景名胜", "tags": ["公园", "湖泊", "免费", "休闲", "亲子"],
     "lat": 30.1850, "lng": 120.2550, "rating": 4.0, "price": 0, "duration": 40},

    # ===== 余杭区 =====
    {"name": "梦想小镇", "category": "文化", "tags": ["创业", "古镇", "互联网", "拍照", "免费"],
     "lat": 30.2800, "lng": 120.0000, "rating": 4.4, "price": 0, "duration": 60},
    {"name": "人工智能小镇", "category": "文化", "tags": ["科技", "现代", "未来", "打卡", "免费"],
     "lat": 30.2850, "lng": 119.9950, "rating": 4.1, "price": 0, "duration": 30},
    {"name": "径山寺", "category": "风景名胜", "tags": ["寺庙", "禅宗", "茶道", "登山", "安静"],
     "lat": 30.3500, "lng": 119.8500, "rating": 4.6, "price": 20, "duration": 120},
    {"name": "双溪漂流", "category": "休闲娱乐", "tags": ["漂流", "夏天", "刺激", "亲子", "竹筏"],
     "lat": 30.3200, "lng": 119.8800, "rating": 4.3, "price": 100, "duration": 120},
    {"name": "山沟沟", "category": "风景名胜", "tags": ["自然", "瀑布", "徒步", "农家乐", "避暑"],
     "lat": 30.3800, "lng": 119.8000, "rating": 4.2, "price": 50, "duration": 180},
    {"name": "良渚古城遗址公园", "category": "风景名胜", "tags": ["世界遗产", "史前", "稻田", "鹿苑", "文化"],
     "lat": 30.4100, "lng": 120.0200, "rating": 4.6, "price": 60, "duration": 180},
    {"name": "美丽洲公园", "category": "风景名胜", "tags": ["公园", "湿地", "免费", "亲子", "野餐"],
     "lat": 30.4050, "lng": 120.0250, "rating": 4.3, "price": 0, "duration": 50},
    {"name": "五常湿地", "category": "风景名胜", "tags": ["湿地", "自然", "免费", "安静", "徒步"],
     "lat": 30.2900, "lng": 120.0300, "rating": 4.2, "price": 0, "duration": 60},
    {"name": "未来科技城学术交流中心", "category": "文化", "tags": ["建筑", "科技", "现代", "地标", "会议"],
     "lat": 30.2820, "lng": 119.9980, "rating": 4.0, "price": 0, "duration": 20},

    # ===== 拱墅区扩展 =====
    {"name": "杭州新天地", "category": "购物服务", "tags": ["商场", "演艺", "夜生活", "年轻", "活力"],
     "lat": 30.3100, "lng": 120.1750, "rating": 4.3, "price": 0, "duration": 90},
    {"name": "太阳马戏《X绮幻之境》", "category": "休闲娱乐", "tags": ["演出", "震撼", "杂技", "艺术", "必看"],
     "lat": 30.3120, "lng": 120.1780, "rating": 4.6, "price": 380, "duration": 90},
    {"name": "半山国家森林公园", "category": "风景名胜", "tags": ["森林", "登山", "免费", "洗肺", "亲子"],
     "lat": 30.3500, "lng": 120.1800, "rating": 4.3, "price": 0, "duration": 120},
    {"name": "虎山水库", "category": "风景名胜", "tags": ["水库", "安静", "钓鱼", "自然", "免费"],
     "lat": 30.3450, "lng": 120.1780, "rating": 4.1, "price": 0, "duration": 40},
    {"name": "运河上街", "category": "购物服务", "tags": ["商场", "美食", "亲子", "运河", "便利"],
     "lat": 30.3050, "lng": 120.1550, "rating": 4.2, "price": 0, "duration": 90},

    # ===== 临安区 =====
    {"name": "青山湖国家森林公园", "category": "风景名胜", "tags": ["森林", "湖泊", "骑行", "免费", "自然"],
     "lat": 30.2300, "lng": 119.7200, "rating": 4.5, "price": 0, "duration": 180},
    {"name": "大明山", "category": "风景名胜", "tags": ["滑雪", "登山", "云海", "秋天", "壮观"],
     "lat": 30.0500, "lng": 118.9500, "rating": 4.5, "price": 88, "duration": 240},
    {"name": "天目山", "category": "风景名胜", "tags": ["古树", "森林", "避暑", "佛教", "自然"],
     "lat": 30.3200, "lng": 119.4200, "rating": 4.6, "price": 110, "duration": 240},
    {"name": "浙西大峡谷", "category": "风景名胜", "tags": ["峡谷", "漂流", "瀑布", "自然", "徒步"],
     "lat": 30.1500, "lng": 118.8500, "rating": 4.4, "price": 100, "duration": 240},
    {"name": "太湖源", "category": "风景名胜", "tags": ["溪流", "瀑布", "夏天", "清凉", "自然"],
     "lat": 30.1800, "lng": 119.4500, "rating": 4.3, "price": 70, "duration": 180},
    {"name": "柳溪江", "category": "风景名胜", "tags": ["竹筏", "江景", "安静", "自然", "夏天"],
     "lat": 30.1200, "lng": 119.3000, "rating": 4.2, "price": 60, "duration": 120},
    {"name": "临安博物馆", "category": "博物馆", "tags": ["建筑", "文物", "普利兹克", "免费", "文化"],
     "lat": 30.2250, "lng": 119.7000, "rating": 4.4, "price": 0, "duration": 60},
    {"name": "钱王陵", "category": "风景名胜", "tags": ["历史", "吴越国", "文化", "安静", "免费"],
     "lat": 30.2280, "lng": 119.7100, "rating": 4.2, "price": 0, "duration": 40},

    # ===== 富阳区 =====
    {"name": "龙门古镇", "category": "风景名胜", "tags": ["古镇", "孙权", "明清", "拍照", "文化"],
     "lat": 29.9500, "lng": 119.9500, "rating": 4.4, "price": 70, "duration": 120},
    {"name": "富春江", "category": "风景名胜", "tags": ["江景", "小三峡", "游船", "自然", "免费"],
     "lat": 30.0500, "lng": 119.9500, "rating": 4.5, "price": 0, "duration": 120},
    {"name": "黄公望隐居地", "category": "风景名胜", "tags": ["书画", "富春山居图", "竹林", "文化", "安静"],
     "lat": 30.0800, "lng": 119.9800, "rating": 4.4, "price": 50, "duration": 90},
    {"name": "新沙岛", "category": "风景名胜", "tags": ["岛屿", "农家乐", "采摘", "亲子", "免费"],
     "lat": 30.0200, "lng": 119.9200, "rating": 4.1, "price": 0, "duration": 120},
    {"name": "杭州野生动物世界", "category": "休闲娱乐", "tags": ["动物", "亲子", "自驾", "互动", "大型"],
     "lat": 30.1800, "lng": 119.9800, "rating": 4.5, "price": 220, "duration": 240},
    {"name": "东吴文化公园", "category": "风景名胜", "tags": ["公园", "三国", "文化", "免费", "亲子"],
     "lat": 30.0300, "lng": 119.9400, "rating": 4.2, "price": 0, "duration": 60},
    {"name": "鹳山", "category": "风景名胜", "tags": ["登山", "江景", "免费", "文化", "历史"],
     "lat": 30.0400, "lng": 119.9300, "rating": 4.1, "price": 0, "duration": 60},

    # ===== 更多美食 =====
    {"name": "龙井菜馆", "category": "餐饮服务", "tags": ["杭帮菜", "龙井", "环境好", "茶园", "家常"],
     "lat": 30.2200, "lng": 120.1180, "rating": 4.3, "price": 120, "duration": 75},
    {"name": "茶人村", "category": "餐饮服务", "tags": ["杭帮菜", "茶香", "私房", "环境好", "小众"],
     "lat": 30.2180, "lng": 120.1200, "rating": 4.4, "price": 130, "duration": 75},
    {"name": "朴墅餐厅", "category": "餐饮服务", "tags": ["创意菜", "青芝坞", "环境好", "年轻人", "拍照"],
     "lat": 30.2670, "lng": 120.1240, "rating": 4.3, "price": 110, "duration": 75},
    {"name": "素描餐厅", "category": "餐饮服务", "tags": ["创意菜", "灵隐", "环境好", "榴莲烤鸡", "网红"],
     "lat": 30.2390, "lng": 120.0960, "rating": 4.4, "price": 100, "duration": 75},
    {"name": "马灯部落", "category": "餐饮服务", "tags": ["西餐", "四眼井", "露台", "拍照", "约会"],
     "lat": 30.2320, "lng": 120.1400, "rating": 4.3, "price": 140, "duration": 75},
    {"name": "弄堂里", "category": "餐饮服务", "tags": ["杭帮菜", "便宜", "家常", "排队", "卤鸡爪"],
     "lat": 30.2600, "lng": 120.1500, "rating": 4.3, "price": 70, "duration": 60},
    {"name": "慧娟面馆", "category": "餐饮服务", "tags": ["片儿川", "拌川", "老店", "夜宵", "地道"],
     "lat": 30.2750, "lng": 120.1750, "rating": 4.3, "price": 35, "duration": 40},
    {"name": "阿强面馆", "category": "餐饮服务", "tags": ["拌川", "猪肝", "市井", "排队", "地道"],
     "lat": 30.2480, "lng": 120.1760, "rating": 4.2, "price": 30, "duration": 40},
    {"name": "方传面馆", "category": "餐饮服务", "tags": ["片儿川", "拌川", "老字号", "平价", "本地"],
     "lat": 30.2520, "lng": 120.1680, "rating": 4.2, "price": 28, "duration": 35},
    {"name": "复兴面王", "category": "餐饮服务", "tags": ["拌川", "腰花", "市井", "排队", "网红"],
     "lat": 30.2550, "lng": 120.1700, "rating": 4.3, "price": 35, "duration": 40},
    {"name": "小狗面馆", "category": "餐饮服务", "tags": ["拌川", "肉丝", "老店", "市井", "平价"],
     "lat": 30.2500, "lng": 120.1740, "rating": 4.2, "price": 25, "duration": 35},
    {"name": "荣鲜面馆", "category": "餐饮服务", "tags": ["片儿川", "海鲜", "老店", "平价", "本地"],
     "lat": 30.2530, "lng": 120.1720, "rating": 4.2, "price": 30, "duration": 35},
    {"name": "叶马茶楼", "category": "餐饮服务", "tags": ["杭帮菜", "私房", "黄鱼", "家庭", "老店"],
     "lat": 30.2580, "lng": 120.1380, "rating": 4.4, "price": 130, "duration": 75},
    {"name": "民厨饭堂", "category": "餐饮服务", "tags": ["杭帮菜", "家常", "便宜", "本地", "小菜"],
     "lat": 30.2650, "lng": 120.1560, "rating": 4.2, "price": 60, "duration": 60},
    {"name": "金猪", "category": "餐饮服务", "tags": ["杭帮菜", "便宜", "排队", "家常", "武林"],
     "lat": 30.2700, "lng": 120.1650, "rating": 4.3, "price": 55, "duration": 60},
    {"name": "笑典皇", "category": "餐饮服务", "tags": ["绍兴菜", "霉干菜", "老店", "本地", "下酒"],
     "lat": 30.2680, "lng": 120.1730, "rating": 4.2, "price": 90, "duration": 60},
    {"name": "宝中宝食府", "category": "餐饮服务", "tags": ["杭帮菜", "腰花", "老店", "家常", "本地"],
     "lat": 30.2400, "lng": 120.1710, "rating": 4.3, "price": 100, "duration": 60},
    {"name": "福缘居", "category": "餐饮服务", "tags": ["杭帮菜", "脆皮大肠", "排队", "老店", "河坊街"],
     "lat": 30.2410, "lng": 120.1690, "rating": 4.4, "price": 95, "duration": 60},
    {"name": "大头隐食", "category": "餐饮服务", "tags": ["创意菜", "馒头山", "环境好", "拍照", "私房"],
     "lat": 30.2150, "lng": 120.1600, "rating": 4.3, "price": 110, "duration": 75},
    {"name": "圈子餐厅", "category": "餐饮服务", "tags": ["西餐", "牛排", "约会", "环境好", "拍照"],
     "lat": 30.2720, "lng": 120.1580, "rating": 4.2, "price": 160, "duration": 90},

    # ===== 更多茶馆/书店 =====
    {"name": "青藤茶馆", "category": "咖啡厅", "tags": ["茶馆", "自助", "传统", "商务", "西湖"],
     "lat": 30.2540, "lng": 120.1450, "rating": 4.3, "price": 100, "duration": 120},
    {"name": "和茶馆", "category": "咖啡厅", "tags": ["茶馆", "安静", "禅意", "小众", "拍照"],
     "lat": 30.2560, "lng": 120.1430, "rating": 4.4, "price": 80, "duration": 90},
    {"name": "法云安缦咖啡厅", "category": "咖啡厅", "tags": ["高端", "禅意", "环境好", "隐秘", "品质"],
     "lat": 30.2390, "lng": 120.0950, "rating": 4.7, "price": 120, "duration": 60},
    {"name": "纯真年代书吧", "category": "咖啡厅", "tags": ["书店", "湖景", "文艺", "安静", "宝石山"],
     "lat": 30.2600, "lng": 120.1480, "rating": 4.5, "price": 50, "duration": 60},
    {"name": "钟书阁", "category": "文化", "tags": ["书店", "设计感", "镜面", "拍照", "网红"],
     "lat": 30.2500, "lng": 120.2150, "rating": 4.4, "price": 0, "duration": 45},
    {"name": "西西弗书店", "category": "文化", "tags": ["书店", "咖啡", "连锁", "文艺", "阅读"],
     "lat": 30.2550, "lng": 120.1650, "rating": 4.3, "price": 0, "duration": 40},
    {"name": "网易蜗牛读书馆", "category": "文化", "tags": ["书店", "免费", "现代", "滨江", "阅读"],
     "lat": 30.2080, "lng": 120.2050, "rating": 4.3, "price": 0, "duration": 45},

    # ===== 高端酒店 =====
    {"name": "西湖国宾馆", "category": "酒店宾馆", "tags": ["国宾馆", "西湖", "园林", "高端", "历史"],
     "lat": 30.2350, "lng": 120.1300, "rating": 4.8, "price": 1200, "duration": 30},
    {"name": "西子湖四季酒店", "category": "酒店宾馆", "tags": ["奢华", "园林", "SPA", "西湖", "服务"],
     "lat": 30.2400, "lng": 120.1280, "rating": 4.8, "price": 2500, "duration": 30},
    {"name": "法云安缦", "category": "酒店宾馆", "tags": ["顶级", "禅意", "古村落", "隐秘", "奢华"],
     "lat": 30.2380, "lng": 120.0940, "rating": 4.9, "price": 5000, "duration": 30},
    {"name": "杭州悦榕庄", "category": "酒店宾馆", "tags": ["奢华", "运河", "SPA", "度假", "静谧"],
     "lat": 30.2980, "lng": 120.1530, "rating": 4.7, "price": 2000, "duration": 30},
    {"name": "杭州柏悦酒店", "category": "酒店宾馆", "tags": ["高端", "钱江新城", "云端", "设计", "服务"],
     "lat": 30.2470, "lng": 120.2110, "rating": 4.7, "price": 1800, "duration": 30},
    {"name": "杭州康莱德酒店", "category": "酒店宾馆", "tags": ["高端", "来福士", "设计", "江景", "服务"],
     "lat": 30.2500, "lng": 120.2050, "rating": 4.6, "price": 1600, "duration": 30},
    {"name": "杭州洲际酒店", "category": "酒店宾馆", "tags": ["地标", "金球", "江景", "商务", "高端"],
     "lat": 30.2440, "lng": 120.2090, "rating": 4.6, "price": 1400, "duration": 30},
    {"name": "杭州君悦酒店", "category": "酒店宾馆", "tags": ["高端", "湖滨", "湖景", "便利", "服务"],
     "lat": 30.2560, "lng": 120.1630, "rating": 4.7, "price": 1500, "duration": 30},
    {"name": "钱江新城万豪酒店", "category": "酒店宾馆", "tags": ["高端", "江景", "商务", "现代", "服务"],
     "lat": 30.2430, "lng": 120.2100, "rating": 4.6, "price": 1300, "duration": 30},
    {"name": "木守西溪", "category": "酒店宾馆", "tags": ["设计", "西溪", "静谧", "高端", "隐逸"],
     "lat": 30.2680, "lng": 120.0600, "rating": 4.7, "price": 2200, "duration": 30},

    # ===== 更多夜生活/娱乐 =====
    {"name": "響Livehouse", "category": "休闲娱乐", "tags": ["音乐", "酒吧", "现场", "年轻", "氛围"],
     "lat": 30.2550, "lng": 120.1650, "rating": 4.3, "price": 200, "duration": 120},
    {"name": "MAO Livehouse", "category": "休闲娱乐", "tags": ["摇滚", "演出", "现场", "年轻", "热血"],
     "lat": 30.2600, "lng": 120.1700, "rating": 4.4, "price": 180, "duration": 120},
    {"name": "大麦·66LiveHouse", "category": "休闲娱乐", "tags": ["演出", "音乐", "现场", "年轻", "潮流"],
     "lat": 30.2750, "lng": 120.1750, "rating": 4.3, "price": 160, "duration": 120},
    {"name": "新天地活力Park", "category": "休闲娱乐", "tags": ["夜市", "演艺", "酒吧", "年轻", "活力"],
     "lat": 30.3110, "lng": 120.1770, "rating": 4.3, "price": 100, "duration": 120},
    {"name": "远洋乐堤港", "category": "购物服务", "tags": ["商场", "艺术", "美食", "运河", "年轻"],
     "lat": 30.3000, "lng": 120.1500, "rating": 4.3, "price": 0, "duration": 90},
    {"name": "城西银泰城", "category": "购物服务", "tags": ["商场", "美食", "亲子", "地铁", "热闹"],
     "lat": 30.2850, "lng": 120.1150, "rating": 4.4, "price": 0, "duration": 120},
    {"name": "中大银泰城", "category": "购物服务", "tags": ["商场", "美食", "亲子", "拱墅", "便利"],
     "lat": 30.3150, "lng": 120.1750, "rating": 4.2, "price": 0, "duration": 90},
    {"name": "龙湖滨江天街", "category": "购物服务", "tags": ["商场", "潮牌", "美食", "滨江", "年轻"],
     "lat": 30.2080, "lng": 120.2080, "rating": 4.4, "price": 0, "duration": 120},
    {"name": "萧山万象汇", "category": "购物服务", "tags": ["商场", "美食", "亲子", "萧山", "地铁"],
     "lat": 30.1850, "lng": 120.2650, "rating": 4.3, "price": 0, "duration": 120},

]

# UGC关键词库
UGC_KEYWORDS = {
    "景点": ["景色美", "值得去", "人多", "拍照出片", "有历史", "空气好", "门票贵", "建议早去"],
    "餐饮": ["味道好", "排队久", "性价比高", "服务一般", "分量足", "环境好", "必点菜", "提前预约"],
    "咖啡厅": ["咖啡香", "适合办公", "拍照好看", "座位少", "价格偏贵", "氛围好"],
    "购物": ["品牌多", "好逛", "停车难", "吃饭方便", "周末人多"],
    "博物馆": ["涨知识", "安静", "免费", "值得二刷", "讲解好", "亲子适合"],
    "休闲娱乐": ["好玩", "刺激", "放松", "值得票价", "人不多", "推荐"],
    "文化": ["文艺", "安静", "有格调", "适合发呆", "小众"],
}


def enrich_poi(poi: dict, index: int) -> dict:
    """为POI添加额外字段"""
    business_hours_map = {
        "风景名胜": "全天开放" if poi["price"] == 0 else "08:00-17:00",
        "餐饮服务": "10:30-21:00",
        "咖啡厅": "08:00-22:00",
        "购物服务": "10:00-22:00",
        "休闲娱乐": "09:00-21:00",
        "博物馆": "09:00-17:00",
        "文化": "09:00-21:00",
    }

    category_type = "景点"
    if poi["category"] == "餐饮服务":
        category_type = "餐饮"
    elif poi["category"] == "咖啡厅":
        category_type = "咖啡厅"
    elif poi["category"] == "购物服务":
        category_type = "购物"
    elif poi["category"] == "博物馆":
        category_type = "博物馆"
    elif poi["category"] == "休闲娱乐":
        category_type = "休闲娱乐"
    elif poi["category"] == "文化":
        category_type = "文化"

    keywords = UGC_KEYWORDS.get(category_type, [])
    selected_keywords = random.sample(keywords, min(3, len(keywords)))

    rating = round(min(5.0, max(3.5, poi["rating"] + random.uniform(-0.2, 0.2))), 1)

    poi_id = f"mock_hangzhou_{index:03d}"
    # 使用本地生成的封面图
    photos = [
        f"images/pois/{poi_id}.jpg",
    ]

    return {
        "poi_id": poi_id,
        "name": poi["name"],
        "city": "杭州",
        "district": random.choice(["西湖区", "上城区", "拱墅区", "滨江区", "余杭区", "萧山区"]),
        "category": poi["category"],
        "address": f"杭州市{random.choice(['西湖区', '上城区', '拱墅区', '余杭区'])}某某路{random.randint(1, 999)}号",
        "location": {
            "lat": poi["lat"] + random.uniform(-0.001, 0.001),
            "lng": poi["lng"] + random.uniform(-0.001, 0.001),
        },
        "tel": f"0571-{random.randint(80000000, 89999999)}",
        "rating": rating,
        "price": poi["price"],
        "business_hours": business_hours_map.get(poi["category"], "09:00-18:00"),
        "suggested_duration": poi["duration"],
        "tags": poi["tags"],
        "ugc_keywords": selected_keywords,
        "highlights": f"{poi['tags'][0]}是这里的最大特色",
        "photos": photos,
        "source": "mock"
    }


def generate_mock_pois() -> list:
    pois = []
    for i, raw in enumerate(HANGZHOU_POIS):
        enriched = enrich_poi(raw, i)
        pois.append(enriched)
    return pois


def main():
    print("=" * 50)
    print("生成杭州高质量Mock POI数据 V2")
    print("=" * 50)

    pois = generate_mock_pois()

    categories = {}
    for p in pois:
        cat = p["category"]
        categories[cat] = categories.get(cat, 0) + 1

    print(f"\n共生成 {len(pois)} 个POI:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}个")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, "杭州_pois_mock.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] 已保存到: {filepath}")

    print("\n数据示例（前5条）:")
    for p in pois[:5]:
        print(f"  -> {p['name']} | {p['category']} | 评分:{p['rating']} | 标签:{','.join(p['tags'])}")


if __name__ == "__main__":
    main()
