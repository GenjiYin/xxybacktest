#!/usr/bin/env python3
"""
清理 live_schedule.json 中的残留记录。
只删除数据库中已不存在的账户，保留有效账户。
"""

import json
import os
import shutil
import sys

DATA_PATH = sys.argv[1] if len(sys.argv) > 1 else r"D:\Desktop\最新回测框架\data"


def main():
    from xxybacktest.simulation.submitter import list_accounts

    valid_ids = {a["account_id"] for a in list_accounts(data_path=DATA_PATH)}
    print(f"[信息] 数据库中有效账户: {len(valid_ids)} 个")

    schedule_path = os.path.join(DATA_PATH, "live", "live_schedule.json")
    if not os.path.exists(schedule_path):
        print("[信息] live_schedule.json 不存在，无需清理")
        return

    with open(schedule_path, "r", encoding="utf-8") as f:
        schedule = json.load(f)

    print(f"[信息] live_schedule.json 共 {len(schedule)} 条记录")

    residual = [k for k in schedule if k not in valid_ids]
    if not residual:
        print("[信息] 无残留，一切正常")
        return

    print(f"\n[信息] 发现 {len(residual)} 条残留，开始清理...")
    for k in residual:
        print(f"  ✗ {k}")

    # 清理
    for k in residual:
        del schedule[k]

        # 清理目录和日志
        live_account_dir = os.path.join(DATA_PATH, "live", "accounts", k)
        if os.path.exists(live_account_dir):
            shutil.rmtree(live_account_dir)
            print(f"  [清理] 删除目录 {live_account_dir}")

        log_dir = os.path.join(DATA_PATH, "simulation_results", "task_logs")
        task_id = f"live_{k}"
        for ext in [".log", ".status"]:
            f = os.path.join(log_dir, f"{task_id}{ext}")
            if os.path.exists(f):
                os.remove(f)
                print(f"  [清理] 删除日志 {f}")
        h = os.path.join(log_dir, "history", task_id)
        if os.path.exists(h):
            shutil.rmtree(h)
            print(f"  [清理] 删除历史日志 {h}")

    with open(schedule_path, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)

    print(f"\n[完成] 已清理 {len(residual)} 条残留")
    print(f"[保留] {len(schedule)} 条有效记录")


if __name__ == "__main__":
    main()
