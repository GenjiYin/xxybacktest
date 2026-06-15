"""账户详情页面路由 - 连接真实数据"""
import os
import pandas as pd
from flask import Blueprint, render_template, abort
from xxydb import xxydb as _xxydb

from xxybacktest.simulation.submitter import get_account
from xxybacktest.simulation.runner import get_account_nav, get_account_positions, get_account_orders

account_bp = Blueprint('account', __name__)


def _fill_missing_names(df, data_path, asset_type):
    """对 name 字段为空的行，从数据库实时补充名称。

    stock: 查 daily_bar 近15天
    fund:  依次查 fund_dividend、fund_split（小表，不分区）
    """
    if df.empty:
        return df
    missing_mask = df['name'].isna() | (df['name'] == '')
    if not missing_mask.any():
        return df

    missing_codes = df.loc[missing_mask, 'instrument'].unique().tolist()
    codes_str = "', '".join(missing_codes)

    try:
        from xxydb import xxydb as _xxydb
        db = _xxydb(path=data_path)
        names_map = {}

        # ── 先查股票表（daily_bar）──
        try:
            rows = db.query(f"""
                SELECT instrument, name FROM daily_bar
                WHERE instrument IN ('{codes_str}')
                  AND name IS NOT NULL AND name != ''
                QUALIFY ROW_NUMBER() OVER (PARTITION BY instrument ORDER BY date DESC) = 1
            """).df()
            for _, r in rows.iterrows():
                if r['name'] and r['instrument'] not in names_map:
                    names_map[r['instrument']] = r['name']
        except Exception:
            pass

        # ── 再查基金表（daily_fund）──
        try:
            rows = db.query(f"""
                SELECT instrument, name FROM daily_fund
                WHERE instrument IN ('{codes_str}')
                  AND name IS NOT NULL AND name != ''
                QUALIFY ROW_NUMBER() OVER (PARTITION BY instrument ORDER BY date DESC) = 1
            """).df()
            for _, r in rows.iterrows():
                if r['name'] and r['instrument'] not in names_map:
                    names_map[r['instrument']] = r['name']
        except Exception:
            pass

        # ── 基金分红/拆分小表兜底 ──
        if asset_type == 'fund':
            for tbl in ('fund_dividend', 'fund_split'):
                try:
                    rows = db.query(
                        f"SELECT DISTINCT instrument, name FROM {tbl} "
                        f"WHERE instrument IN ('{codes_str}') "
                        f"AND name IS NOT NULL AND name != ''"
                    ).df()
                    for _, r in rows.iterrows():
                        if r['name'] and r['instrument'] not in names_map:
                            names_map[r['instrument']] = r['name']
                except Exception:
                    pass

        db.close()

        if names_map:
            df = df.copy()
            df.loc[missing_mask, 'name'] = df.loc[missing_mask, 'instrument'].map(
                lambda code: names_map.get(code, '')
            )
    except Exception:
        pass
    return df

# 默认数据路径
DEFAULT_DATA_PATH = os.environ.get('XXY_DATA_PATH', './data')


@account_bp.route('/account/<account_id>')
def account_detail(account_id):
    """账户详情页 - 从 xxydb 读取真实数据"""

    acc = get_account(account_id, data_path=DEFAULT_DATA_PATH)
    if not acc:
        abort(404, description="账户不存在")

    created_at = acc.get('created_at', '')
    if hasattr(created_at, 'strftime'):
        created_at = created_at.strftime('%Y-%m-%d')
    elif isinstance(created_at, str):
        created_at = created_at[:10]

    account = {
        'account_id': account_id,
        'name': acc['name'],
        'status': acc['status'],
        'created_at': created_at,
        'initial_cash': acc.get('initial_cash', 100000),
        'asset_type': acc.get('asset_type', 'stock'),
        'benchmark': acc.get('benchmark', '000001.SH'),
        'initialize_code': acc.get('initialize_code') or '',
        'handle_data_code': acc.get('handle_data_code') or '',
        'trigger_cron': acc.get('trigger_cron') or '',
        'execution_mode': acc.get('execution_mode') or 'daily',
        'rebalance_interval': acc.get('rebalance_interval') or 1,
    }

    nav_df = get_account_nav(account_id, data_path=DEFAULT_DATA_PATH)

    if nav_df.empty:
        indicators = {
            'total_return': 0,
            'annual_return': 0,
            'max_drawdown': 0,
            'sharpe_ratio': 0,
            'current_nav': 1.0,
            'latest_daily_return': 0,
            'latest_return_date': ''
        }
        nav_dates = []
        nav_values = []
        benchmark_values = []
        all_benchmark_values = {}
    else:
        first_nav = nav_df['nav'].iloc[0]
        last_nav = nav_df['nav'].iloc[-1]
        total_return = (last_nav - first_nav) / first_nav if first_nav > 0 else 0

        days = len(nav_df)
        annual_return = (1 + total_return) ** (252 / days) - 1 if days > 1 else 0

        nav_series = nav_df['nav']
        rolling_max = nav_series.cummax()
        drawdowns = (nav_series - rolling_max) / rolling_max
        max_drawdown = abs(drawdowns.min()) if len(drawdowns) > 0 else 0

        daily_returns = nav_df['daily_return'].dropna()
        if len(daily_returns) > 1:
            excess_returns = daily_returns - 0.02 / 252
            sharpe_ratio = (excess_returns.mean() / excess_returns.std()) * (252 ** 0.5) if excess_returns.std() != 0 else 0
        else:
            sharpe_ratio = 0

        # 当日收益：取最新有效日收益率（排除0值，取最后一个非零值）
        nav_df_copy = nav_df.dropna(subset=['daily_return'])
        if len(nav_df_copy) > 0:
            # 从后往前找第一个非零值
            non_zero_df = nav_df_copy[nav_df_copy['daily_return'] != 0]
            if len(non_zero_df) > 0:
                latest_daily_return = non_zero_df['daily_return'].iloc[-1]
                latest_return_date = str(non_zero_df['date'].iloc[-1])[:10]
            else:
                latest_daily_return = nav_df_copy['daily_return'].iloc[-1]
                latest_return_date = str(nav_df_copy['date'].iloc[-1])[:10]
        else:
            latest_daily_return = 0
            latest_return_date = ""

        indicators = {
            'latest_daily_return': latest_daily_return,
            'latest_return_date': latest_return_date,
            'total_return': total_return,
            'annual_return': annual_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'current_nav': last_nav
        }

        nav_df['date'] = nav_df['date'].astype(str).str[:10]
        nav_dates = nav_df['date'].tolist()
        nav_values = nav_df['nav'].tolist()

        # 一次性查三个指数，前端切换时直接读 JS 变量，无需再发请求
        BENCHMARKS = {
            '000300.SH': '沪深300',
            '000905.SH': '中证500',
            '000852.SH': '中证1000',
        }
        start_date = nav_df['date'].iloc[0]
        end_date = nav_df['date'].iloc[-1]
        codes_str = "', '".join(BENCHMARKS.keys())
        all_benchmark_values = {}
        try:
            db = _xxydb(path=DEFAULT_DATA_PATH)
            raw_df = db.query(f"""
                SELECT instrument, date AS trade_date, change_ratio * 100 AS pct_chg
                FROM index_bar
                WHERE instrument IN ('{codes_str}')
                  AND date >= '{start_date}'
                  AND date <= '{end_date}'
                ORDER BY instrument, date
            """).df()
            raw_df['trade_date'] = raw_df['trade_date'].astype(str).str[:10]
            for code in BENCHMARKS:
                sub = raw_df[raw_df['instrument'] == code]
                bench_map = dict(zip(sub['trade_date'], sub['pct_chg'] / 100))
                bench = 1.0
                nav_list = []
                for d in nav_dates:
                    bench *= (1 + bench_map.get(d, 0.0))
                    nav_list.append(round(bench, 4))
                all_benchmark_values[code] = nav_list
        except Exception:
            pass

        # 默认展示沪深300，若查询失败则为空列表
        benchmark_values = all_benchmark_values.get('000300.SH', [])

    # 先加载成交记录，从中建 instrument→name 字典（成交时名称一定有值）
    orders_df = get_account_orders(account_id, limit=10000, data_path=DEFAULT_DATA_PATH)
    orders_name_map = {}
    if not orders_df.empty:
        for _, r in orders_df.iterrows():
            if r['name'] and r['instrument'] not in orders_name_map:
                orders_name_map[r['instrument']] = r['name']

    # 加载持仓，用成交记录的名称字典补全缺失名称
    positions_df = get_account_positions(account_id, data_path=DEFAULT_DATA_PATH)
    if not positions_df.empty:
        positions_df['date'] = positions_df['date'].astype(str).str[:10]
        positions_df['name'] = positions_df.apply(
            lambda row: orders_name_map.get(row['instrument'], row['name'])
            if (not row['name'] or row['name'] != row['name'])  # 空或 NaN
            else row['name'],
            axis=1
        )
        # 兜底：成交记录中也没有的名称，从数据库实时查询
        positions_df = _fill_missing_names(
            positions_df, DEFAULT_DATA_PATH, account.get('asset_type', 'stock')
        )
    positions = []
    for _, row in positions_df.iterrows():
        positions.append({
            'code': row['instrument'],
            'name': row['name'],
            'amount': int(row['volume']),
            'cost_basis': round(row['avg_cost'], 2),
            'market_value': round(row['close_price'] * row['volume'], 2),
            'ratio': round(row['ratio'] * 100, 2),
            'cum_return': round(row['cum_return'] * 100, 2)
        })

    # 兜底：补全订单中的缺失名称（实盘订单写入时可能缺少ETF名称）
    if not orders_df.empty:
        orders_df = _fill_missing_names(
            orders_df, DEFAULT_DATA_PATH, account.get('asset_type', 'stock')
        )
        orders_df['date'] = orders_df['date'].astype(str).str[:10]
    all_orders = []
    for _, row in orders_df.iterrows():
        all_orders.append({
            'trade_date': row['date'],
            'code': row['instrument'],
            'name': row['name'],
            'direction': 'buy' if str(row['side']).upper() in ['BUY', '买入', '买'] else 'sell',
            'amount': int(abs(row['volume'])),
            'price': round(float(row['price']), 4) if 'price' in orders_df.columns and row['price'] else 0
        })

    # 计划交易：只显示当天的交易（如果有的话）
    from datetime import datetime
    planned_trades = []
    today = datetime.now().strftime('%Y-%m-%d')
    planned_trades_date = today
    if all_orders:
        planned_trades = [
            order for order in all_orders
            if order['trade_date'] == today
        ]

    return render_template(
        'account.html',
        account=account,
        indicators=indicators,
        nav_dates=nav_dates,
        nav_values=nav_values,
        benchmark_values=benchmark_values,
        all_benchmark_values=all_benchmark_values,
        positions=positions,
        orders=all_orders,
        total_orders=len(all_orders),
        planned_trades=planned_trades,
        planned_trades_date=planned_trades_date
    )
