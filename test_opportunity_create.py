#!/usr/bin/env python
"""
测试商机创建功能
"""
import requests
import json

API_BASE = "http://127.0.0.1:8001"

# 首先登录获取 token
login_data = {
    "username": "admin",
    "password": "123456"
}

print("正在登录...")
response = requests.post(f"{API_BASE}/api/auth/login", json=login_data)
if response.status_code != 200:
    print(f"登录失败: {response.status_code} - {response.text}")
    exit(1)

token_data = response.json()
token = token_data["access_token"]
print(f"登录成功，获取到 token")

# 创建商机数据
opportunity_data = {
    "name": "测试商机 - 客户A - 产品B",
    "stage": "初步接触",
    "status": "new",
    "amount": 100000.0,
    "source": "manual",

    # 评分维度字段（必须包含，否则后端验证会失败）
    "industry": None,
    "industry_rank": None,
    "scene": None,
    "budget": None,
    "labor_cost": None,
    "daily_calls": None,
    "leader_owner": None,
    "lowest_price": None,
    "initiator_department": None,
    "competitor": None,
    "bidding_type": None,
    "has_ai_project": None,
    "customer_service_size": None,
    "region": None,

    # 客户商机管理表字段
    "customer_name": "客户A",
    "customer_type": "新客户",
    "requirement_desc": "测试需求描述",
    "product_name": "产品B",
    "estimated_cycle": "3个月",
    "opportunity_level": "A",
    "project_date": "2026-04-22",
    "project_members": "张三、李四",
    "solution_communication": "方案沟通中",
    "poc_status": "正在对接",
    "key_person_approved": "是",
    "bid_probability": "A",
    "contract_negotiation": "未启动",
    "project_type": "SaaS",
    "contract_signed": "否",
    "handoff_completed": "否",

    "custom_fields": {
        "owner_name_display": "admin",
        "customer_name": "客户A",
        "customer_type": "新客户",
        "requirement_desc": "测试需求描述",
        "product_name": "产品B",
        "estimated_cycle": "3个月",
        "opportunity_level": "A",
        "project_date": "2026-04-22",
        "project_members": "张三、李四",
        "solution_communication": "方案沟通中",
        "poc_status": "正在对接",
        "key_person_approved": "是",
        "bid_probability": "A",
        "contract_negotiation": "未启动",
        "project_type": "SaaS",
        "contract_signed": "否",
        "handoff_completed": "否",

        "company": "客户A",
        "demand": "测试需求描述",
        "product": "产品B",
        "level": "A",
        "bcard": "A",
        "approve": "是",
        "signed": "否",
        "notes": "测试需求描述"
    }
}

print("\n正在创建商机...")
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

response = requests.post(f"{API_BASE}/api/opportunities", json=opportunity_data, headers=headers)
print(f"响应状态码: {response.status_code}")
print(f"响应内容: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")

if response.status_code == 201:
    print("\n✅ 商机创建成功！")
else:
    print(f"\n❌ 商机创建失败: {response.text}")
