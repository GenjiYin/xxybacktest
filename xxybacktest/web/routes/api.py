"""API 路由（AJAX 调用）- 连接真实数据"""
import os
from flask import Blueprint, jsonify, request
import pandas as pd

from xxybacktest.simulation.submitter import list_accounts, pause, resume, delete, update_account
from xxybacktest.simulation.runner import get_account_nav, get_account_positions, get_account_orders

api_bp = Blueprint('api', __name__)

# 默认数据路径
DEFAULT_DATA_PATH = os.environ.get('XXY_DATA_PATH', './data')


@api_bp.route('/accounts')
def get_accounts():
    """获取所有账户列表（JSON）"""
    accounts_raw = list_accounts(data_path=DEFAULT_DATA_PATH)

    accounts = []
    for acc in accounts_raw:
        account_id = acc['account_id']

        # 获取该账户的最新净值
        nav_df = get_account_nav(account_id, data_path=DEFAULT_DATA_PATH)

        if not nav_df.empty:
            first_nav = nav_df['nav'].iloc[0]
            last_nav = nav_df['nav'].iloc[-1]
            total_return = (last_nav - first_nav) / first_nav if first_nav > 0 else 0
            current_nav = last_nav
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
        else:
            total_return = 0
            current_nav = 1.0
            latest_daily_return = 0

        accounts.append({
            'account_id': account_id,
            'name': acc['name'],
            'status': acc['status'],
            'total_return': round(total_return, 4),
            'latest_daily_return': round(latest_daily_return, 4),
            'latest_return_date': latest_return_date,
            'current_nav': round(current_nav, 4),
            'created_at': acc.get('created_at', '')
        })

    return jsonify(accounts)


@api_bp.route('/accounts/<account_id>/nav')
def get_nav(account_id):
    """获取账户净值曲线数据"""
    nav_df = get_account_nav(account_id, data_path=DEFAULT_DATA_PATH)

    if nav_df.empty:
        return jsonify([])

    nav_df['date'] = nav_df['date'].astype(str).str[:10]

    data = []
    for _, row in nav_df.iterrows():
        data.append({
            'date': row['date'],
            'nav': round(row['nav'], 4),
            'daily_return': round(row['daily_return'], 4) if pd.notna(row['daily_return']) else 0
        })

    return jsonify(data)


@api_bp.route('/accounts/<account_id>/positions')
def get_positions(account_id):
    """获取账户当前持仓"""
    positions_df = get_account_positions(account_id, data_path=DEFAULT_DATA_PATH)

    if not positions_df.empty:
        positions_df['date'] = positions_df['date'].astype(str).str[:10]

    positions = []
    for _, row in positions_df.iterrows():
        positions.append({
            'date': row['date'],
            'code': row['instrument'],
            'name': row['name'],
            'volume': int(row['volume']),
            'ratio': round(row['ratio'], 4),
            'cum_profit': round(row['cum_profit'], 2),
            'cum_return': round(row['cum_return'], 4),
            'close_price': round(row['close_price'], 2),
            'avg_cost': round(row['avg_cost'], 2)
        })

    return jsonify(positions)


@api_bp.route('/accounts/<account_id>/orders')
def get_orders(account_id):
    """获取账户订单记录"""
    orders_df = get_account_orders(account_id, limit=100, data_path=DEFAULT_DATA_PATH)

    if not orders_df.empty:
        orders_df['date'] = orders_df['date'].astype(str).str[:10]

    orders = []
    for _, row in orders_df.iterrows():
        orders.append({
            'date': row['date'],
            'code': row['instrument'],
            'name': row['name'],
            'volume': int(abs(row['volume'])),
            'side': '买入' if str(row['side']).upper() in ['BUY', '买入', '买'] else '卖出',
            'status': row['status'],
            'cost': round(row['cost'], 2)
        })

    return jsonify(orders)


@api_bp.route('/accounts/<account_id>/pause', methods=['POST'])
def pause_account(account_id):
    """暂停账户"""
    success = pause(account_id, data_path=DEFAULT_DATA_PATH)
    if success:
        return jsonify({'success': True, 'message': '账户已暂停'})
    else:
        return jsonify({'success': False, 'message': '账户不存在或暂停失败'}), 404


@api_bp.route('/accounts/<account_id>/resume', methods=['POST'])
def resume_account(account_id):
    """恢复账户"""
    success = resume(account_id, data_path=DEFAULT_DATA_PATH)
    if success:
        return jsonify({'success': True, 'message': '账户已恢复'})
    else:
        return jsonify({'success': False, 'message': '账户不存在或恢复失败'}), 404


@api_bp.route('/accounts/<account_id>', methods=['DELETE'])
def delete_account(account_id):
    """删除账户"""
    success = delete(account_id, data_path=DEFAULT_DATA_PATH)
    if success:
        return jsonify({'success': True, 'message': '账户已删除'})
    else:
        return jsonify({'success': False, 'message': '账户不存在或删除失败'}), 404


@api_bp.route('/accounts/<account_id>', methods=['PUT'])
def update_account_route(account_id):
    """
    更新账户配置和策略代码。

    请求体(JSON):
        {
            "name": "新名称",
            "initialize_code": "def initialize(ctx):\n    ctx.g['x'] = 1",
            "handle_data_code": "def handle_data(ctx):\n    pass",
            "trigger_cron": "30 10 * * *",
            "qmt_path": "D:\\\\国金证券QMT交易端\\\\userdata_mini",
            "live_account_id": "8881686799",
            "execution_mode": "daily",
            "rebalance_interval": 1
        }

    返回:
        {
            "success": true,
            "account_id": "live_xxx",
            "updated_fields": ["initialize_code", "trigger_cron"],
            "cron_changed": true,
            "scheduler_refreshed": true
        }
    """
    data = request.get_json() or {}

    result = update_account(
        account_id=account_id,
        data_path=DEFAULT_DATA_PATH,
        name=data.get('name'),
        initialize_code=data.get('initialize_code'),
        handle_data_code=data.get('handle_data_code'),
        trigger_cron=data.get('trigger_cron'),
        qmt_path=data.get('qmt_path'),
        live_account_id=data.get('live_account_id'),
        execution_mode=data.get('execution_mode'),
        rebalance_interval=data.get('rebalance_interval'),
    )

    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 404


@api_bp.route('/portfolio/nav', methods=['POST'])
def portfolio_nav():
    """计算策略组合净值曲线（加权合成）

    请求体: {"accounts": [{"account_id": "sim_001", "weight": 40}, ...]}
    返回:   combined NAV 序列 + 各账户对齐 NAV + 统计指标
    """
    data = request.get_json()
    if not data or 'accounts' not in data:
        return jsonify({'error': '请求格式错误'}), 400

    accounts_input = data['accounts']
    if len(accounts_input) < 2:
        return jsonify({'error': '至少需要选择 2 个策略'}), 400

    total_weight = sum(float(a.get('weight', 0)) for a in accounts_input)
    if total_weight <= 0:
        return jsonify({'error': '权重之和必须大于 0'}), 400

    # 加载各账户净值数据
    nav_data = {}
    for acc in accounts_input:
        account_id = acc['account_id']
        nav_df = get_account_nav(account_id, data_path=DEFAULT_DATA_PATH)
        if nav_df.empty:
            continue
        nav_df = nav_df.copy()
        nav_df['date'] = nav_df['date'].astype(str).str[:10]
        nav_data[account_id] = nav_df.set_index('date')

    valid_ids = list(nav_data.keys())
    if len(valid_ids) < 2:
        return jsonify({'error': '有效数据不足，至少需要 2 个有历史数据的策略'}), 400

    # 取日期交集
    date_sets = [set(nav_data[aid].index) for aid in valid_ids]
    common_dates = sorted(date_sets[0].intersection(*date_sets[1:]))

    if len(common_dates) < 5:
        return jsonify({'error': f'各策略公共交易日不足（仅 {len(common_dates)} 天），无法生成有效曲线'}), 400

    # 加权合成每日收益率
    combined_returns = pd.Series(0.0, index=common_dates)
    for acc in accounts_input:
        account_id = acc['account_id']
        if account_id not in nav_data:
            continue
        w = float(acc.get('weight', 0)) / total_weight
        daily_ret = nav_data[account_id].loc[common_dates, 'daily_return'].fillna(0)
        combined_returns = combined_returns + w * daily_ret

    # 累乘得到组合净值，归一化起点为 1.0
    combined_nav = (1 + combined_returns).cumprod()
    combined_nav = combined_nav / combined_nav.iloc[0]

    # 统计指标
    total_return = float(combined_nav.iloc[-1] - 1)
    rolling_max = combined_nav.cummax()
    drawdowns = (combined_nav - rolling_max) / rolling_max
    max_drawdown = float(abs(drawdowns.min()))

    if len(combined_returns) > 1 and combined_returns.std() > 0:
        excess = combined_returns - 0.02 / 252
        sharpe = float((excess.mean() / excess.std()) * (252 ** 0.5))
    else:
        sharpe = 0.0

    # 各账户对齐后的净值（归一化到公共起点 1.0，用于图表叠加）
    from xxybacktest.simulation.submitter import get_account as _get_acc
    accounts_out = []
    for acc in accounts_input:
        account_id = acc['account_id']
        if account_id not in nav_data:
            continue
        acc_nav_series = nav_data[account_id].loc[common_dates, 'nav']
        base = float(acc_nav_series.iloc[0])
        normalized = [round(float(v) / base, 4) for v in acc_nav_series]

        acc_info = _get_acc(account_id, data_path=DEFAULT_DATA_PATH)
        acc_name = acc_info['name'] if acc_info else account_id

        actual_weight = round(float(acc.get('weight', 0)) / total_weight * 100, 1)
        accounts_out.append({
            'account_id': account_id,
            'name': acc_name,
            'weight': actual_weight,
            'nav': normalized,
        })

    return jsonify({
        'combined': {
            'dates': common_dates,
            'nav': [round(float(v), 4) for v in combined_nav.tolist()],
        },
        'accounts': accounts_out,
        'stats': {
            'total_return': round(total_return, 4),
            'max_drawdown': round(max_drawdown, 4),
            'sharpe_ratio': round(sharpe, 2),
            'start_date': common_dates[0],
            'end_date': common_dates[-1],
            'days': len(common_dates),
        }
    })
