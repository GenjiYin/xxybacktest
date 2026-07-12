"""
================================================================================
FactorResult —— 因子分析结果对象
================================================================================
把 engine 输出的六键 dict 包装成好用的对象, 供 notebook 探索:
    res = analyze_factor(sql="...", data_path="...")
    res.summary()        # 打印核心指标(风格对齐 BarraLens 的中文体检)
    res.plot_ic()        # 累计 IC 曲线
    res.plot_groups()    # 分组年化柱状 + 分组净值曲线
    res.plot_ls()        # 多空净值曲线
    res.ic_series / res.groups / res.yearly / res.metrics   # 原始 DataFrame
    res.to_dict()        # 转成前端/落盘用的 JSON 结构(store 和 web 复用)

画图用 matplotlib(可选依赖, 未装则 plot_* 给出友好提示)。
================================================================================
"""
import numpy as np
import pandas as pd


class FactorResult:
    """因子分析结果的容器 + 展示层。构造自 engine 的六键 dict。"""

    def __init__(self, output, name=None):
        """
        output: engine.analyze / analyze_from_sql 返回的 dict
        name:   因子名称(展示用, 可选)
        """
        self.name = name or "因子"
        self.ic_series = output["ic_series"]
        self.groups = output["groups"]
        self.group_summary = output["group_summary"]
        self.ls_series = output["ls_series"]
        self.yearly = output["yearly"]
        self.metrics = output["metrics"]
        # 因子有效时限 IC 衰减曲线(可能为空 DataFrame, 当 with_horizon=False 时)
        self.decay_curve = output.get("decay_curve", pd.DataFrame())
        self.params = output.get("params", {})

    # ------------------------------------------------------------------
    # 文字体检
    # ------------------------------------------------------------------
    def summary(self, verbose=True):
        """打印全区间核心指标 + 年度拆解。返回 metrics dict。"""
        m = self.metrics
        bp = m.get("base_period", "?")
        if verbose:
            print("=" * 60)
            print(f"【因子体检】{self.name}   (主周期 {bp} 日, 样本 {m.get('n_days', 0)} 个截面)")
            print("=" * 60)

            def _pct(x):
                return f"{x*100:+.2f}%" if x == x else "  n/a"

            def _num(x):
                return f"{x:+.3f}" if x == x else "  n/a"

            print(f"  IC 均值      {_pct(m.get('ic_mean', np.nan))}"
                  f"       ICIR       {_num(m.get('icir', np.nan))}")
            print(f"  IC 胜率      {_pct(m.get('ic_win_rate', np.nan))}"
                  f"       方向       {m.get('direction', '?')}")
            print(f"  多空年化     {_pct(m.get('ls_return', np.nan))}"
                  f"       多空夏普   {_num(m.get('ls_sharpe', np.nan))}")
            print(f"  多空回撤     {_pct(m.get('ls_maxdd', np.nan))}"
                  f"       换手       {_pct(m.get('turnover', np.nan))}")
            print(f"  覆盖度       {_pct(m.get('coverage', np.nan))}")

            # 各周期 IC
            per = self.params.get("periods", [])
            if per:
                ics = "  ".join(f"{n}日 {m.get(f'ic_mean_{n}', np.nan):+.4f}"
                                for n in per)
                print(f"\n  各周期 IC 均值:  {ics}")

            # 分组单调性提示
            if not self.group_summary.empty:
                ann = self.group_summary.sort_values("group")["ann_return"].values
                mono_up = all(ann[i] <= ann[i+1] for i in range(len(ann)-1))
                mono_dn = all(ann[i] >= ann[i+1] for i in range(len(ann)-1))
                tag = ("单调递增 ✓" if mono_up else
                       "单调递减 ✓" if mono_dn else "非单调(尾部效应?)")
                print(f"  分组年化: Q1 {_pct(ann[0])} → Q{len(ann)} {_pct(ann[-1])}  [{tag}]")

            if not self.yearly.empty:
                print("\n  年度拆解:")
                for _, r in self.yearly.iterrows():
                    print(f"    {int(r['year'])}  IC {r['ic']:+.4f}"
                          f"  多空 {_pct(r['ls_return'])}"
                          f"  多头 {_pct(r['long_return'])}")
        return m

    # ------------------------------------------------------------------
    # 画图(matplotlib 可选)
    # ------------------------------------------------------------------
    @staticmethod
    def _plt():
        try:
            import matplotlib.pyplot as plt
            import matplotlib
            # 中文与负号
            matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return plt
        except ImportError:
            print("[提示] 未安装 matplotlib, 无法画图。pip install matplotlib 后重试。")
            return None

    def _base_period_col(self):
        return f"ic_{self.params.get('base_period', self.params.get('periods', [1])[0])}"

    def plot_ic(self, ax=None):
        """累计 IC 曲线(主周期)。"""
        plt = self._plt()
        if plt is None:
            return None
        col = self._base_period_col()
        s = self.ic_series.dropna(subset=[col]).sort_values("date")
        cum = s[col].cumsum()
        if ax is None:
            _, ax = plt.subplots(figsize=(9, 3.5))
        ax.plot(s["date"], cum, color="#4c8dff", lw=1.5)
        ax.fill_between(s["date"], cum, alpha=0.12, color="#4c8dff")
        ax.axhline(0, color="#888", lw=0.6)
        ax.set_title(f"{self.name} · 累计 IC({self.params.get('base_period','')}日)")
        ax.grid(alpha=0.2)
        return ax

    def plot_groups(self, axes=None):
        """左: 分组年化收益柱状; 右: 分组净值曲线。"""
        plt = self._plt()
        if plt is None or self.group_summary.empty:
            return None
        if axes is None:
            _, axes = plt.subplots(1, 2, figsize=(13, 4))
        ax1, ax2 = axes

        # 分组年化柱状(红→蓝渐变)
        gs = self.group_summary.sort_values("group")
        n = len(gs)
        colors = [(1 - i/(n-1) if n > 1 else 0.5, 0.36, i/(n-1) if n > 1 else 0.5)
                  for i in range(n)]
        ax1.bar([f"Q{g+1}" for g in gs["group"]], gs["ann_return"] * 100,
                color=colors)
        ax1.axhline(0, color="#888", lw=0.6)
        ax1.set_title(f"{self.name} · 分组年化收益 (%)")
        ax1.grid(alpha=0.2, axis="y")

        # 分组净值曲线
        gr = self.groups.copy()
        if not gr.empty:
            gr = gr.sort_values(["group", "date"])
            for g, gg in gr.groupby("group"):
                nav = (1 + gg["ret"]).cumprod().values
                dates = gg["date"].values
                t = g / (n - 1) if n > 1 else 0.5
                ax2.plot(dates, nav, lw=1.2, color=(1-t, 0.36, t),
                         label=f"Q{g+1}")
            ax2.set_title(f"{self.name} · 分组净值曲线")
            ax2.legend(fontsize=7, ncol=2)
            ax2.grid(alpha=0.2)
        return axes

    def plot_ls(self, ax=None):
        """多空(最高分位 - 最低分位)净值曲线。"""
        plt = self._plt()
        if plt is None or self.ls_series.empty:
            return None
        s = self.ls_series.sort_values("date")
        nav = (1 + s["ret"]).cumprod().values
        if ax is None:
            _, ax = plt.subplots(figsize=(9, 3.5))
        ax.plot(s["date"], nav, color="#26c281", lw=1.6)
        ax.fill_between(s["date"], nav, 1, alpha=0.1, color="#26c281")
        ax.axhline(1, color="#888", lw=0.6)
        ax.set_title(f"{self.name} · 多空净值曲线")
        ax.grid(alpha=0.2)
        return ax

    def plot(self):
        """一次性画全部四张图(2x2)。notebook 里最常用。"""
        plt = self._plt()
        if plt is None:
            return None
        fig, axes = plt.subplots(2, 2, figsize=(14, 8))
        self.plot_ic(axes[0][0])
        self.plot_ls(axes[0][1])
        self.plot_groups([axes[1][0], axes[1][1]])
        fig.suptitle(f"因子分析 · {self.name}", fontsize=13, fontweight="bold")
        fig.tight_layout()
        return fig

    # ------------------------------------------------------------------
    # 序列化(供 store 落盘 / web 渲染复用)
    # ------------------------------------------------------------------
    def to_dict(self):
        """转成 JSON 友好结构。日期转字符串, NaN 转 None。"""
        def _df(df):
            if df is None or df.empty:
                return []
            d = df.copy()
            for c in d.columns:
                if np.issubdtype(d[c].dtype, np.datetime64):
                    d[c] = d[c].dt.strftime("%Y-%m-%d")
            return d.where(pd.notna(d), None).to_dict("records")

        def _clean(m):
            return {k: (None if (isinstance(v, float) and v != v) else v)
                    for k, v in m.items()}

        return {
            "name": self.name,
            "metrics": _clean(self.metrics),
            "ic_series": _df(self.ic_series),
            "groups": _df(self.groups),
            "group_summary": _df(self.group_summary),
            "ls_series": _df(self.ls_series),
            "yearly": _df(self.yearly),
            "decay_curve": _df(self.decay_curve),
            "params": self.params,
        }

    def __repr__(self):
        m = self.metrics
        return (f"<FactorResult {self.name} "
                f"IC={m.get('ic_mean', float('nan')):+.4f} "
                f"ICIR={m.get('icir', float('nan')):+.2f} "
                f"多空={m.get('ls_return', float('nan'))*100:+.1f}%>")
