"""
test_get_price.py — 验证 get_price 冷启动兜底（主动订阅 + 短轮询等待）

背景：
    非持仓/未订阅标的首次 get_full_tick 取不到 tick，被动等访问触发订阅会出现
    「头几次返 None、再跑才有价」。trader.get_price 已加：取不到 → subscribe_quote
    → 每 0.13s 轮询、最多 15 次（约 2 秒）等首个 tick。

用法（QMT 客户端需已登录、已装 xtquant）：
    # demo1：裸调 xtdata，验证 get_price 的核心逻辑（不需要资金账号）
    python scripts/test_get_price.py
    python scripts/test_get_price.py 159915.SZ 513100.SH

    # demo2：走完整 QMTTrader.get_price（需要 qmt_path + 资金账号）
    python scripts/test_get_price.py --trader --qmt "D:/QMT/userdata_mini" --acc 12345678 159915.SZ
"""

import sys
import time
import argparse


# 默认测试标的：159915.SZ（创业板，宽基 ETF，典型冷标的）
DEFAULT_CODES = ["600854.SH"]


def demo1_bare_xtdata(codes):
    """裸调 xtdata，复刻 trader.get_price 的冷启动兜底逻辑。"""
    from xtquant import xtdata

    def get_price(code):
        t0 = time.time()
        ticks = xtdata.get_full_tick([code])
        price = float(ticks[code].get("lastPrice", 0)) if (ticks and code in ticks) else 0.0
        first_hit = price > 0
        rounds = 0

        if price <= 0:
            # 冷缓存兜底
            xtdata.subscribe_quote(code, period="tick")
            for i in range(15):
                rounds = i + 1
                time.sleep(0.13)
                ticks = xtdata.get_full_tick([code])
                if ticks and code in ticks:
                    price = float(ticks[code].get("lastPrice", 0))
                    if price > 0:
                        break

        elapsed = time.time() - t0
        return (price if price > 0 else None), first_hit, rounds, elapsed

    print("=" * 64)
    print("demo1：裸调 xtdata（get_price 核心逻辑）")
    print("=" * 64)
    for code in codes:
        price, first_hit, rounds, elapsed = get_price(code)
        if price is None:
            print(f"[{code}] ✗ None（等满 {rounds} 轮仍无价 → 真停牌/无行情）  耗时 {elapsed:.2f}s")
        elif first_hit:
            print(f"[{code}] ✓ {price}  （热缓存，首次命中，零等待）  耗时 {elapsed:.2f}s")
        else:
            print(f"[{code}] ✓ {price}  （冷缓存，订阅后第 {rounds} 轮命中）  耗时 {elapsed:.2f}s")


def demo2_via_trader(codes, qmt_path, acc):
    """走完整 QMTTrader.get_price，验证真实调用路径。"""
    from xxybacktest.live.trader import QMTTrader

    print("=" * 64)
    print("demo2：QMTTrader.get_price（完整路径）")
    print("=" * 64)
    print(f"连接 QMT: {qmt_path}  账号: {acc}")
    trader = QMTTrader(qmt_path, acc)
    try:
        for code in codes:
            t0 = time.time()
            price = trader.get_price(code)
            elapsed = time.time() - t0
            flag = "✓" if price is not None else "✗"
            print(f"[{code}] {flag} {price}   耗时 {elapsed:.2f}s")
    finally:
        try:
            trader.disconnect()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("codes", nargs="*", default=DEFAULT_CODES,
                        help="标的代码，如 159915.SZ 513100.SH（默认 159915.SZ）")
    parser.add_argument("--trader", action="store_true",
                        help="走完整 QMTTrader.get_price（需 --qmt 和 --acc）")
    parser.add_argument("--qmt", default="", help="QMT 客户端目录")
    parser.add_argument("--acc", default="", help="QMT 资金账号")
    args = parser.parse_args()

    codes = args.codes or DEFAULT_CODES

    if args.trader:
        if not args.qmt or not args.acc:
            print("[错误] --trader 模式需要同时提供 --qmt 和 --acc")
            sys.exit(1)
        demo2_via_trader(codes, args.qmt, args.acc)
    else:
        demo1_bare_xtdata(codes)


if __name__ == "__main__":
    main()
