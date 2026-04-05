"""测试history方法修复"""
import sys
sys.path.insert(0, '.')

from datetime import date
from xxybacktest.simulation.batch_engine import SimulationContext

# 模拟账户数据
account = {
    "account_id": "test_001",
    "name": "测试账户",
    "cash": 100000.0,
    "initial_cash": 100000.0,
}

# 创建context
sim_date = date(2026, 4, 5)  # 周六
context = SimulationContext(account, sim_date)

print("=" * 50)
print("测试 history() 方法")
print(f"当前日期: {sim_date}")
print("=" * 50)

# 测试1: 查询一只股票
print("\n1. 查询 000001.SZ 的20天历史数据:")
result = context.history(["000001.SZ"], bar_count=20)
print(f"   返回数据条数: {len(result)}")
print(f"   列结构: {list(result.columns)}")
if len(result) > 0:
    print(f"   数据预览:")
    print(result.head())
else:
    print("   警告: 没有返回数据！")

# 测试2: 查询多只股票
print("\n2. 查询多只股票 (000001.SZ, 000002.SZ) 的5天数据:")
result = context.history(["000001.SZ", "000002.SZ"], bar_count=5)
print(f"   返回数据条数: {len(result)}")
if len(result) > 0:
    print(f"   列层级: {result.columns.names}")
    print(result)

# 测试3: 验证数据可以正确访问（像策略中那样使用）
print("\n3. 验证数据访问（模拟策略使用方式）:")
result = context.history(["000001.SZ"], bar_count=20, fields=["close"])
if len(result) > 0:
    try:
        # 尝试像策略代码那样访问数据
        close_prices = result["000001.SZ"]["close"]
        ma5 = close_prices.tail(5).mean()
        ma20 = close_prices.mean()
        print(f"   最近5天收盘价: {close_prices.tail(5).tolist()}")
        print(f"   MA5: {ma5:.2f}")
        print(f"   MA20: {ma20:.2f}")
        print("   ✓ 数据访问成功！")
    except Exception as e:
        print(f"   ✗ 数据访问失败: {e}")
else:
    print("   警告: 无法测试数据访问，因为返回为空")

print("\n" + "=" * 50)
print("测试完成!")
print("=" * 50)
