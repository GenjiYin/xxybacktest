"""
模拟交易服务启动入口（项目根目录快捷脚本）

用法:
    conda activate vnpy
    python run_simulation.py [--data PATH] [--data-renew PATH] [--time HH:MM:SS]

安装后也可直接使用命令:
    xxy-sim [--data PATH] [--data-renew PATH] [--time HH:MM:SS]
"""

from xxybacktest.simulation.main import main

if __name__ == "__main__":
    main()
