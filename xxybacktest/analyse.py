"""
================================================================================
BarraLens —— Barra 风险数据透视镜
================================================================================
传入 xxybacktest 回测的 performance 对象, 自动对接 exposure / factor_return /
specific_return 三张表, 一个方法出一个结论。

用法:
    from xxybacktest.analyse import BarraLens
    ctx = run_backtest(...)
    lens = BarraLens(ctx.performance)      # 传 performance; db 默认复用回测的 Data._db
    lens.exposure_snapshot()   # 体检: 我在赌什么
    lens.attribution()         # 归因: 我赚/亏在哪个维度
    lens.alpha_curve()         # 选股能力: 剥离beta后有没有真本事

三张表各自回答:
  exposure(暴露)        → 押了哪些因子、押多重        → 体检/排雷
  factor_return(因子收益) → 每个因子这段帮我还是害我    → 归因
  specific_return(特质)  → 剥离所有因子后的纯选股能力   → 有没有alpha
================================================================================
"""
import numpy as np
import pandas as pd

INDUSTRIES = ['交通运输','传媒','公用事业','农林牧渔','医药生物','商贸零售','国防军工',
    '基础化工','家用电器','建筑材料','建筑装饰','房地产','有色金属','机械设备','汽车','煤炭',
    '环保','电力设备','电子','石油石化','社会服务','纺织服饰','综合','美容护理','计算机',
    '轻工制造','通信','钢铁','银行','非银金融','食品饮料']
STYLES = ['z_size','z_earningsyield','z_lev','z_growth_rev','z_quality',
    'z_value','z_div','z_mom','z_vol','z_liq']
STYLE_CN = {'z_size':'市值','z_earningsyield':'盈利收益率','z_lev':'杠杆','z_growth_rev':'成长',
    'z_quality':'质量','z_value':'价值','z_div':'红利','z_mom':'动量','z_vol':'波动','z_liq':'流动性'}


class BarraLens:
    def __init__(self, performance, db=None, data_path='./data'):
        """
        performance: xxybacktest run_backtest 返回的 ctx.performance
        db:   可选, 传入一个已开的 xxydb 连接直接复用(此时不负责关闭)
        data_path: 不传 db 时, 用它自开一个独立连接(默认 ./data)
                   注意: 不复用 Data._db, 因回测结束后框架会关闭它
        """
        if db is not None:
            self.db = db
            self._own_db = False        # 外部传入, 不由本类关闭
        else:
            from xxydb import xxydb
            self.db = xxydb(path=data_path)
            self._own_db = True         # 自开, close() 时关闭

        # 逐日持仓快照 → (date, instrument, ratio, w)
        snaps = pd.DataFrame(performance.get('position_snapshots'))
        snaps['date'] = pd.to_datetime(snaps['date'])
        snaps['w'] = snaps.groupby('date')['ratio'].transform(
            lambda x: x / x.sum() if x.sum() > 0 else x)   # 持仓内归一化(排除现金)
        self.pos = snaps

        # 策略日收益 + 基准
        self.ret = performance.get('returns').copy()
        self.ret.index = pd.to_datetime(self.ret.index)
        bench = performance.get('bench_returns')
        self.bench = bench.copy() if bench is not None else None
        if self.bench is not None:
            self.bench.index = pd.to_datetime(self.bench.index)

        self.start = self.pos['date'].min()
        self.end = self.pos['date'].max()
        self._expo = None
        self._fr = None

    def _load_exposure(self):
        if self._expo is None:
            q = f"SELECT date, instrument, {','.join(STYLES+INDUSTRIES)} FROM exposure"
            e = self.db.query(q, filters={'date': (str(self.start.date()), str(self.end.date()))}).df()
            e['date'] = pd.to_datetime(e['date'])
            self._expo = e
        return self._expo

    def _load_factor_return(self):
        if self._fr is None:
            q = f"SELECT date, expo_date, country, {','.join(STYLES+INDUSTRIES)} FROM factor_return"
            fr = self.db.query(q).df()
            fr['date'] = pd.to_datetime(fr['date'])
            fr['expo_date'] = pd.to_datetime(fr['expo_date'])
            self._fr = fr
        return self._fr

    def close(self):
        """仅关闭自己开的连接; 复用的 Data._db 不关(留给回测框架)"""
        if self._own_db:
            self.db.close()

    # ========================================================================
    # 方法1: 体检 —— "我在赌什么"
    # ========================================================================
    def exposure_snapshot(self, date=None, verbose=True):
        """
        最新持仓(或指定日)的风格暴露 + 行业集中度。
        回答: 我这堆持仓, 主动/被动押了哪些因子。
        返回: dict{'style': Series, 'industry': Series}
        """
        expo = self._load_exposure()
        d = pd.to_datetime(date) if date else self.end
        pos_dates = self.pos['date'].unique()
        d = max([x for x in pos_dates if x <= d], default=self.end)

        cur = self.pos[self.pos['date'] == d][['instrument', 'w']]
        m = cur.merge(expo[expo['date'] == d], on='instrument', how='left')

        sty = pd.Series({s: (m['w'] * m[s]).sum() for s in STYLES})
        ind = pd.Series({i: (m['w'] * m[i]).sum() for i in INDUSTRIES}).sort_values(ascending=False)

        if verbose:
            print('='*60)
            print(f'【体检】持仓日 {pd.Timestamp(d).date()}   持仓 {len(cur)} 只')
            print('='*60)
            print('\n风格暴露 (单位=标准差, |值|越大押得越重):')
            for s in STYLES:
                e = sty[s]
                tag = '  ← 重度!' if abs(e) >= 1.0 else ('  ← 明显' if abs(e) >= 0.5 else '')
                print(f'  {STYLE_CN[s]:6s} {e:+.2f}{tag}')
            print('\n行业暴露 (前5):')
            for name, wt in ind.head(5).items():
                print(f'  {name:6s} {wt*100:5.1f}%')
            print(f'  >>> 前3行业合计 {ind.head(3).sum()*100:.1f}%  (>60%=过度集中)')
        return {'style': sty, 'industry': ind}

    # ========================================================================
    # 方法2: 归因 —— "我赚/亏在哪个维度"
    # ========================================================================
    def attribution(self, verbose=True):
        """
        把策略收益拆成: 市场beta(国家) + 各风格 + 行业 + 特质。
        口径: T日组合暴露 × (T→T+1因子收益), 算术累加。
        返回: DataFrame(因子, 累计贡献pt)
        """
        expo = self._load_exposure()
        fr = self._load_factor_return()

        pe = self.pos.merge(expo, on=['date', 'instrument'], how='inner')
        port_expo = pe.groupby('date').apply(
            lambda g: pd.Series({f: (g['w'] * g[f]).sum() for f in STYLES + INDUSTRIES}),
            include_groups=False)

        merged = port_expo.merge(fr.set_index('expo_date'), left_index=True, right_index=True,
                                 suffixes=('_e', ''))
        contrib = {}
        for f in STYLES + INDUSTRIES:
            contrib[f] = (merged[f'{f}_e'] * merged[f]).sum()
        contrib['country'] = merged['country'].sum()

        style_c = pd.Series({f: contrib[f] for f in STYLES}) * 100
        ind_c = sum(contrib[i] for i in INDUSTRIES) * 100
        country_c = contrib['country'] * 100
        strat_cum = ((1 + self.ret.dropna()).prod() - 1) * 100

        if verbose:
            print('='*60)
            print('【归因】收益来源分解 (算术累加口径, 百分点)')
            print('='*60)
            print(f'  国家因子(市场β) {country_c:+8.2f}')
            srt = style_c.reindex(style_c.abs().sort_values(ascending=False).index)
            for f in srt.index:
                print(f'  {STYLE_CN[f]:6s}         {srt[f]:+8.2f}')
            print(f'  行业合计       {ind_c:+8.2f}')
            print('-'*60)
            print(f'  策略累计收益(复利,仅参照) {strat_cum:+.2f}')
            print('\n  ⚠ 口径提醒: 上面是算术累加, 不能直接和复利总收益相减求alpha。')
            print('  ⚠ size贡献是"剥离其他因子后"的纯效应, 若你满仓小盘却见size≈0,')
            print('    是因为小盘的钱被流动性/波动/行业分走了 —— 用 alpha_curve() 看真本事。')

        out = pd.Series({'国家(市场β)': country_c, **{STYLE_CN[f]: style_c[f] for f in STYLES},
                         '行业合计': ind_c})
        return out.to_frame('累计贡献pt')

    # ========================================================================
    # 方法3: 选股能力 —— "剥离所有beta后, 我到底有没有真本事"
    # ========================================================================
    def alpha_curve(self, verbose=True):
        """
        用 specific_return(特质收益/残差)看纯选股能力。
        逻辑: 组合特质收益 = Σ w_i × u_i (持仓股当日残差加权)。
        累计上扬=有真alpha; 走平/向下=beta搬运工。
        返回: Series(累计特质收益曲线)
        """
        insts_dates = self.pos[['date', 'instrument', 'w']]
        q = "SELECT expo_date AS date, instrument, u FROM specific_return"
        sr = self.db.query(q, filters={'date': (str(self.start.date()), str(self.end.date()))}).df()
        sr['date'] = pd.to_datetime(sr['date'])

        m = insts_dates.merge(sr, on=['date', 'instrument'], how='inner')
        daily_spec = m.groupby('date').apply(lambda g: (g['w'] * g['u']).sum(),
                                             include_groups=False)
        cum = daily_spec.cumsum() * 100

        if verbose:
            print('='*60)
            print('【选股能力】纯特质收益 (剥离所有因子后的真alpha)')
            print('='*60)
            print(f'  累计特质收益: {cum.iloc[-1]:+.2f} 百分点 ({len(cum)}天)')
            print(f'  日均特质:     {daily_spec.mean()*100:+.4f}%')
            ann = daily_spec.mean() * 252 * 100
            print(f'  年化特质:     {ann:+.2f}%')
            if cum.iloc[-1] > 5:
                print('  → 特质持续为正: 你有真选股能力(不只是beta搬运)')
            elif cum.iloc[-1] < -5:
                print('  → 特质为负: 选股在拖后腿, 收益全靠因子暴露撑')
            else:
                print('  → 特质≈0: 你基本是个beta搬运工, alpha不明显')
        return cum

