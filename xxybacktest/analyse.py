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
    lens.exposure_snapshot()   # 体检: 我在赌什么(单期快照)
    lens.exposure_series()     # 时序: 我这一路都赌同一个吗(风格全程轨迹)
    lens.industry_series()     # 时序: 我这一路都押同一批行业吗(行业全程轨迹)
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


def _renorm(w):
    """inner join 丢掉缺数据的股票后, 对存活股票权重重新归一化(和=1)。
    否则 Σw<1 会把组合暴露/特质收益系统性往 0 缩, 低估真实口径。"""
    s = w.sum()
    return w / s if s > 0 else w


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
    # 方法1.5: 暴露时序 —— "我这一路都在赌同一个吗"
    # ========================================================================
    def exposure_series(self, verbose=True):
        """
        逐日组合风格暴露时序 + 全程统计。
        补 exposure_snapshot 的盲区: 单期快照看不出风格漂移,
        最后一天押 A, 可能中途从 B 换过来 —— 这里把整段轨迹摊开。
        判定口径:
          std 大   → 暴露漂移(择时/换仓), 快照会骗你
          |均值| 大 → 全程稳定押注, 才是真信仰
        返回: dict{'series': DataFrame(逐日风格暴露, 列=中文风格, 可直接 .plot()),
                  'stats':  DataFrame(均值/标准差/最小/最大/|均值|, 按|均值|排序)}
        """
        expo = self._load_exposure()
        pe = self.pos.merge(expo, on=['date', 'instrument'], how='inner')
        series = pe.groupby('date').apply(
            lambda g: pd.Series({s: (_renorm(g['w']) * g[s]).sum() for s in STYLES}),
            include_groups=False).sort_index()
        series_cn = series.rename(columns=STYLE_CN)

        stats = pd.DataFrame({
            '均值':  series.mean(),
            '标准差': series.std(),
            '最小':  series.min(),
            '最大':  series.max(),
        })
        stats['|均值|'] = stats['均值'].abs()
        stats = stats.rename(index=STYLE_CN).sort_values('|均值|', ascending=False)

        if verbose:
            print('='*60)
            print(f'【暴露时序】逐日风格暴露 全程统计  ({len(series)}个持仓日)')
            print(f'  {pd.Timestamp(series.index.min()).date()} → '
                  f'{pd.Timestamp(series.index.max()).date()}')
            print('='*60)
            print(f'  {"风格":6s} {"均值":>7s} {"标准差":>7s} {"最小":>7s} {"最大":>7s}   判定')
            for name, row in stats.iterrows():
                std, am = row['标准差'], row['|均值|']
                if std >= 0.5:
                    tag = '← 漂移大(择时/换仓)'
                elif am >= 1.0:
                    tag = '← 长期重仓(稳)'
                elif am >= 0.5:
                    tag = '← 持续偏向(稳)'
                else:
                    tag = ''
                print(f'  {name:6s} {row["均值"]:+7.2f} {std:7.2f} '
                      f'{row["最小"]:+7.2f} {row["最大"]:+7.2f}   {tag}')
            print('\n  >>> 标准差高的因子, exposure_snapshot() 的单期快照会误导你。')
        return {'series': series_cn, 'stats': stats}

    # ========================================================================
    # 方法1.6: 行业暴露时序 —— "我这一路都押同一批行业吗"
    # ========================================================================
    def industry_series(self, top=8, verbose=True):
        """
        逐日组合行业暴露(权重占比)时序 + 全程统计。
        补 exposure_snapshot 的盲区: 最新一天行业分布看不出中途有没有换赛道。
        与 exposure_series 的差异:
          风格看"押得多重(标准差)+ 漂移", 行业看"仓位占比 + 轮动/集中度"。
        判定口径:
          均值高      → 全程重仓该行业(真赛道信仰)
          均值中/std高 → 阶段性重仓, 在做行业轮动(快照会漏掉别的赛道)
        参数:
          top: verbose 打印时展示的行业数(按全程平均权重排序), series 始终返回全部31个行业。
        返回: dict{'series': DataFrame(逐日行业权重, 列=行业名, 可直接 .plot.area()),
                  'stats':  DataFrame(均值/标准差/最小/最大, 按均值降序)}
        """
        expo = self._load_exposure()
        pe = self.pos.merge(expo, on=['date', 'instrument'], how='inner')
        series = pe.groupby('date').apply(
            lambda g: pd.Series({i: (_renorm(g['w']) * g[i]).sum() for i in INDUSTRIES}),
            include_groups=False).sort_index()

        stats = pd.DataFrame({
            '均值':  series.mean(),
            '标准差': series.std(),
            '最小':  series.min(),
            '最大':  series.max(),
        }).sort_values('均值', ascending=False)

        if verbose:
            hhi = (series ** 2).sum(axis=1)   # 逐日行业赫芬达尔指数(集中度)
            print('='*60)
            print(f'【行业时序】逐日行业暴露 全程统计  ({len(series)}个持仓日)')
            print(f'  {pd.Timestamp(series.index.min()).date()} → '
                  f'{pd.Timestamp(series.index.max()).date()}   (前{top}大行业, 按全程均值)')
            print('='*60)
            print(f'  {"行业":6s} {"均值%":>7s} {"标准差":>7s} {"最小%":>7s} {"最大%":>7s}   判定')
            for name, row in stats.head(top).iterrows():
                mean, std, mx = row['均值'], row['标准差'], row['最大']
                if mean >= 0.20:
                    tag = '← 长期重仓(赛道信仰)'
                elif std >= 0.10:
                    tag = '← 波动大(行业轮动)'
                elif mean >= 0.10:
                    tag = '← 持续持有'
                else:
                    tag = ''
                print(f'  {name:6s} {mean*100:7.1f} {std*100:7.1f} '
                      f'{row["最小"]*100:7.1f} {mx*100:7.1f}   {tag}')
            print(f'\n  集中度(HHI): 均值{hhi.mean():.3f}  最高{hhi.max():.3f}  最低{hhi.min():.3f}')
            print('    · HHI≈1/N 越接近均衡; 越大越集中(单行业押注)')
            print('  >>> 均值高=赛道信仰; std高=在换赛道, exposure_snapshot() 只看最后一天会漏掉。')
        return {'series': series, 'stats': stats}

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
            lambda g: pd.Series({f: (_renorm(g['w']) * g[f]).sum() for f in STYLES + INDUSTRIES}),
            include_groups=False)

        merged = port_expo.merge(fr.set_index('expo_date'), left_index=True, right_index=True,
                                 suffixes=('_e', ''))
        contrib, avg_expo, fac_cum = {}, {}, {}
        for f in STYLES + INDUSTRIES:
            contrib[f]   = (merged[f'{f}_e'] * merged[f]).sum()   # 贡献 = Σ暴露×因子收益
            avg_expo[f]  = merged[f'{f}_e'].mean()                # 你平均押的方向/轻重
            fac_cum[f]   = merged[f].sum()                        # 因子自己这段涨跌(算术累加)
        contrib['country'] = merged['country'].sum()
        fac_cum['country'] = merged['country'].sum()

        style_c   = pd.Series({f: contrib[f] for f in STYLES}) * 100
        ind_c     = sum(contrib[i] for i in INDUSTRIES) * 100
        country_c = contrib['country'] * 100
        strat_cum = ((1 + self.ret.dropna()).prod() - 1) * 100

        def _verdict(e, fc):
            """e=平均暴露, fc=因子累计收益(pt); 拆出正负号背后的操作含义"""
            if abs(e) < 0.1 or abs(fc) < 0.3:
                return '影响小'
            if e > 0 and fc > 0: return '押对 (做多↑的因子)'
            if e > 0 and fc < 0: return '押反 (做多↓的因子,踩雷)'
            if e < 0 and fc > 0: return '踏空 (低配↑的因子)'
            return '躲对 (低配↓的因子)'

        if verbose:
            print('='*60)
            print('【归因】收益来源分解 (算术累加口径, 百分点)')
            print('='*60)
            print('  贡献 = 你的暴露方向 × 因子自己的涨跌; 看懂正负号请对照右侧解读')
            print('-'*60)
            print(f'  {"因子":6s} {"贡献pt":>7s} {"平均暴露":>7s} {"因子收益":>7s}   解读')
            # 市场β: 满仓吃/被市场, 暴露≈1
            mkt = '市场涨你在场,赚了' if country_c >= 0 else '市场跌你满仓,被套'
            print(f'  {"市场β":6s} {country_c:+7.2f} {"~满仓":>7s} '
                  f'{fac_cum["country"]*100:+7.2f}   {mkt}')
            srt = style_c.reindex(style_c.abs().sort_values(ascending=False).index)
            for f in srt.index:
                print(f'  {STYLE_CN[f]:6s} {srt[f]:+7.2f} {avg_expo[f]:+7.2f} '
                      f'{fac_cum[f]*100:+7.2f}   {_verdict(avg_expo[f], fac_cum[f]*100)}')
            print(f'  {"行业合计":6s} {ind_c:+7.2f}')
            print('-'*60)
            print(f'  策略累计收益(复利,仅参照) {strat_cum:+.2f}')
            print('\n  口径速查:')
            print('    · 贡献>0 = 这个因子帮你赚钱; <0 = 拖你后腿')
            print('    · 平均暴露>0 = 你在做多该风格; <0 = 低配/做空')
            print('    · 因子收益>0 = 该因子这段自己在涨; <0 = 自己在跌')
            print('    · 押对/躲对 → 赚 (贡献+);  押反/踏空 → 亏 (贡献-)')
            print('\n  ⚠ 算术累加口径, 不能直接和复利总收益相减求alpha。')
            print('  ⚠ 满仓小盘却见 size≈0, 是钱被流动性/波动/行业分走了 —— 用 alpha_curve() 看真本事。')

        out = pd.DataFrame({
            '累计贡献pt': {'国家(市场β)': country_c,
                        **{STYLE_CN[f]: style_c[f] for f in STYLES}, '行业合计': ind_c},
            '平均暴露':  {'国家(市场β)': np.nan,
                        **{STYLE_CN[f]: avg_expo[f] for f in STYLES}, '行业合计': np.nan},
            '因子收益pt': {'国家(市场β)': fac_cum['country']*100,
                        **{STYLE_CN[f]: fac_cum[f]*100 for f in STYLES}, '行业合计': np.nan},
        })
        return out

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
        sr = self.db.query(q, filters={'expo_date': (str(self.start.date()), str(self.end.date()))}).df()
        sr['date'] = pd.to_datetime(sr['date'])

        m = insts_dates.merge(sr, on=['date', 'instrument'], how='inner')
        daily_spec = m.groupby('date').apply(lambda g: (_renorm(g['w']) * g['u']).sum(),
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

