# -*- coding: utf-8 -*-
"""
并发性能测试 - Locust

安装:
    pip install locust

运行:
    locust -f tests/locustfile.py --host=http://localhost:8000
    # 然后在浏览器打开 http://localhost:8089 配置并发用户数

或命令行直接运行:
    locust -f tests/locustfile.py --host=http://localhost:8000 -u 10 -r 2 -t 60s --headless
"""

from locust import HttpUser, task, between


class RoutePlannerUser(HttpUser):
    """模拟用户使用路线规划系统"""
    
    wait_time = between(1, 3)  # 每个任务之间等待1-3秒
    
    def on_start(self):
        """每个用户启动时先检查健康状态"""
        self.client.get("/")
    
    @task(3)
    def plan_with_preferences(self):
        """结构化偏好请求（最常见）"""
        payload = {
            "city": "杭州",
            "start_time": "09:00",
            "end_time": "18:00",
            "budget": 500,
            "preferences": ["美食", "拍照"],
            "travelers": "情侣",
            "pace": "适中",
            "transport_mode": "步行"
        }
        with self.client.post("/api/plan", json=payload, catch_response=True) as resp:
            if resp.status_code == 200:
                data = resp.json()
                if data.get("plans") and len(data["plans"]) == 3:
                    resp.success()
                else:
                    resp.failure("返回路线数量不正确")
            else:
                resp.failure(f"状态码 {resp.status_code}")
    
    @task(2)
    def plan_with_raw_query(self):
        """自然语言请求（LLM解析路径，较慢）"""
        payload = {
            "raw_query": "周末带女朋友去杭州玩，喜欢拍照和吃辣",
            "city": "杭州",
            "start_time": "09:00",
            "end_time": "18:00",
            "budget": 500,
            "preferences": ["美食", "拍照"],
            "travelers": "情侣",
            "pace": "适中"
        }
        with self.client.post("/api/plan", json=payload, catch_response=True, timeout=60) as resp:
            if resp.status_code == 200:
                data = resp.json()
                if data.get("plans") and len(data["plans"]) == 3:
                    resp.success()
                else:
                    resp.failure("返回路线数量不正确")
            else:
                resp.failure(f"状态码 {resp.status_code}")
    
    @task(2)
    def plan_family_trip(self):
        """亲子出行场景"""
        payload = {
            "city": "杭州",
            "start_time": "09:00",
            "end_time": "16:00",
            "budget": 400,
            "preferences": ["自然", "娱乐"],
            "travelers": "亲子",
            "pace": "悠闲"
        }
        with self.client.post("/api/plan", json=payload, catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"状态码 {resp.status_code}")
    
    @task(1)
    def plan_budget_trip(self):
        """经济型独自出行"""
        payload = {
            "city": "杭州",
            "start_time": "09:00",
            "end_time": "17:00",
            "budget": 150,
            "preferences": ["文化"],
            "travelers": "独自",
            "pace": "适中"
        }
        with self.client.post("/api/plan", json=payload, catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"状态码 {resp.status_code}")
    
    @task(1)
    def get_cities(self):
        """获取城市列表"""
        self.client.get("/api/cities")
