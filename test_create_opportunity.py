"""
测试新建商机功能
"""
import urllib.request
import urllib.error
import json

API_BASE = "http://127.0.0.1:8000"

# 首先登录获取 token
login_data = {
    "username": "admin",
    "password": "admin123"
}

print("1. 登录获取 token...")
try:
    login_url = f"{API_BASE}/api/auth/login"
    data = json.dumps(login_data).encode('utf-8')
    req = urllib.request.Request(login_url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as response:
        token_data = json.loads(response.read().decode('utf-8'))
        token = token_data["access_token"]
        print(f"   登录成功，获取到 token: {token[:20]}...")
except urllib.error.HTTPError as e:
    print(f"   登录失败: {e.code} - {e.read().decode('utf-8')}")
    exit(1)
except Exception as e:
    print(f"   登录异常: {e}")
    exit(1)

# 测试新建商机
print("\n2. 测试新建商机...")

# 构建包含评分维度的 payload
opportunity_data = {
    "name": "测试商机 - 测试客户 - 测试产品",
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
    "customer_name": "测试客户",
    "customer_type": "新客户",
    "requirement_desc": "测试需求描述",
    "product_name": "测试产品",
    "estimated_cycle": "3个月",
    "opportunity_level": "A",
    "project_date": "2026-04-23",
    "project_members": "张三、李四",
    "solution_communication": "方案沟通中",
    "poc_status": "POC测试中",
    "key_person_approved": "是",
    "bid_probability": "A",
    "contract_negotiation": "未启动",
    "project_type": "SaaS",
    "contract_signed": "否",
    "handoff_completed": "否",

    "custom_fields": {
        "owner_name_display": "admin",
        "customer_name": "测试客户",
        "customer_type": "新客户",
        "requirement_desc": "测试需求描述",
        "product_name": "测试产品",
        "estimated_cycle": "3个月",
        "opportunity_level": "A",
        "project_date": "2026-04-23",
        "project_members": "张三、李四",
        "solution_communication": "方案沟通中",
        "poc_status": "POC测试中",
        "key_person_approved": "是",
        "bid_probability": "A",
        "contract_negotiation": "未启动",
        "project_type": "SaaS",
        "contract_signed": "否",
        "handoff_completed": "否",

        "company": "测试客户",
        "demand": "测试需求描述",
        "product": "测试产品",
        "level": "A",
        "bcard": "A",
        "approve": "是",
        "signed": "否",
        "notes": "测试需求描述"
    }
}

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

try:
    create_url = f"{API_BASE}/api/opportunities"
    data = json.dumps(opportunity_data).encode('utf-8')
    req = urllib.request.Request(create_url, data=data, headers=headers)
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode('utf-8'))
        print(f"   新建商机成功！")
        print(f"   商机ID: {result['id']}")
        print(f"   商机名称: {result['name']}")
        print(f"   客户名称: {result['customer_name']}")
        print(f"   产品名称: {result['product_name']}")
        print(f"   商机等级: {result['opportunity_level']}")
except urllib.error.HTTPError as e:
    print(f"   新建商机失败: {e.code}")
    print(f"   错误信息: {e.read().decode('utf-8')}")
except Exception as e:
    print(f"   新建商机异常: {e}")

print("\n3. 测试完成")
