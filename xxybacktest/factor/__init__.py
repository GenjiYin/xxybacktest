"""
================================================================================
factor —— 因子分析模块
================================================================================
一条 SQL 查出因子值, 系统自动算 IC / ICIR / 分组收益 / 多空曲线等绩效。

两种用法, 共用同一个计算引擎(engine.py), 口径永远一致:

  ① 即时分析(notebook 探索, 不落盘)
      from xxybacktest.factor import analyze_factor
      res = analyze_factor(sql="...", data_path=r"D:\\...\\data")
      res.summary(); res.plot_groups()

  ② 提交入库(纳入每日监控看板, 由 run_all 每天重跑落盘)
      from xxybacktest.factor import submit_factor, run_all
      fid = submit_factor(name="EP因子", sql="...", category="价值")
      run_all(data_path=r"D:\\...\\data")   # 定时任务调用, 刷新前端

设计边界(见 建设方案.md):
  - 因子值来源: 用户 SQL, 必须返回 date / instrument / value 三列
  - 收益口径:   次日开盘 + 后复权  (open×adj)(T+1+N)/(open×adj)(T+1) - 1
  - 系统只做:   可交易过滤(停牌/ST/涨跌停) + 算收益 + 算 IC/分组
  - 交给用户:   股票池筛选、中性化(在 SQL 里自理)
  - 数据依赖:   daily_bar + stock_status 两张表
================================================================================
"""
from .engine import analyze, analyze_from_sql
from .api import analyze_factor
from .result import FactorResult
from .submitter import (submit_factor, list_factors, get_factor,
                        update_factor, delete_factor)
from .runner import run_single, run_all

__all__ = [
    "analyze_factor", "analyze", "analyze_from_sql", "FactorResult",
    "submit_factor", "list_factors", "get_factor", "update_factor",
    "delete_factor", "run_single", "run_all",
]
