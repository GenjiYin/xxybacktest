"""
模拟交易结果数据迁移脚本

将旧格式（xxydb 共享表）迁移为新格式（每账户独立 Parquet 文件）

使用方式:
    cd xxybacktest
    python scripts/migrate_sim_results.py

迁移前（旧格式）:
    data/simulation_results/
      simulation_daily_values/data.parquet   <- 所有账户混在一起
      simulation_positions/data.parquet
      simulation_orders/data.parquet

迁移后（新格式）:
    data/simulation_results/
      accounts/
        sim_001/
          daily_values.parquet               <- 只属于 sim_001
          positions.parquet
          orders.parquet
        sim_002/
          ...

注意事项:
    1. 迁移前建议备份 data/simulation_results 目录
    2. 迁移过程中会保留旧数据，新数据写入 accounts/ 子目录
    3. 可以重复运行，会覆盖已存在的目标文件
"""
import os
import sys
import shutil
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from xxydb import xxydb


def migrate_data(data_path: str = "./data"):
    """
    执行数据迁移

    参数:
        data_path: 数据根目录，默认为 ./data
    """
    sim_path = os.path.join(data_path, "simulation_results")

    if not os.path.exists(sim_path):
        print(f"[错误] 目录不存在: {sim_path}")
        return False

    # 检查旧数据表是否存在
    old_db_path = os.path.join(sim_path, "simulation_daily_values")
    if not os.path.exists(old_db_path):
        print(f"[信息] 未检测到旧格式数据（simulation_daily_values 目录不存在）")
        print(f"[信息] 可能已经是新格式，或没有历史数据需要迁移")
        return True

    print("=" * 60)
    print("模拟交易结果数据迁移")
    print("=" * 60)
    print(f"数据源: {sim_path}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 创建备份
    backup_path = f"{sim_path}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"\n[1/4] 创建备份...")
    try:
        shutil.copytree(sim_path, backup_path)
        print(f"      备份已保存到: {backup_path}")
    except Exception as e:
        print(f"      [警告] 备份失败: {e}")
        response = input("      是否继续? (y/n): ")
        if response.lower() != 'y':
            return False

    # 连接旧数据库
    print(f"\n[2/4] 连接旧数据库...")
    db = xxydb(path=sim_path)

    # 迁移配置
    migrations = [
        ("simulation_daily_values", "daily_values.parquet", ['account_id', 'date', 'nav', 'daily_return']),
        ("simulation_positions", "positions.parquet", ['account_id', 'date', 'instrument', 'name', 'volume', 'ratio', 'cum_profit', 'cum_return', 'close_price', 'avg_cost']),
        ("simulation_orders", "orders.parquet", ['account_id', 'date', 'instrument', 'name', 'volume', 'side', 'status', 'cost']),
    ]

    total_accounts = set()
    total_records = 0

    for table_name, filename, expected_cols in migrations:
        print(f"\n[3/4] 迁移表: {table_name} -> {filename}")

        try:
            # 读取旧表数据
            df = db.query(f"SELECT * FROM {table_name}").df()
            print(f"      读取到 {len(df)} 条记录")

            if df.empty:
                print(f"      [跳过] 表为空")
                continue

            # 检查必要的列
            if 'account_id' not in df.columns:
                print(f"      [错误] 表中缺少 account_id 列")
                continue

            # 按 account_id 分组并写入独立文件
            account_count = 0
            for account_id, group in df.groupby('account_id'):
                # 创建账户目录
                account_dir = os.path.join(sim_path, "accounts", str(account_id))
                os.makedirs(account_dir, exist_ok=True)

                # 确保列顺序一致
                cols_to_keep = [c for c in expected_cols if c in group.columns]
                group = group[cols_to_keep]

                # 写入 Parquet
                output_path = os.path.join(account_dir, filename)
                group.to_parquet(output_path, index=False)

                total_accounts.add(account_id)
                account_count += 1

            total_records += len(df)
            print(f"      已迁移到 {account_count} 个账户目录")

        except Exception as e:
            print(f"      [错误] 迁移失败: {e}")
            import traceback
            traceback.print_exc()

    db.close()

    # 输出统计
    print(f"\n[4/4] 迁移完成!")
    print("=" * 60)
    print(f"账户数量: {len(total_accounts)}")
    print(f"总记录数: {total_records}")
    print(f"新数据位置: {os.path.join(sim_path, 'accounts')}")
    print("=" * 60)

    # 列出迁移的账户
    if total_accounts:
        print(f"\n已迁移账户列表:")
        for acc_id in sorted(total_accounts):
            account_dir = os.path.join(sim_path, "accounts", str(acc_id))
            files = os.listdir(account_dir) if os.path.exists(account_dir) else []
            print(f"  - {acc_id}: {', '.join(files)}")

    print(f"\n[提示] 旧数据仍保留在: {sim_path}")
    print(f"[提示] 如需清理旧数据，请手动删除以下目录:")
    for table_name, _, _ in migrations:
        old_dir = os.path.join(sim_path, table_name)
        if os.path.exists(old_dir):
            print(f"       {old_dir}")

    return True


def verify_migration(data_path: str = "./data"):
    """
    验证迁移结果
    对比旧表和新文件的数据一致性
    """
    print("\n" + "=" * 60)
    print("验证迁移结果")
    print("=" * 60)

    sim_path = os.path.join(data_path, "simulation_results")
    accounts_dir = os.path.join(sim_path, "accounts")

    if not os.path.exists(accounts_dir):
        print("[错误] 未找到新格式数据")
        return False

    # 检查每个账户的文件
    accounts = [d for d in os.listdir(accounts_dir) if os.path.isdir(os.path.join(accounts_dir, d))]

    print(f"发现 {len(accounts)} 个账户目录")

    all_ok = True
    for account_id in sorted(accounts):
        account_dir = os.path.join(accounts_dir, account_id)
        files = os.listdir(account_dir)

        print(f"\n  {account_id}:")
        for fname in ['daily_values.parquet', 'positions.parquet', 'orders.parquet']:
            fpath = os.path.join(account_dir, fname)
            if os.path.exists(fpath):
                df = pd.read_parquet(fpath)
                print(f"    ✓ {fname}: {len(df)} 条记录")
            else:
                print(f"    - {fname}: 不存在")

    return all_ok


if __name__ == "__main__":
    import pandas as pd  # 延迟导入，避免在模块导入时就加载

    # 解析命令行参数
    data_path = "./data"
    verify_only = False

    if len(sys.argv) > 1:
        if sys.argv[1] in ['--help', '-h']:
            print(__doc__)
            sys.exit(0)
        elif sys.argv[1] == '--verify':
            verify_only = True
        else:
            data_path = sys.argv[1]

    if verify_only:
        verify_migration(data_path)
    else:
        success = migrate_data(data_path)
        if success:
            # 迁移后自动验证
            verify_migration(data_path)
            print("\n[完成] 数据迁移成功！")
        else:
            print("\n[失败] 数据迁移失败！")
            sys.exit(1)
