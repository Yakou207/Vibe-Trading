"""The official Shenwan (SWS 2021) stock classification file.

cninfo has no Shenwan record for a few old stocks (000002, 000651, 600795, ...); the official
file covers every listed stock with dated industry codes.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fintech_quant.data.symbols import normalize_a_share_symbol

SHENWAN_FILE_URL = "https://www.swsresearch.com/swindex/pdf/SwClass2021/StockClassifyUse_stock.xls"
# Level-1 name by the first two digits of a Shenwan code, as cninfo names it. Checked on 2026-11-04
# against every cached cninfo row that shares a symbol and date with the official file: each code
# matched exactly one name. 76 (环保) is in the 2021 standard but had no matched row.
SHENWAN_LEVEL1 = {
    "11": "农林牧渔", "22": "基础化工", "23": "钢铁", "24": "有色金属", "27": "电子", "28": "汽车",
    "31": "国防军工", "33": "家用电器", "34": "食品饮料", "35": "纺织服饰", "36": "轻工制造",
    "37": "医药生物", "41": "公用事业", "42": "交通运输", "43": "房地产", "44": "非银金融",
    "45": "商贸零售", "46": "社会服务", "48": "银行", "49": "非银金融", "51": "综合",
    "61": "建筑材料", "62": "建筑装饰", "63": "电力设备", "64": "机械设备", "65": "国防军工",
    "71": "计算机", "72": "传媒", "73": "通信", "74": "煤炭", "75": "石油石化", "76": "环保",
    "77": "美容护理",
}


def read_official_shenwan(path: Path) -> dict[str, list[tuple[str, str]]]:
    """{symbol: [(inclusion date, level-1 name), ...]} in file order."""
    import pandas as pd

    frame = pd.read_excel(path, dtype=str)
    history: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for code, day, industry in zip(frame["股票代码"], frame["计入日期"], frame["行业代码"]):
        name = SHENWAN_LEVEL1.get(str(industry)[:2])
        if name:
            history[normalize_a_share_symbol(str(code))].append((str(day)[:10], name))
    return dict(history)
