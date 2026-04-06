"""API 路由（AJAX 调用）- 连接真实数据"""
import os
from flask import Blueprint, jsonify
import pandas as pd

from xxybacktest.simulation.submitter import list_accounts, pause, resume, delete
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
        else:
            total_return = 0
            current_nav = 1.0

        accounts.append({
            'account_id': account_id,
            'name': acc['name'],
            'status': acc['status'],
            'total_return': round(total_return, 4),
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
