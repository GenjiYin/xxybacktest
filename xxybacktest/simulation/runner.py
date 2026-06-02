"""
模拟交易每日重跑引擎 - 阶段三

功能：
    - run_all(end_date): 对所有运行中账户执行回测并存库
    - run_single(account_id, end_date): 对单个账户执行回测并存库
"""

import os
import re
import types
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, Optional

import pandas as pd

from ..backtest import run_backtest


def _resolve_account_path(account_id: str, filename: str, data_path: str = "./data") -> str | None:
    """
    查找账户数据文件路径。
    同时查 simulation_results/accounts/ 和 live/accounts/，
    返回修改时间最新的文件（避免回测旧数据覆盖实盘新数据）。
    都找不到返回 None。
    """
    paths = []
    for subdir in ("simulation_results", "live"):
        path = os.path.join(data_path, subdir, "accounts", account_id, filename)
        if os.path.exists(path):
            paths.append((path, os.path.getmtime(path)))
    if not paths:
        return None
    return max(paths, key=lambda x: x[1])[0]


def _load_func(code: str, func_name: str = "user_func") -> Callable:
    """
    从源码字符串加载函数

    参数:
        code: 函数源码
        func_name: 函数名（用于错误提示）

    返回:
        Callable: 加载的函数
    """
    if not code or not code.strip():
        return None

    # 清理源码中的行号前缀（如果有）
    lines = code.split('\n')
    cleaned_lines = []
    for line in lines:
        # 移除类似 "1 |    def func():" 的行号前缀
        match = re.match(r'\s*\d+\s*[│|]\s*(.*)', line)
        if match:
            cleaned_lines.append(match.group(1))
        else:
            cleaned_lines.append(line)

    code = '\n'.join(cleaned_lines)

    # 创建模块并执行代码
    module = types.ModuleType("dynamic_module")
    module.__dict__['__builtins__'] = __builtins__

    try:
        exec(code, module.__dict__)
    except Exception as e:
        raise ValueError(f"函数源码执行失败: {e}\n源码:\n{code[:200]}...")

    # 找到函数对象
    for name, obj in module.__dict__.items():
        if callable(obj) and not name.startswith('_'):
            return obj

    raise ValueError(f"在源码中未找到函数定义")


def _save_results(account_id: str, context, data_path: str):
    """
    将回测结果存入独立 Parquet 文件（每账户独立存储，无竞争）

    参数:
        account_id: 账户ID
        context: 回测上下文
        data_path: 数据路径
    """
    # 每个账户写自己的独立目录
    account_dir = os.path.join(data_path, "simulation_results", "accounts", account_id)
    os.makedirs(account_dir, exist_ok=True)

    # 1. 保存每日净值
    returns_data = getattr(context.performance, 'returns', None)
    nav_records = []
    if returns_data is not None and len(returns_data) > 0:
        nav = 1.0

        # 判断 returns 是列表还是 Series/DataFrame
        if isinstance(returns_data, pd.Series):
            # 已经是 Series（经过 Performance.analyse 处理后）
            for date, daily_return in returns_data.items():
                nav *= (1 + daily_return)  # daily_return 已经是涨跌幅（如 0.02）
                nav_records.append({
                    'account_id': account_id,
                    'date': date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date),
                    'nav': nav,
                    'daily_return': daily_return,
                })
        else:
            # 原始列表格式 [[date_str, return_ratio], ...]
            for date_str, daily_return in returns_data:
                nav *= daily_return
                nav_records.append({
                    'account_id': account_id,
                    'date': date_str,
                    'nav': nav,
                    'daily_return': daily_return - 1 if daily_return != 0 else 0,
                })

    if nav_records:
        df_nav = pd.DataFrame(nav_records)
        df_nav.to_parquet(os.path.join(account_dir, "daily_values.parquet"), index=False)

    # 2. 保存持仓快照
    if hasattr(context.performance, 'position_snapshots') and context.performance.position_snapshots:
        snapshots = context.performance.position_snapshots
        df_pos = pd.DataFrame(snapshots)
        df_pos['account_id'] = account_id

        # 重命名列以匹配表结构
        df_pos = df_pos.rename(columns={
            'close': 'close_price',
        })

        # 确保所有列都存在
        for col in ['account_id', 'date', 'instrument', 'name', 'volume', 'ratio',
                    'cum_profit', 'cum_return', 'close_price', 'avg_cost']:
            if col not in df_pos.columns:
                df_pos[col] = '' if col in ['date', 'instrument', 'name'] else 0.0

        # 选择需要的列
        df_pos = df_pos[['account_id', 'date', 'instrument', 'name', 'volume', 'ratio',
                         'cum_profit', 'cum_return', 'close_price', 'avg_cost']]

        df_pos.to_parquet(os.path.join(account_dir, "positions.parquet"), index=False)

    # 3. 保存订单
    if hasattr(context, 'order') and context.order is not None and not context.order.empty:
        df_orders = context.order.copy()
        df_orders['account_id'] = account_id

        # 确保列存在
        for col in ['account_id', 'date', 'instrument', 'name', 'volume', 'side', 'status', 'price', 'cost']:
            if col not in df_orders.columns:
                df_orders[col] = '' if col in ['date', 'instrument', 'name', 'side', 'status'] else 0.0

        df_orders = df_orders[['account_id', 'date', 'instrument', 'name', 'volume', 'side', 'status', 'price', 'cost']]

        df_orders.to_parquet(os.path.join(account_dir, "orders.parquet"), index=False)

    returns_count = len(getattr(context.performance, 'returns', []))
    pos_count = len(getattr(context.performance, 'position_snapshots', []))
    order_count = len(context.order) if hasattr(context, 'order') and context.order is not None else 0
    print(f"  [存储完成] 净值记录: {returns_count}, 持仓快照: {pos_count}, 订单: {order_count}")


def run_single(account_id: str, end_date: Optional[str] = None, data_path: str = "./data") -> dict:
    """
    对单个账户执行回测并存库

    参数:
        account_id: 账户ID
        end_date: 结束日期，默认为今天
        data_path: 数据源路径（默认'./data'）

    返回:
        dict: 回测结果信息
    """
    from .submitter import get_account

    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    # 加载账户配置
    account = get_account(account_id, data_path)
    if not account:
        raise ValueError(f"账户不存在: {account_id}")

    if account['status'] != 'running':
        print(f"[跳过] 账户 {account_id} 状态为 {account['status']}，不参与回测")
        return {'account_id': account_id, 'status': 'skipped', 'reason': 'not_running'}

    if account.get('account_type') == 'live':
        print(f"[跳过] 账户 {account_id} 为实盘账户，不参与模拟回测")
        return {'account_id': account_id, 'status': 'skipped', 'reason': 'live_account'}

    # 使用账户自己的 data_path
    account_data_path = account.get('data_path', data_path)

    print(f"\n[回测开始] {account_id} ({account['name']})")
    print(f"  区间: {account['start_date']} ~ {end_date}")
    print(f"  初始资金: {account['initial_cash']}")
    print(f"  数据源: {account_data_path}")

    # 从源码重建函数
    try:
        initialize = _load_func(account['initialize_code'], 'initialize')
        handle_data = _load_func(account['handle_data_code'], 'handle_data') if account['handle_data_code'] else None
    except ValueError as e:
        print(f"[错误] 函数加载失败: {e}")
        return {'account_id': account_id, 'status': 'error', 'reason': str(e)}

    # 执行回测
    try:
        context = run_backtest(
            initialize=initialize,
            handle_data=handle_data,
            start_date=account['start_date'],
            end_date=end_date,
            capital=account['initial_cash'],
            data_path=account_data_path,
            asset_type=account.get('asset_type', 'stock'),
            benchmark=account.get('benchmark', '000001.SH'),
            plot=False,  # 静默模式
        )
    except Exception as e:
        print(f"[错误] 回测执行失败: {e}")
        import traceback
        traceback.print_exc()
        return {'account_id': account_id, 'status': 'error', 'reason': str(e)}

    # 保存结果
    _save_results(account_id, context, data_path)

    # 计算最终指标
    returns_data = getattr(context.performance, 'returns', None)
    if returns_data is not None and len(returns_data) > 0:
        if isinstance(returns_data, pd.Series):
            final_nav = (1 + returns_data).cumprod().iloc[-1]
        else:
            final_nav = returns_data[-1][1]
    else:
        final_nav = 1.0

    final_value = context.portfolio.total_value if hasattr(context, 'portfolio') else account['initial_cash']

    print(f"[回测完成] {account_id}")
    print(f"  最终净值: {final_nav:.4f}")
    print(f"  最终市值: {final_value:.2f}")

    returns_count = len(returns_data) if returns_data is not None else 0
    positions_count = len(getattr(context.performance, 'position_snapshots', []))
    orders_count = len(context.order) if hasattr(context, 'order') and context.order is not None else 0

    return {
        'account_id': account_id,
        'status': 'success',
        'final_nav': final_nav,
        'final_value': final_value,
        'returns_count': returns_count,
        'positions_count': positions_count,
        'orders_count': orders_count,
    }


def run_all(end_date: Optional[str] = None, data_path: str = "./data") -> list:
    """
    对所有运行中账户执行回测并存库（并行执行）

    参数:
        end_date: 结束日期，默认为今天
        data_path: 数据源路径（默认'./data'）

    返回:
        list: 每个账户的回测结果信息列表
    """
    from .submitter import list_accounts

    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"[每日模拟交易重跑] 目标日期: {end_date}")
    print(f"{'='*60}")

    # 获取所有运行中的账户
    accounts = list_accounts(status='running', data_path=data_path)

    if not accounts:
        print("[提示] 没有运行中的账户")
        return []

    print(f"[信息] 共 {len(accounts)} 个运行中账户，开始并行执行")

    # max_workers 默认用 CPU 核心数，也可以写死为 4
    max_workers = min(len(accounts), os.cpu_count() or 4)

    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        future_to_id = {
            pool.submit(run_single, acc['account_id'], end_date, data_path): acc['account_id']
            for acc in accounts
        }
        for future in as_completed(future_to_id):
            account_id = future_to_id[future]
            try:
                result = future.result()
            except Exception as e:
                print(f"[错误] {account_id} 执行异常: {e}")
                result = {'account_id': account_id, 'status': 'error', 'reason': str(e)}
            results.append(result)

    # 统计
    success_count = sum(1 for r in results if r['status'] == 'success')
    error_count = sum(1 for r in results if r['status'] == 'error')
    skip_count = sum(1 for r in results if r['status'] == 'skipped')

    print(f"\n{'='*60}")
    print(f"[每日重跑完成] 成功: {success_count}, 失败: {error_count}, 跳过: {skip_count}")
    print(f"{'='*60}")

    # 若全部失败（有错误且无一成功），抛异常让调度器感知
    if error_count > 0 and success_count == 0:
        raise RuntimeError(f"所有 {error_count} 个账户执行失败")

    return results


def get_account_nav(account_id: str, data_path: str = "./data") -> pd.DataFrame:
    """
    获取账户的净值曲线（自动兼容模拟账户和实盘账户）

    参数:
        account_id: 账户ID
        data_path: 数据源路径（默认'./data'）

    返回:
        DataFrame: 包含 date, nav, daily_return 列
    """
    path = _resolve_account_path(account_id, "daily_values.parquet", data_path)
    if path is None:
        return pd.DataFrame(columns=['date', 'nav', 'daily_return'])
    df = pd.read_parquet(path)
    return df[['date', 'nav', 'daily_return']].sort_values('date').reset_index(drop=True)


def get_account_positions(account_id: str, date: Optional[str] = None, data_path: str = "./data") -> pd.DataFrame:
    """
    获取账户的持仓（自动兼容模拟账户和实盘账户）

    参数:
        account_id: 账户ID
        date: 日期，默认为最新日期
        data_path: 数据源路径（默认'./data'）

    返回:
        DataFrame: 持仓信息
    """
    path = _resolve_account_path(account_id, "positions.parquet", data_path)
    cols = ['date', 'instrument', 'name', 'volume', 'ratio', 'cum_profit', 'cum_return', 'close_price', 'avg_cost']
    if path is None:
        return pd.DataFrame(columns=cols)
    df = pd.read_parquet(path)
    if date:
        df = df[df['date'] == date]
    else:
        # 取最新日期的持仓
        if not df.empty:
            latest_date = df['date'].max()
            df = df[df['date'] == latest_date]
    return df.sort_values('ratio', ascending=False).reset_index(drop=True)


def get_account_orders(account_id: str, limit: int = 100, data_path: str = "./data") -> pd.DataFrame:
    """
    获取账户的订单记录（自动兼容模拟账户和实盘账户）

    参数:
        account_id: 账户ID
        limit: 返回记录数限制
        data_path: 数据源路径（默认'./data'）

    返回:
        DataFrame: 订单信息
    """
    path = _resolve_account_path(account_id, "orders.parquet", data_path)
    cols = ['date', 'instrument', 'name', 'volume', 'side', 'status', 'price', 'cost']
    if path is None:
        return pd.DataFrame(columns=cols)
    df = pd.read_parquet(path)
    if 'price' not in df.columns:
        df['price'] = 0.0
    return df.sort_values('date', ascending=False).head(limit).reset_index(drop=True)
