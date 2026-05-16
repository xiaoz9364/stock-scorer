"""
ranker.py - 百分位排名 + 总分合成 + 多进程加速 + 输出候选池
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import baostock as bs
import multiprocessing
from functools import partial

from stock_filter import get_filtered_codes, initial_screen_and_fetch
from factors import calc_all_factors


def compute_factors_for_batch(codes_data):
    """子进程任务：计算一批股票的因子"""
    batch_results = []
    for code, df in codes_data.items():
        if df is None:
            continue
        # 确保均线已计算
        if 'ma5' not in df.columns:
            df['ma5'] = df['close'].rolling(5).mean()
            df['ma10'] = df['close'].rolling(10).mean()
            df['ma20'] = df['close'].rolling(20).mean()
            df['ma60'] = df['close'].rolling(60).mean()
        factors = calc_all_factors(code, df)
        if factors:
            factors['code'] = code
            batch_results.append(factors)
    return batch_results


def get_industry_map(codes):
    """批量获取股票行业"""
    industry_map = {}
    bs.login()
    for code in codes:
        try:
            bs_code = f"{'sz' if code.startswith(('0','2')) else 'sh'}.{code}"
            rs = bs.query_stock_industry(bs_code)
            if rs.error_code == '0':
                while rs.next():
                    row = rs.get_row_data()
                    ind = row[2] if len(row) > 2 and row[2] else row[1]
                    industry_map[code] = ind
                    break
        except:
            pass
    bs.logout()
    return industry_map


def calc_sector_stats(codes_data, industry_map):
    """计算行业近10日平均涨幅"""
    sector_rets = {}
    sector_counts = {}
    for code, df in codes_data.items():
        ind = industry_map.get(code, '未知')
        if len(df) >= 21:
            ret = df['close'].iloc[-1] / df['close'].iloc[-11] - 1
            sector_rets[ind] = sector_rets.get(ind, 0) + ret
            sector_counts[ind] = sector_counts.get(ind, 0) + 1
    for ind in sector_rets:
        sector_rets[ind] /= sector_counts[ind]
    return sector_rets


def calc_sector_duration(codes_data, industry_map):
    """计算板块连涨天数"""
    sector_daily = {}
    for code, df in codes_data.items():
        ind = industry_map.get(code, '未知')
        if len(df) >= 20:
            daily_ret = df['close'].pct_change().tail(10)
            if ind not in sector_daily:
                sector_daily[ind] = []
            sector_daily[ind].append(daily_ret.values)
    sector_dur = {}
    for ind, rets in sector_daily.items():
        avg = np.nanmean(np.array(rets), axis=0)
        streak = 0
        for r in reversed(avg):
            if r > 0:
                streak += 1
            else:
                break
        sector_dur[ind] = streak
    return sector_dur


def run_ranking():
    print("开始运行评分系统（多进程加速）...")

    # 1. 获取过滤代码，然后一次性初筛+获取数据
    codes = get_filtered_codes()
    data_dict = initial_screen_and_fetch(codes)
    pool_codes = list(data_dict.keys())
    print(f"进入打分池：{len(pool_codes)} 只")

    if not pool_codes:
        print("无通过初筛股票。")
        return

    # 2. 多进程计算因子
    n_processes = min(4, multiprocessing.cpu_count())
    print(f"启动 {n_processes} 个进程并行计算因子...")
    code_list = list(data_dict.keys())
    batch_size = len(code_list) // n_processes + 1
    batches = []
    for i in range(n_processes):
        batch_codes = code_list[i*batch_size : (i+1)*batch_size]
        batch_data = {c: data_dict[c] for c in batch_codes if c in data_dict}
        batches.append(batch_data)

    with multiprocessing.Pool(processes=n_processes) as pool:
        results_list = pool.map(compute_factors_for_batch, batches)

    all_factors = []
    for batch in results_list:
        all_factors.extend(batch)

    print(f"因子计算完成，共 {len(all_factors)} 只股票。")

    if not all_factors:
        print("没有计算出任何因子，终止。")
        return

    # 3. 行业数据
    industry_map = get_industry_map(pool_codes)
    sector_ret = calc_sector_stats(data_dict, industry_map)
    sector_dur = calc_sector_duration(data_dict, industry_map)

    df_all = pd.DataFrame(all_factors)
    # 覆盖板块因子
    for idx, row in df_all.iterrows():
        code = row['code']
        ind = industry_map.get(code, '未知')
        df_all.at[idx, 'sector_rank'] = sector_ret.get(ind, 0)
        df_all.at[idx, 'sector_duration'] = sector_dur.get(ind, 0) / 10
        stock_ret = row['ret_20d']
        df_all.at[idx, 'stock_vs_sector'] = stock_ret - sector_ret.get(ind, 0)

    # 4. 百分位排名
    pos_factors = [
        'ma_rank', 'ret_20d', 'ret_60d', 'dist_to_high', 'ma10_slope',
        'vol_ratio', 'up_vol_pct', 'amount_ratio', 'vol_stability',
        'corr_price_vol', 'sector_rank', 'sector_duration', 'stock_vs_sector',
        'avg_amount', 'recovery_ratio'
    ]
    neg_factors = ['bias', 'max_drawdown', 'volatility', 'vol_ratio', 'abnormal_down']

    for col in pos_factors:
        if col in df_all.columns:
            df_all[col + '_rank'] = df_all[col].rank(pct=True) * 100
    for col in neg_factors:
        if col in df_all.columns:
            df_all[col + '_rank'] = (-df_all[col]).rank(pct=True) * 100

    # 5. 四大类合成
    trend_cols = ['ma_rank', 'ret_20d', 'ret_60d', 'dist_to_high', 'ma10_slope', 'bias']
    fund_cols = ['vol_ratio', 'up_vol_pct', 'amount_ratio', 'vol_stability', 'corr_price_vol']
    sector_cols = ['sector_rank', 'sector_duration', 'stock_vs_sector']
    risk_cols = ['max_drawdown', 'volatility', 'vol_ratio', 'abnormal_down', 'avg_amount', 'recovery_ratio']

    df_all['trend_score'] = df_all[[c+'_rank' for c in trend_cols if c+'_rank' in df_all.columns]].mean(axis=1)
    df_all['fund_score'] = df_all[[c+'_rank' for c in fund_cols if c+'_rank' in df_all.columns]].mean(axis=1)
    df_all['sector_score'] = df_all[[c+'_rank' for c in sector_cols if c+'_rank' in df_all.columns]].mean(axis=1)
    df_all['risk_score'] = df_all[[c+'_rank' for c in risk_cols if c+'_rank' in df_all.columns]].mean(axis=1)

    df_all['total_score'] = (df_all['trend_score'] + df_all['fund_score'] +
                             df_all['sector_score'] + df_all['risk_score']) / 4

    # 6. 前100名
    top100 = df_all.sort_values('total_score', ascending=False).head(100)
    result = top100[['code', 'total_score']].copy()
    result.columns = ['代码', '总分']

    # 添加名称
    import akshare as ak
    stock_info = ak.stock_info_a_code_name()
    name_map = dict(zip(stock_info['code'], stock_info['name']))
    result['名称'] = result['代码'].map(name_map)

    today_str = datetime.now().strftime('%Y%m%d')
    # 创建历史记录文件夹（若不存在）
    import os
    os.makedirs('历史记录', exist_ok=True)
    filename = f'候选池_{today_str}.csv'
    filepath = os.path.join('历史记录', filename)
    result.to_csv(filepath, index=False, encoding='utf-8-sig')
    print(f"候选池已保存至 {filepath}")

    # 同时保存带名称版本（方便查看）
    result.to_csv(f'候选池_{today_str}_带名称.csv', index=False, encoding='utf-8-sig')

    return result


if __name__ == "__main__":
    run_ranking()