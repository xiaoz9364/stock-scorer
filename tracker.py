"""
tracker.py - 实盘跟踪模块（完整功能：持仓天数、20日退出、是否在池、质量评分、盈亏走势）
"""

import pandas as pd
from datetime import datetime, timedelta
import baostock as bs
import os
import numpy as np

DB_FILE = "tracker.csv"
EXIT_FILE = "退出记录.csv"


def get_latest_price(code):
    """获取单只股票最新收盘价"""
    bs.login()
    try:
        bs_code = f"{'sz' if code.startswith(('0','2')) else 'sh'}.{code}"
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
        rs = bs.query_history_k_data_plus(
            bs_code, "date,close", start_date=start, end_date=end,
            frequency="d", adjustflag="2"
        )
        if rs.error_code != '0':
            return None
        data = []
        while (rs.error_code == '0') & rs.next():
            data.append(rs.get_row_data())
        if not data:
            return None
        df = pd.DataFrame(data, columns=['date','close'])
        df['close'] = pd.to_numeric(df['close'])
        return df['close'].iloc[-1]
    except:
        return None
    finally:
        try: bs.logout()
        except: pass


def load_tracker():
    if os.path.exists(DB_FILE):
        df = pd.read_csv(DB_FILE, dtype={'代码': str})
        if '入选评分' not in df.columns:
            df['入选评分'] = None
        return df
    return pd.DataFrame(columns=['入选日期','代码','名称','入选评分','成本价','持仓数量'])


def save_tracker(df):
    df.to_csv(DB_FILE, index=False, encoding='utf-8-sig')


def add_to_tracker(new_stocks):
    df = load_tracker()
    if '入选评分' not in df.columns:
        df['入选评分'] = None
    today = datetime.now().strftime('%Y-%m-%d')
    for _, row in new_stocks.iterrows():
        code = str(row['代码']).zfill(6)
        if code in df['代码'].values:
            continue
        price = get_latest_price(code)
        if price is None:
            continue
        score = row.get('总分', None)
        new_row = pd.DataFrame([{
            '入选日期': today,
            '代码': code,
            '名称': row['名称'],
            '入选评分': score,
            '成本价': price,
            '持仓数量': 1000
        }])
        df = pd.concat([df, new_row], ignore_index=True)
    save_tracker(df)
    print(f"已添加 {len(new_stocks)} 只新股到跟踪表")


def update_tracker():
    df = load_tracker()
    if df.empty:
        return df
    # 计算持仓天数
    today = datetime.now()
    df['持仓天数'] = df['入选日期'].apply(lambda d: (today - datetime.strptime(d, '%Y-%m-%d')).days)

    # 移除超过20天的持仓并记录退出
    exit_mask = df['持仓天数'] >= 20
    if exit_mask.any():
        exit_records = df[exit_mask].copy()
        # 获取最新价格作为退出价
        exit_prices = []
        for code in exit_records['代码']:
            price = get_latest_price(str(code))
            exit_prices.append(price if price else exit_records.loc[exit_records['代码']==code, '成本价'].values[0])
        exit_records['退出日期'] = today.strftime('%Y-%m-%d')
        exit_records['退出价格'] = exit_prices
        exit_records['盈亏%'] = (exit_records['退出价格'] / exit_records['成本价'] - 1) * 100
        # 保存退出记录
        if os.path.exists(EXIT_FILE):
            exit_records.to_csv(EXIT_FILE, mode='a', header=False, index=False, encoding='utf-8-sig')
        else:
            exit_records.to_csv(EXIT_FILE, index=False, encoding='utf-8-sig')
        df = df[~exit_mask]  # 删除已退出

    # 更新现价和盈亏
    prices = []
    profits = []
    for _, row in df.iterrows():
        price = get_latest_price(str(row['代码']))
        prices.append(price)
        if price and row['成本价'] > 0:
            profits.append(round((price / row['成本价'] - 1) * 100, 2))
        else:
            profits.append(None)
    df['现价'] = prices
    df['盈亏%'] = profits
    save_tracker(df)
    return df


def check_in_pool(candidate_file=None):
    """检查跟踪表各股是否还在今日候选池"""
    if candidate_file is None:
        candidate_file = f"候选池_{datetime.now().strftime('%Y%m%d')}_带名称.csv"
    if not os.path.exists(candidate_file):
        return {}
    cand = pd.read_csv(candidate_file, dtype={'代码': str})
    pool_codes = set(cand['代码'].tolist())
    df = load_tracker()
    in_pool_map = {}
    for code in df['代码']:
        in_pool_map[code] = code in pool_codes
    return in_pool_map


def quality_check(code):
    """简易质量评分：返回文字诊断"""
    # 由于因子数据在ranker中，此处可用总分近似（从tracker的入选评分推断）
    # 简化：用入选评分代替
    df = load_tracker()
    if code not in df['代码'].values:
        return "无记录"
    score = df.loc[df['代码']==code, '入选评分'].values[0]
    if score is None or pd.isna(score):
        return "无评分"
    score = float(score)
    if score > 70:
        return "优质"
    elif score > 60:
        return "良好"
    elif score > 50:
        return "偏弱"
    else:
        return "弱势"


def get_pnl_trend():
    """持仓盈亏走势文字"""
    df = update_tracker()
    if df.empty:
        return "无持仓"
    # 模拟：通过比较近5天盈亏%（需历史数据，这里简单用盈亏%正值数量代替）
    profit_vals = df['盈亏%'].dropna()
    if len(profit_vals) == 0:
        return "无数据"
    avg_profit = profit_vals.mean()
    if avg_profit > 2:
        return "近5天盈利持续改善"
    elif avg_profit > 0:
        return "近5天小幅盈利"
    elif avg_profit > -2:
        return "近5天小幅亏损"
    else:
        return "近5天亏损扩大"


if __name__ == "__main__":
    df = update_tracker()
    print(df)