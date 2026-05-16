"""
stock_filter.py - 股票池过滤 + 初筛门槛（优化版：一次取120天数据，复用至打分）
过滤：创业板/科创板/北交所/ST/A+H（固定规则）
初筛：成交额、价格、短期趋势
"""

import akshare as ak
import baostock as bs
import pandas as pd
from datetime import datetime, timedelta


def get_filtered_codes():
    """获取过滤后的主板股票代码列表"""
    print("正在获取A股列表...")
    stock_info = ak.stock_info_a_code_name()
    codes = []
    for _, row in stock_info.iterrows():
        code = row['code']
        name = row['name']
        if code.startswith(('300', '301')):
            continue
        if code.startswith(('688', '689')):
            continue
        if code.startswith('8'):
            continue
        if 'ST' in name:
            continue
        if 'H' in name:
            continue
        codes.append(code)
    print(f"过滤后股票数量：{len(codes)}")
    return codes


def initial_screen_and_fetch(codes):
    """
    初筛：一次请求120天数据，用近20天判断，通过者保留全部数据
    返回：通过初筛的 {code: DataFrame} 字典
    """
    print("正在进行初筛并获取完整数据...")
    bs.login()
    passed = {}
    total = len(codes)

    for i, code in enumerate(codes):
        if (i + 1) % 200 == 0:
            print(f"  初筛进度：{i+1}/{total}")

        try:
            bs_code = f"{'sz' if code.startswith(('0','2')) else 'sh'}.{code}"
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=240)).strftime('%Y-%m-%d')
            rs = bs.query_history_k_data_plus(
                bs_code, "date,open,high,low,close,volume,amount",
                start_date=start_date, end_date=end_date,
                frequency="d", adjustflag="2"
            )
            if rs.error_code != '0':
                continue

            data = []
            while (rs.error_code == '0') & rs.next():
                data.append(rs.get_row_data())
            if len(data) < 120:
                continue

            df = pd.DataFrame(data, columns=['date','open','high','low','close','volume','amount'])
            for col in ['open','high','low','close','volume','amount']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)

            # 取最近120天（用于打分），最近20天用于初筛
            df_full = df.tail(120).copy()
            if len(df_full) < 60:
                continue
            df_recent = df_full.tail(20)

            # 条件1：近20日均成交额 >= 5000万
            avg_amount = df_recent['amount'].mean()
            if avg_amount < 50000000:
                continue

            # 条件2：价格 3~300
            close = df_recent['close'].iloc[-1]
            if close < 3 or close > 300:
                continue

            # 条件3：近5日涨幅 > -10% 且 收盘价 > 20日均线
            if len(df_recent) >= 20:
                ma20 = df_recent['close'].rolling(20).mean().iloc[-1]
                pct_5d = df_recent['close'].iloc[-1] / df_recent['close'].iloc[-6] - 1
                if pct_5d > -0.10 and close > ma20:
                    passed[code] = df_full  # 保存完整120天数据
        except:
            continue

    bs.logout()
    print(f"初筛通过数量：{len(passed)}")
    return passed