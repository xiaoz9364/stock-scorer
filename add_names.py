"""
给候选池 CSV 补上股票名称
"""
import akshare as ak
import pandas as pd

# 读取刚才的候选池
df = pd.read_csv('候选池_20260515.csv', dtype={'代码': str})

# 获取全A股名称映射
stock_info = ak.stock_info_a_code_name()
name_map = dict(zip(stock_info['code'], stock_info['name']))

# 补上名称
df['名称'] = df['代码'].map(name_map)

# 调整列顺序
df = df[['代码', '名称', '总分']]

# 保存
df.to_csv('候选池_20260515_带名称.csv', index=False, encoding='utf-8-sig')
print(df.head(20))
print(f"共 {len(df)} 行，已保存至 候选池_20260515_带名称.csv")