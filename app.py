"""
A股趋势评分系统 - 手机版
"""

import streamlit as st
import pandas as pd
import os
from datetime import datetime
import ranker
import tracker
import market_state

# PWA 配置
st.set_page_config(page_title="A股趋势评分", page_icon="📈", layout="wide")

st.markdown("""
<link rel="manifest" href="/static/manifest.json">
<script>
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/static/sw.js');
}
</script>
""", unsafe_allow_html=True)

st.title("📈 A股趋势评分系统")

# 侧边栏
with st.sidebar:
    state, desc = market_state.get_market_state()
    st.metric("当前市场", state)
    st.caption(desc)
    st.divider()
    st.subheader("自定义打分")
    custom_codes = st.text_input("输入股票代码（逗号分隔）")
    custom_btn = st.button("⚡ 给这些股打分")

# 主区域
col1, col2 = st.columns(2)

with col1:
    st.subheader("🚀 全市场扫描")
    if st.button("开始扫描", use_container_width=True):
        with st.spinner("正在扫描全市场..."):
            ranker.run_ranking()
            tracker.update_tracker()
        st.success("扫描完成！")
        st.rerun()

with col2:
    st.subheader("📤 导出数据")
    today_str = datetime.now().strftime('%Y%m%d')
    cand_file = f'候选池_{today_str}_带名称.csv'
    if os.path.exists(cand_file):
        df_download = pd.read_csv(cand_file, dtype={'代码': str})
        csv = df_download.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button("下载候选池CSV", csv, f"候选池_{today_str}.csv", use_container_width=True)

# 候选池
st.header("今日候选池 TOP100")
today_str = datetime.now().strftime('%Y%m%d')
cand_file = f'候选池_{today_str}_带名称.csv'

if os.path.exists(cand_file):
    df_cand = pd.read_csv(cand_file, dtype={'代码': str})
    st.dataframe(df_cand, use_container_width=True, hide_index=True)
else:
    st.info("暂无今日候选池，请点击“开始扫描”")

# 实盘跟踪
st.header("实盘跟踪")
df_track = tracker.load_tracker()
if not df_track.empty:
    df_track['入选日期'] = df_track['入选日期'].astype(str).str[5:]
    st.dataframe(df_track, use_container_width=True, hide_index=True)
    total_val = (df_track['现价'].fillna(df_track['成本价']) * 1000).sum()
    total_cost = (df_track['成本价'] * 1000).sum()
    profit = total_val - total_cost
    profit_pct = (profit / total_cost * 100) if total_cost else 0
    st.metric("跟踪总市值", f"¥{total_val:,.0f}", delta=f"盈亏 ¥{profit:,.0f} ({profit_pct:+.2f}%)")
else:
    st.info("暂无跟踪持仓")

# 自定义打分
if custom_btn and custom_codes:
    codes = [c.strip() for c in custom_codes.split(',') if c.strip()]
    st.info("自定义打分功能开发中，请先在电脑端使用")