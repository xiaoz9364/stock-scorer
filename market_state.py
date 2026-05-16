"""
market_state.py - 大盘状态判断
"""

import baostock as bs
import pandas as pd
from datetime import datetime, timedelta


def get_market_state():
    bs.login()
    try:
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=200)).strftime('%Y-%m-%d')
        rs = bs.query_history_k_data_plus(
            "sh.000001", "date,close,volume",
            start_date=start, end_date=end, frequency="d", adjustflag="2"
        )
        if rs.error_code != '0':
            bs.logout()
            return "未知", "数据获取失败"
        data = []
        while (rs.error_code == '0') & rs.next():
            data.append(rs.get_row_data())
        bs.logout()
        if len(data) < 60:
            return "未知", "数据不足"
        
        df = pd.DataFrame(data, columns=['date','close','volume'])
        df['close'] = pd.to_numeric(df['close'])
        df['volume'] = pd.to_numeric(df['volume'])
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma60'] = df['close'].rolling(60).mean()
        last = df.iloc[-1]
        
        above_ma60 = last['close'] > last['ma60']
        ma20_up = df['ma20'].iloc[-1] > df['ma20'].iloc[-5]
        vol_strong = df['volume'].tail(5).mean() > df['volume'].tail(20).mean()
        
        if above_ma60 and ma20_up and vol_strong:
            state = "主升期"
        elif not above_ma60 and not ma20_up:
            state = "退潮期"
        elif abs(last['close'] / last['ma60'] - 1) < 0.03:
            state = "震荡期"
        else:
            state = "混沌期"
        
        return state, f"指数{last['close']:.0f}，60日线{last['ma60']:.0f}"
    except:
        try: bs.logout()
        except: pass
        return "未知", "判断失败"


if __name__ == "__main__":
    s, d = get_market_state()
    print(f"当前市场：{s}（{d}）")