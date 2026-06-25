"""
live/trader.py — QMT 交易通道

唯一与 QMT API 打交道的模块，对外屏蔽 xtquant 细节。
上层模块（context.py / trading.py）只调用本模块的公开接口，
不直接 import xtquant。

依赖：
    xtquant（本地安装，不在 pyproject.toml 中声明）
    安装方式：pip install xtquant  或从 QMT 客户端目录拷贝
"""

import time
import random

try:
    from xtquant import xtdata
    from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
    from xtquant.xttype import StockAccount
    import xtquant.xtconstant as xtconstant
    _XTQUANT_AVAILABLE = True
except ImportError:
    _XTQUANT_AVAILABLE = False


class QMTConnectionError(Exception):
    """QMT 连接失败异常"""
    pass


class QMTOrderError(Exception):
    """QMT 下单失败异常"""
    pass


def check_qmt_login(qmt_path: str, account_id: str) -> bool:
    """
    快速检测 QMT 客户端是否已登录（只做一次连接尝试，不重试）。
    返回 True 表示已登录，False 表示未登录或 xtquant 未安装。
    """
    if not _XTQUANT_AVAILABLE:
        return False

    session_id = random.randint(100000, 999999)
    trader = None
    try:
        trader = XtQuantTrader(qmt_path, session_id)
        callback = XtQuantTraderCallback()
        trader.register_callback(callback)
        trader.start()

        ret = trader.connect()
        if ret != 0:
            return False

        acc = StockAccount(account_id, 'STOCK')
        asset = trader.query_stock_asset(acc)
        return asset is not None
    except Exception:
        return False
    finally:
        if trader is not None:
            try:
                trader.stop()
            except Exception:
                pass


def _require_xtquant():
    if not _XTQUANT_AVAILABLE:
        raise ImportError(
            "xtquant 未安装。请从 QMT 客户端目录安装：\n"
            "  pip install <QMT安装目录>/userdata/xtquant\n"
            "或联系迅投获取安装包。"
        )


class QMTTrader:
    """
    QMT 交易通道。

    职责：
        - 连接 QMT 客户端（含重试）
        - 查询资金、持仓、最新价
        - 原始下单（order_stock）

    不包含任何登录逻辑，调用方需确保 QMT 客户端已登录。

    参数:
        qmt_path:       QMT 客户端安装目录（含 XtQuantClient 可执行文件的目录）
        account_id:     QMT 资金账号（字符串）
        retry:          连接失败最大重试次数（默认 5）
        interval:       每次重试间隔秒数（默认 3）
    """

    def __init__(self, qmt_path: str, account_id: str,
                 retry: int = 5, interval: int = 3):
        _require_xtquant()

        self.qmt_path = qmt_path
        self.account_id = account_id
        self._retry = retry
        self._interval = interval

        # 用随机 session_id 避免多账户冲突
        self._session_id = random.randint(100000, 999999)
        self._trader: "XtQuantTrader" = None
        self._acc: "StockAccount" = None
        self._connected = False

        self._connect()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def _connect(self):
        """连接 QMT，失败自动重试。"""
        last_err = None
        for attempt in range(1, self._retry + 1):
            try:
                trader = XtQuantTrader(self.qmt_path, self._session_id)

                callback = XtQuantTraderCallback()
                trader.register_callback(callback)

                trader.start()

                acc = StockAccount(self.account_id, 'STOCK')
                ret = trader.connect()
                if ret != 0:
                    raise QMTConnectionError(
                        f"XtQuantTrader.connect() 返回 {ret}，期望 0"
                    )

                # 订阅账户推送
                trader.subscribe(acc)

                self._trader = trader
                self._acc = acc
                self._connected = True
                print(f"[QMTTrader] 连接成功，账号: {self.account_id}，"
                      f"session: {self._session_id}")
                return

            except Exception as e:
                last_err = e
                print(f"[QMTTrader] 第 {attempt}/{self._retry} 次连接失败: {e}")
                if attempt < self._retry:
                    time.sleep(self._interval)

        raise QMTConnectionError(
            f"QMT 连接失败，已重试 {self._retry} 次。最后错误: {last_err}\n"
            "请确认：① QMT 客户端已启动并登录  ② qmt_path 路径正确"
        )

    def is_connected(self) -> bool:
        """检查连接状态。"""
        return self._connected and self._trader is not None

    def disconnect(self):
        """断开连接，释放资源。"""
        if self._trader is not None:
            try:
                self._trader.stop()
            except Exception:
                pass
            self._trader = None
            self._connected = False

    # ------------------------------------------------------------------
    # 资金与持仓查询
    # ------------------------------------------------------------------

    def get_portfolio(self) -> dict:
        """
        查询账户资金概况。

        返回:
            {
                'cash':          float,  # 可用资金
                'frozen_cash':   float,  # 冻结资金
                'market_value':  float,  # 持仓市值
                'total_asset':   float,  # 总资产
            }
        """
        asset = self._trader.query_stock_asset(self._acc)
        if asset is None:
            raise QMTConnectionError("query_stock_asset 返回 None，请检查 QMT 连接状态")

        return {
            'cash':         float(asset.cash),
            'frozen_cash':  float(asset.frozen_cash),
            'market_value': float(asset.market_value),
            'total_asset':  float(asset.total_asset),
        }

    def get_position(self, code: str) -> dict | None:
        """
        查询单只股票持仓，无持仓时返回 None。

        参数:
            code: 股票代码，如 '000001.SZ'

        返回:
            {
                'volume':          int,    # 总持仓数量
                'can_sell_volume': int,    # 可卖数量（T+1）
                'cost_price':      float,  # 持仓均价
                'last_price':      float,  # 最新价
                'market_value':    float,  # 持仓市值
            }
            无持仓返回 None
        """
        positions = self.get_positions()
        return positions.get(code)

    def get_positions(self) -> dict:
        """
        查询当前持仓。

        返回:
            {
                '000001.SZ': {
                    'volume':          int,    # 总持仓数量
                    'can_sell_volume': int,    # 可卖数量（T+1）
                    'cost_price':      float,  # 持仓均价
                    'last_price':      float,  # 最新价
                    'market_value':    float,  # 持仓市值
                },
                ...
            }
        """
        positions = self._trader.query_stock_positions(self._acc)
        if positions is None:
            return {}

        result = {}
        for pos in positions:
            if pos.volume <= 0:
                continue
            result[pos.stock_code] = {
                'volume':          int(pos.volume),
                'can_sell_volume': int(pos.can_use_volume),
                'cost_price':      float(pos.avg_price),
                'last_price':      float(pos.last_price),
                'market_value':    float(pos.volume * pos.last_price),
            }
        return result

    def get_price(self, code: str) -> float | None:
        """
        获取股票最新价（通过 xtdata.get_full_tick）。

        停牌或无行情时返回 None。

        参数:
            code: 股票代码，如 '000001.SZ'
        """
        try:
            ticks = xtdata.get_full_tick([code])
            price = float(ticks[code].get('lastPrice', 0)) if (ticks and code in ticks) else 0.0

            if price <= 0:
                # 冷缓存兜底：非持仓/未订阅标的首次访问时，QMT 本地缓存里没有它的 tick，
                # 被动等访问触发订阅会出现「头几次返 None、再跑才有价」。这里主动订阅并
                # 短暂轮询等待 QMT 推送首个 tick，把冷启动消化在函数内部。
                xtdata.subscribe_quote(code, period='tick')
                for _ in range(15):              # 最多等约 2 秒
                    time.sleep(0.13)
                    ticks = xtdata.get_full_tick([code])
                    if ticks and code in ticks:
                        price = float(ticks[code].get('lastPrice', 0))
                        if price > 0:
                            break

            # lastPrice 仍为 0 视为无效（停牌 / 真无行情）
            return price if price > 0 else None
        except Exception as e:
            print(f"[QMTTrader] get_price({code}) 异常: {e}")
            return None

    # ------------------------------------------------------------------
    # 下单
    # ------------------------------------------------------------------

    @staticmethod
    def _get_market_price_type(code: str) -> int:
        """根据代码后缀返回对应市场的五档即成剩撤市价单类型（保证立刻成交）。"""
        if code.endswith('.SH'):
            return xtconstant.MARKET_SH_CONVERT_5_CANCEL
        elif code.endswith('.SZ'):
            return xtconstant.MARKET_SZ_CONVERT_5_CANCEL
        elif code.endswith('.BJ'):
            return xtconstant.MARKET_BEST
        else:
            return xtconstant.LATEST_PRICE

    def order_stock(self, code: str, volume: int, direction: str,
                    price_type: str = 'MARKET', price: float = 0.0) -> dict:
        """
        原始下单接口。

        参数:
            code:       股票代码，如 '000001.SZ'
            volume:     下单数量（正整数，股）
            direction:  'BUY' | 'SELL'
            price_type: 'MARKET'（五档即成剩撤，保证立刻成交）| 'FIX'（限价）
            price:      限价单价格，市价单传 0.0

        返回:
            {
                'status':   'submitted' | 'error',
                'order_id': str | None,   # QMT 返回的委托号
                'msg':      str,
            }
        """
        if volume <= 0:
            return {'status': 'error', 'order_id': None,
                    'msg': f'下单数量无效: {volume}'}

        # 方向映射
        if direction == 'BUY':
            xt_direction = xtconstant.STOCK_BUY
        elif direction == 'SELL':
            xt_direction = xtconstant.STOCK_SELL
        else:
            return {'status': 'error', 'order_id': None,
                    'msg': f'未知方向: {direction}，应为 BUY 或 SELL'}

        # 报价类型映射
        if price_type == 'MARKET':
            xt_price_type = self._get_market_price_type(code)
        elif price_type == 'FIX':
            xt_price_type = xtconstant.FIX_PRICE
        else:
            return {'status': 'error', 'order_id': None,
                    'msg': f'未知报价类型: {price_type}，应为 MARKET 或 FIX'}

        try:
            order_id = self._trader.order_stock(
                self._acc,
                code,
                xt_direction,
                volume,
                xt_price_type,
                price
            )

            if order_id == -1:
                return {
                    'status': 'error',
                    'order_id': None,
                    'msg': 'order_stock 返回 -1，委托提交失败',
                }

            return {
                'status': 'submitted',
                'order_id': str(order_id),
                'msg': f'{direction} {code} x{volume} 委托已提交',
            }

        except Exception as e:
            return {
                'status': 'error',
                'order_id': None,
                'msg': f'下单异常: {e}',
            }
