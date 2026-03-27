import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.data import Data
from xxybacktest.context import DictObj

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


def setup_module():
    Data.init_db(DATA_PATH)

setup_module()
print(Data.get_index_daily('000300.SH', '2020-01-01', '2020-02-02'))