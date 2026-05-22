"""账户列表页面路由 - 连接真实数据"""
import os
from flask import Blueprint, render_template

from xxybacktest.simulation.submitter import list_accounts
from xxybacktest.simulation.runner import get_account_nav

dashboard_bp = Blueprint('dashboard', __name__)

# 默认数据路径
DEFAULT_DATA_PATH = os.environ.get('XXY_DATA_PATH', './data')


@dashboard_bp.route('/docs')
def docs():
    """API 文档页面"""
    return render_template('docs.html')


@dashboard_bp.route('/')
def index():
    """账户列表首页 - 从 xxydb 读取真实数据"""

    accounts_raw = list_accounts(data_path=DEFAULT_DATA_PATH)

    accounts = []
    for acc in accounts_raw:
        account_id = acc['account_id']

        nav_df = get_account_nav(account_id, data_path=DEFAULT_DATA_PATH)

        if not nav_df.empty:
            first_nav = nav_df['nav'].iloc[0]
            last_nav = nav_df['nav'].iloc[-1]
            total_return = (last_nav - first_nav) / first_nav if first_nav > 0 else 0

            nav_series = nav_df['nav']
            rolling_max = nav_series.cummax()
            drawdowns = (nav_series - rolling_max) / rolling_max
            max_drawdown = abs(drawdowns.min()) if len(drawdowns) > 0 else 0

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
            max_drawdown = 0
            latest_daily_return = 0
            latest_return_date = ""

        created_at = acc.get('created_at', '')
        if hasattr(created_at, 'strftime'):
            created_at = created_at.strftime('%Y-%m-%d')
        elif isinstance(created_at, str):
            created_at = created_at[:10]

        nav_curve = []
        if not nav_df.empty:
            nav_df['date'] = nav_df['date'].astype(str).str[:10]
            nav_values = nav_df['nav'].tolist()
            if len(nav_values) > 30:
                step = len(nav_values) // 30
                nav_curve = nav_values[::step]
                if nav_values[-1] not in nav_curve:
                    nav_curve.append(nav_values[-1])
            else:
                nav_curve = nav_values

        accounts.append({
            'account_id': account_id,
            'name': acc['name'],
            'status': acc['status'],
            'account_type': acc.get('account_type', 'sim'),
            'total_return': total_return,
            'latest_daily_return': latest_daily_return,
            'latest_return_date': latest_return_date,
            'max_drawdown': max_drawdown,
            'created_at': created_at,
            'nav_curve': nav_curve
        })

    stats = {
        'total_accounts': len(accounts),
        'running': sum(1 for a in accounts if a['status'] == 'running'),
        'total_return': sum(a['total_return'] for a in accounts)
    }

    return render_template('dashboard.html', accounts=accounts, stats=stats)
