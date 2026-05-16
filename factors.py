"""
factors.py - 20个因子原始值计算（增加重连重试机制）
"""

import baostock as bs
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def get_daily_data(code, days=120):
    """获取单只股票日线数据（含均线），失败自动重连重试一次"""
    bs_code = f"{'sz' if code.startswith(('0','2')) else 'sh'}.{code}"
    
    for attempt in range(2):  # 最多尝试两次
        try:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=days*2)).strftime('%Y-%m-%d')
            rs = bs.query_history_k_data_plus(
                bs_code, "date,open,high,low,close,volume,amount",
                start_date=start_date, end_date=end_date,
                frequency="d", adjustflag="2"
            )
            if rs.error_code != '0':
                if attempt == 0:
                    # 重连
                    try:
                        bs.logout()
                    except:
                        pass
                    bs.login()
                    continue
                return None
            
            data = []
            while (rs.error_code == '0') & rs.next():
                data.append(rs.get_row_data())
            if len(data) < 60:
                return None
            
            df = pd.DataFrame(data, columns=['date','open','high','low','close','volume','amount'])
            for col in ['open','high','low','close','volume','amount']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True).tail(days).copy()
            
            if len(df) < 60:
                return None
            
            df['ma5'] = df['close'].rolling(5).mean()
            df['ma10'] = df['close'].rolling(10).mean()
            df['ma20'] = df['close'].rolling(20).mean()
            df['ma60'] = df['close'].rolling(60).mean()
            return df
            
        except Exception as e:
            if attempt == 0:
                try:
                    bs.logout()
                except:
                    pass
                bs.login()
                continue
            else:
                return None
    return None


def calc_all_factors(code, df):
    """计算全部20个因子，返回字典"""
    if df is None or len(df) < 60:
        return None
    
    close = df['close']
    volume = df['volume']
    amount = df['amount']
    high = df['high']
    low = df['low']
    
    factors = {}
    
    # ===== 趋势动量（6个） =====
    last = df.iloc[-1]
    ma_score = 0
    if last['ma5'] > last['ma10']: ma_score += 1
    if last['ma10'] > last['ma20']: ma_score += 1
    if last['ma20'] > last['ma60']: ma_score += 1
    factors['ma_rank'] = ma_score / 3
    
    factors['ret_20d'] = close.iloc[-1] / close.iloc[-21] - 1
    factors['ret_60d'] = close.iloc[-1] / close.iloc[-61] - 1
    
    high_60 = high.tail(60).max()
    factors['dist_to_high'] = (close.iloc[-1] / high_60 - 1)
    
    ma10 = df['ma10'].dropna()
    if len(ma10) >= 10:
        factors['ma10_slope'] = (ma10.iloc[-1] / ma10.iloc[-10] - 1)
    else:
        factors['ma10_slope'] = 0
    
    factors['bias'] = (last['close'] / last['ma20'] - 1)
    
    # ===== 资金强度（5个） =====
    vol_ma5 = volume.rolling(5).mean().iloc[-1]
    vol_ma20 = volume.rolling(20).mean().iloc[-1]
    factors['vol_ratio'] = vol_ma5 / vol_ma20 if vol_ma20 > 0 else 1
    
    up_days = close.pct_change() > 0
    vol_up = volume > volume.rolling(20).mean()
    up_and_vol = (up_days & vol_up).tail(10).sum()
    factors['up_vol_pct'] = up_and_vol / 10
    
    amount_ma5 = amount.rolling(5).mean().iloc[-1]
    amount_ma20 = amount.rolling(20).mean().iloc[-1]
    factors['amount_ratio'] = amount_ma5 / amount_ma20 if amount_ma20 > 0 else 1
    
    vol_cv = volume.tail(10).std() / volume.tail(10).mean() if volume.tail(10).mean() > 0 else 1
    factors['vol_stability'] = 1 - vol_cv
    
    ret_10 = close.pct_change().tail(10)
    vol_10 = volume.tail(10)
    if len(ret_10.dropna()) >= 5:
        corr = ret_10.corr(vol_10)
        factors['corr_price_vol'] = corr if pd.notna(corr) else 0
    else:
        factors['corr_price_vol'] = 0
    
    # ===== 板块动量（占位） =====
    factors['sector_rank'] = 0.5
    factors['sector_duration'] = 0.5
    factors['stock_vs_sector'] = 0.5
    
    # ===== 质量/风险（6个） =====
    peak = close.rolling(20).max()
    factors['max_drawdown'] = (close / peak - 1).min()
    
    factors['volatility'] = close.pct_change().tail(20).std()
    
    vol_10d = close.pct_change().tail(10).std()
    vol_60d = close.pct_change().tail(60).std()
    factors['vol_ratio'] = vol_10d / vol_60d if vol_60d > 0 else 1
    
    factors['abnormal_down'] = ((close.pct_change() < -0.05) & (volume > volume.rolling(20).mean() * 1.5)).tail(20).sum()
    
    factors['avg_amount'] = amount.tail(20).mean()
    
    max_high = high.cummax()
    factors['recovery_ratio'] = close.iloc[-1] / max_high.iloc[-1] if max_high.iloc[-1] > 0 else 1
    
    return factors


if __name__ == "__main__":
    bs.login()
    code = '000001'
    df = get_daily_data(code)
    if df is not None:
        f = calc_all_factors(code, df)
        for k, v in f.items():
            if isinstance(v, float):
                print(f"{k}: {v:.4f}")
            else:
                print(f"{k}: {v}")
    else:
        print("数据获取失败")
    bs.logout()