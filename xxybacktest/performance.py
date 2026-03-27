"""
G1 + G2 + G3: 收益率序列处理 + 绩效指标计算 + 绩效展示

G1: 将回测主循环记录的原始净值比数据转为 pandas Series，
    并获取基准指数收益率序列。
G2: 基于 empyrical 库计算各类绩效指标（alpha, beta, sharpe 等），
    以及自算指标（SQN, roto, win_ratio, R2, information_ratio）。
G3: 在 Notebook 中展示回测曲线和绩效指标表。
"""

import numpy as np
import pandas as pd
import empyrical as ep
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from .data import Data


def _safe(value):
    """将 NaN / Inf 置为 0。"""
    if value is None or np.isnan(value) or np.isinf(value):
        return 0.0
    return float(value)


class Performance:
    @staticmethod
    def analyse(context):
        # 1. 策略收益率序列处理
        raw = pd.DataFrame(
            context.performance.returns,
            columns=["trade_date", "returns"],
        )
        raw["trade_date"] = pd.to_datetime(raw["trade_date"])
        raw = raw.set_index("trade_date")

        # 净值比 → 涨跌幅（1.02 → 0.02）
        returns = raw["returns"] - 1

        # 2. 基准收益率序列
        benchmark = context.trade.benchmark
        if benchmark is not None:
            # index_bar 中代码带后缀（如 000001.SH），裸代码需补 .SH
            if "." not in benchmark:
                benchmark = benchmark + ".SH"
            start_date = context.trade.start_time
            end_date = context.trade.end_time
            index_df = Data.get_index_daily(benchmark, start_date, end_date)
            index_df["trade_date"] = pd.to_datetime(index_df["trade_date"])
            index_df = index_df.set_index("trade_date")
            bench_returns = index_df["pct_chg"] / 100  # 百分比 → 小数
        else:
            bench_returns = None

        # 3. 写回 context
        context.performance.returns = returns
        context.performance.bench_returns = bench_returns

        # 4. 绩效指标计算 (G2)
        indicators = Performance._compute_indicators(
            returns, bench_returns, context
        )
        context.performance.indicators = indicators

    @staticmethod
    def _compute_indicators(returns, bench_returns, context):
        """计算全部绩效指标，返回 dict。"""
        ind = {}

        # --- empyrical 指标 ---
        ind["annual_return"] = _safe(ep.annual_return(returns, period="daily"))
        ind["cagr"] = _safe(ep.cagr(returns, period="daily"))
        ind["annual_volatility"] = _safe(
            ep.annual_volatility(returns, period="daily")
        )
        ind["sharpe"] = _safe(ep.sharpe_ratio(returns, period="daily"))
        ind["sortino"] = _safe(ep.sortino_ratio(returns, period="daily"))
        ind["calmar"] = _safe(ep.calmar_ratio(returns, period="daily"))
        ind["omega"] = _safe(ep.omega_ratio(returns))
        ind["max_drawdown"] = _safe(ep.max_drawdown(returns))
        ind["downside_risk"] = _safe(
            ep.downside_risk(returns, period="daily")
        )

        # alpha / beta 需要基准
        if bench_returns is not None and len(bench_returns) > 0:
            # 对齐日期（取交集）
            aligned = pd.DataFrame({
                "r": returns,
                "b": bench_returns,
            }).dropna()

            if len(aligned) > 1:
                r_aligned = aligned["r"]
                b_aligned = aligned["b"]
                alpha, beta = ep.alpha_beta(
                    r_aligned, b_aligned, period="daily"
                )
                ind["alpha"] = _safe(alpha)
                ind["beta"] = _safe(beta)

                # information_ratio：手动计算（empyrical 无此函数）
                # IR = mean(active_return) / std(active_return)
                active = r_aligned - b_aligned
                active_std = active.std()
                if active_std != 0:
                    ind["info_ratio"] = _safe(active.mean() / active_std)
                else:
                    ind["info_ratio"] = 0.0

                # R² — 策略收益率对基准收益率的回归 R²
                ss_res = ((r_aligned - b_aligned) ** 2).sum()
                ss_tot = ((r_aligned - r_aligned.mean()) ** 2).sum()
                if ss_tot != 0:
                    ind["R2"] = _safe(1 - ss_res / ss_tot)
                else:
                    ind["R2"] = 0.0
            else:
                ind["alpha"] = 0.0
                ind["beta"] = 0.0
                ind["info_ratio"] = 0.0
                ind["R2"] = 0.0
        else:
            ind["alpha"] = 0.0
            ind["beta"] = 0.0
            ind["info_ratio"] = 0.0
            ind["R2"] = 0.0

        # --- 自算指标 ---
        trade_num = context.performance.trade_num
        win = context.performance.win
        trade_returns = context.logs.trade_returns

        # win_ratio
        if trade_num > 0:
            ind["win_ratio"] = win / trade_num
        else:
            ind["win_ratio"] = 0.0
        context.performance.win_ratio = ind["win_ratio"]

        # roto — 总收益率 = total_value / starting_cash - 1
        starting_cash = context.portfolio.starting_cash
        if starting_cash != 0:
            ind["roto"] = context.portfolio.total_value / starting_cash - 1
        else:
            ind["roto"] = 0.0

        # SQN = sqrt(trade_num) * mean(trade_returns) / std(trade_returns)
        if trade_num > 1 and len(trade_returns) > 1:
            tr_arr = np.array(trade_returns, dtype=float)
            tr_std = tr_arr.std(ddof=1)
            if tr_std != 0:
                ind["sqn"] = _safe(
                    np.sqrt(trade_num) * tr_arr.mean() / tr_std
                )
            else:
                ind["sqn"] = 0.0
        else:
            ind["sqn"] = 0.0

        ind["trade_num"] = trade_num

        return ind

    # ------------------------------------------------------------------
    # G3: 绩效展示（Notebook 内调用）
    # ------------------------------------------------------------------

    @staticmethod
    def plot(context):
        """在 Notebook 中展示回测曲线和绩效指标表。"""
        # 配置中文字体（Windows: SimHei / Microsoft YaHei）
        plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS"]
        plt.rcParams["axes.unicode_minus"] = False  # 负号正常显示

        returns = context.performance.returns
        bench_returns = context.performance.bench_returns
        indicators = context.performance.indicators

        # --- 累计净值曲线 ---
        cum_strategy = (1 + returns).cumprod()

        has_bench = bench_returns is not None and len(bench_returns) > 0
        if has_bench:
            cum_bench = (1 + bench_returns).cumprod()

        # --- 持仓占比序列 ---
        raw_ratio = pd.DataFrame(
            context.performance.position_ratio,
            columns=["trade_date", "ratio"],
        )
        raw_ratio["trade_date"] = pd.to_datetime(raw_ratio["trade_date"])
        raw_ratio = raw_ratio.set_index("trade_date")
        pos_ratio = raw_ratio["ratio"]

        fig, axes = plt.subplots(3, 1, figsize=(12, 10),
                                 gridspec_kw={"height_ratios": [3, 1, 1]},
                                 sharex=True)

        # 上图：累计净值
        ax1 = axes[0]
        ax1.plot(cum_strategy.index, cum_strategy.values,
                 label="策略", color="#d62728", linewidth=1.5)
        if has_bench:
            ax1.plot(cum_bench.index, cum_bench.values,
                     label="基准", color="#1f77b4", linewidth=1.2, alpha=0.8)
        ax1.set_ylabel("累计净值")
        ax1.set_title("回测绩效")
        ax1.legend(loc="upper left")
        ax1.grid(True, alpha=0.3)
        ax1.axhline(y=1.0, color="grey", linestyle="--", linewidth=0.8)

        # 中图：持仓占比
        ax2 = axes[1]
        ax2.fill_between(pos_ratio.index, pos_ratio.values, 0,
                         color="#2ca02c", alpha=0.4)
        ax2.plot(pos_ratio.index, pos_ratio.values,
                 color="#2ca02c", linewidth=0.8)
        ax2.set_ylabel("持仓占比")
        ax2.set_ylim(-0.05, 1.05)
        ax2.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))
        ax2.grid(True, alpha=0.3)

        # 下图：回撤曲线
        ax3 = axes[2]
        cum_max = cum_strategy.cummax()
        drawdown = (cum_strategy - cum_max) / cum_max
        ax3.fill_between(drawdown.index, drawdown.values, 0,
                         color="#d62728", alpha=0.3)
        ax3.plot(drawdown.index, drawdown.values,
                 color="#d62728", linewidth=0.8)
        ax3.set_ylabel("回撤")
        ax3.set_xlabel("日期")
        ax3.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))
        ax3.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.show()

        # --- 绩效指标表 ---
        # 指标名称中英文映射 + 格式化
        rows = [
            ("总收益率",      "roto",              "{:.2%}"),
            ("年化收益率",    "annual_return",     "{:.2%}"),
            ("CAGR",          "cagr",              "{:.2%}"),
            ("年化波动率",    "annual_volatility", "{:.2%}"),
            ("最大回撤",      "max_drawdown",      "{:.2%}"),
            ("夏普比率",      "sharpe",            "{:.4f}"),
            ("索提诺比率",    "sortino",           "{:.4f}"),
            ("卡尔玛比率",    "calmar",            "{:.4f}"),
            ("Omega",         "omega",             "{:.4f}"),
            ("Alpha",         "alpha",             "{:.4f}"),
            ("Beta",          "beta",              "{:.4f}"),
            ("信息比率",      "info_ratio",        "{:.4f}"),
            ("下行风险",      "downside_risk",     "{:.2%}"),
            ("R²",            "R2",                "{:.4f}"),
            ("SQN",           "sqn",               "{:.4f}"),
            ("交易次数",      "trade_num",         "{:.0f}"),
            ("胜率",          "win_ratio",         "{:.2%}"),
        ]

        col_name = []
        col_value = []
        for label, key, fmt in rows:
            val = indicators[key] if key in indicators else 0.0
            col_name.append(label)
            col_value.append(fmt.format(val))

        df_display = pd.DataFrame({"指标": col_name, "值": col_value})

        try:
            from IPython.display import display
            display(df_display.style.hide(axis="index").set_properties(
                **{"text-align": "left"}
            ))
        except ImportError:
            print(df_display.to_string(index=False))
