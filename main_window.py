"""
main_window.py - 图形界面（终极完整版）
"""

import sys
import os
import glob
from datetime import datetime
import pandas as pd
import numpy as np
import time

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QTextEdit,
    QGroupBox, QHeaderView, QTabWidget, QFileDialog, QMessageBox,
    QProgressBar, QDateEdit, QLineEdit
)
from PyQt5.QtCore import QThread, pyqtSignal, QDate, QTimer
from PyQt5.QtGui import QFont

import market_state
import tracker
import ranker
from stock_filter import get_filtered_codes, initial_screen_and_fetch
from factors import calc_all_factors


class ScanThread(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, float)

    def run(self):
        start = time.time()
        try:
            self.log.emit("===== 开始扫描 =====")
            self.progress.emit(10)
            ranker.run_ranking()
            self.progress.emit(80)
            self.log.emit("扫描完成，更新跟踪表...")
            today = datetime.now().strftime('%Y%m%d')
            cand_file = f'候选池_{today}_带名称.csv'
            if os.path.exists(cand_file):
                top5 = pd.read_csv(cand_file, dtype={'代码': str}).head(5)
                tracker.add_to_tracker(top5[['代码','名称','总分']])
            tracker.update_tracker()
            self.progress.emit(100)
            elapsed = time.time() - start
            self.finished.emit(True, elapsed)
        except Exception as e:
            self.log.emit(f"扫描失败：{str(e)}")
            elapsed = time.time() - start
            self.finished.emit(False, elapsed)


class CustomScoreThread(QThread):
    log = pyqtSignal(str)
    finished = pyqtSignal(list)

    def __init__(self, codes):
        super().__init__()
        self.codes = codes

    def run(self):
        results = []
        today_str = datetime.now().strftime('%Y%m%d')
        factor_file = f'全市场因子_{today_str}.csv'

        if not os.path.exists(factor_file):
            files = glob.glob('全市场因子_*.csv')
            if files:
                latest_file = sorted(files, reverse=True)[0]
                self.log.emit(f"今日因子文件缺失，使用最近数据：{latest_file}")
                factor_file = latest_file
            else:
                self.log.emit("全市场因子文件缺失，请先执行一次全市场扫描")
                for code in self.codes:
                    results.append({'代码': code, '状态': '全市场因子缺失'})
                self.finished.emit(results)
                return

        for code in self.codes:
            self.log.emit(f"正在处理 {code}...")
            data_dict = initial_screen_and_fetch([code])
            if code not in data_dict:
                self.log.emit(f"{code} 未通过初筛")
                results.append({'代码': code, '状态': '未通过初筛'})
                continue

            df = data_dict[code]
            if 'ma5' not in df.columns:
                df['ma5'] = df['close'].rolling(5).mean()
                df['ma10'] = df['close'].rolling(10).mean()
                df['ma20'] = df['close'].rolling(20).mean()
                df['ma60'] = df['close'].rolling(60).mean()
            factors = calc_all_factors(code, df)
            if not factors:
                results.append({'代码': code, '状态': '因子计算失败'})
                continue

            df_all = pd.read_csv(factor_file, dtype={'code': str})
            new_row = {**factors, 'code': code}
            df_all = df_all.append(new_row, ignore_index=True)

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

            df_all.sort_values('total_score', ascending=False, inplace=True)
            df_all.reset_index(drop=True, inplace=True)
            rank_idx = df_all[df_all['code'] == code].index[0] + 1
            row = df_all.iloc[rank_idx - 1]
            in_pool = rank_idx <= 100
            name = ''
            try:
                import akshare as ak
                stock_info = ak.stock_info_a_code_name()
                matched = stock_info[stock_info['code'] == code]
                if not matched.empty:
                    name = matched.iloc[0]['name']
            except:
                pass

            results.append({
                '日期': datetime.now().strftime('%Y-%m-%d'),
                '代码': code,
                '名称': name,
                '总分': round(row['total_score'], 2),
                '趋势得分': round(row['trend_score'], 2),
                '资金得分': round(row['fund_score'], 2),
                '板块得分': round(row['sector_score'], 2),
                '质量得分': round(row['risk_score'], 2),
                '全市场排名': rank_idx,
                '总股票数': len(df_all),
                '是否入池': '是' if in_pool else '否',
                '状态': '成功'
            })
            self.log.emit(f"{code} 打分完成，排名 {rank_idx}/{len(df_all)}")

        hist_file = '自定义打分记录.csv'
        hist_df = pd.DataFrame(results)
        if os.path.exists(hist_file):
            hist_df.to_csv(hist_file, mode='a', header=False, index=False, encoding='utf-8-sig')
        else:
            hist_df.to_csv(hist_file, index=False, encoding='utf-8-sig')
        self.finished.emit(results)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("A股趋势评分系统 V2.0")
        self.resize(1200, 800)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        control = QHBoxLayout()
        self.scan_btn = QPushButton("开始扫描")
        self.scan_btn.clicked.connect(self.start_scan)
        control.addWidget(self.scan_btn)

        self.stop_btn = QPushButton("停止扫描")
        self.stop_btn.clicked.connect(self.stop_scan)
        self.stop_btn.setEnabled(False)
        control.addWidget(self.stop_btn)

        self.market_label = QLabel("市场：--")
        control.addWidget(self.market_label)

        self.export_cand_btn = QPushButton("导出候选池")
        self.export_cand_btn.clicked.connect(self.export_candidate)
        control.addWidget(self.export_cand_btn)

        self.export_track_btn = QPushButton("导出跟踪表")
        self.export_track_btn.clicked.connect(self.export_tracker)
        control.addWidget(self.export_track_btn)

        control.addStretch()
        main_layout.addLayout(control)

        progress_layout = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        progress_layout.addWidget(self.progress)
        self.time_label = QLabel("耗时：--")
        progress_layout.addWidget(self.time_label)
        main_layout.addLayout(progress_layout)

        self.elapsed_timer = QTimer()
        self.elapsed_timer.timeout.connect(self.update_elapsed)
        self.scan_start_time = None

        tabs = QTabWidget()
        main_layout.addWidget(tabs)

        # ===== 今日候选池 =====
        cand_tab = QWidget()
        cand_layout = QVBoxLayout(cand_tab)
        self.cand_table = QTableWidget()
        self.cand_table.setColumnCount(9)
        self.cand_table.setHorizontalHeaderLabels([
            "代码", "名称", "总分", "趋势得分", "资金得分", "板块得分", "质量得分", "连续在榜", "状态"
        ])
        self.cand_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cand_table.setSortingEnabled(True)
        cand_layout.addWidget(self.cand_table)
        tabs.addTab(cand_tab, "今日候选池")

        # ===== 实盘跟踪 =====
        track_tab = QWidget()
        track_layout = QVBoxLayout(track_tab)
        self.track_table = QTableWidget()
        self.track_table.setColumnCount(14)
        self.track_table.setHorizontalHeaderLabels([
            "入选日期","代码","名称","入选评分","成本价","现价","盈亏%",
            "持仓天数","是否在池","最新评分","评分变化","行业","市盈率","市净率"
        ])
        self.track_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.track_table.setSortingEnabled(True)
        track_layout.addWidget(self.track_table)
        self.track_summary = QLabel()
        track_layout.addWidget(self.track_summary)
        tabs.addTab(track_tab, "实盘跟踪")

        # ===== 自定义打分 =====
        custom_tab = QWidget()
        custom_layout = QVBoxLayout(custom_tab)
        input_layout = QHBoxLayout()
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText("输入股票代码，逗号分隔")
        input_layout.addWidget(self.custom_input)
        self.custom_score_btn = QPushButton("开始打分")
        self.custom_score_btn.clicked.connect(self.start_custom_score)
        input_layout.addWidget(self.custom_score_btn)
        input_layout.addStretch()
        custom_layout.addLayout(input_layout)

        self.custom_result_table = QTableWidget()
        self.custom_result_table.setColumnCount(8)
        self.custom_result_table.setHorizontalHeaderLabels([
            "代码", "名称", "总分", "趋势得分", "资金得分", "板块得分", "质量得分", "全市场排名"
        ])
        self.custom_result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        custom_layout.addWidget(self.custom_result_table)

        self.custom_hist_table = QTableWidget()
        self.custom_hist_table.setColumnCount(9)
        self.custom_hist_table.setHorizontalHeaderLabels([
            "日期", "代码", "名称", "总分", "全市场排名", "是否入池", "趋势得分", "资金得分", "质量得分"
        ])
        self.custom_hist_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        custom_layout.addWidget(QLabel("历史打分记录"))
        custom_layout.addWidget(self.custom_hist_table)
        self.load_custom_history()
        tabs.addTab(custom_tab, "自定义打分")

        # ===== 统计面板 =====
        stat_tab = QWidget()
        stat_layout = QVBoxLayout(stat_tab)
        self.yesterday_label = QLabel("昨日候选池今日表现：--")
        stat_layout.addWidget(self.yesterday_label)
        self.streak_label = QLabel("连续在榜天数：--")
        stat_layout.addWidget(self.streak_label)
        self.quality_label = QLabel("持仓质量分布：--")
        stat_layout.addWidget(self.quality_label)
        calc_yesterday_btn = QPushButton("刷新昨日表现")
        calc_yesterday_btn.clicked.connect(self.calc_yesterday_performance)
        stat_layout.addWidget(calc_yesterday_btn)
        stat_layout.addStretch()
        tabs.addTab(stat_tab, "统计面板")

        # ===== 历史回顾 =====
        hist_tab = QWidget()
        hist_layout = QVBoxLayout(hist_tab)
        hist_control = QHBoxLayout()
        self.date_edit = QDateEdit(QDate.currentDate())
        hist_control.addWidget(QLabel("选择日期："))
        hist_control.addWidget(self.date_edit)
        self.load_hist_btn = QPushButton("加载历史候选池")
        self.load_hist_btn.clicked.connect(self.load_history)
        hist_control.addWidget(self.load_hist_btn)
        hist_control.addStretch()
        hist_layout.addLayout(hist_control)
        self.hist_table = QTableWidget()
        self.hist_table.setColumnCount(3)
        self.hist_table.setHorizontalHeaderLabels(["代码","名称","总分"])
        self.hist_table.setSortingEnabled(True)
        hist_layout.addWidget(self.hist_table)
        tabs.addTab(hist_tab, "历史回顾")

        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(100)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

        self.scan_thread = None
        self.custom_thread = None
        self.refresh_all()

    def log(self, msg):
        self.log_text.append(msg)

    def start_scan(self):
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setValue(0)
        self.scan_start_time = time.time()
        self.elapsed_timer.start(1000)
        self.scan_thread = ScanThread()
        self.scan_thread.log.connect(self.log)
        self.scan_thread.progress.connect(self.progress.setValue)
        self.scan_thread.finished.connect(self.on_scan_finished)
        self.scan_thread.start()

    def stop_scan(self):
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.terminate()
            self.log("用户停止了扫描")
            self.on_scan_finished(False, 0)

    def update_elapsed(self):
        if self.scan_start_time:
            elapsed = time.time() - self.scan_start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.time_label.setText(f"耗时：{minutes}分{seconds}秒")

    def on_scan_finished(self, success, elapsed):
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.elapsed_timer.stop()
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        self.time_label.setText(f"耗时：{minutes}分{seconds}秒")
        if success:
            self.log(f"===== 扫描完成，耗时 {minutes}分{seconds}秒 =====")
            self.refresh_all()
        else:
            self.log("扫描未正常完成")

    def refresh_all(self):
        self.refresh_candidate_table()
        self.refresh_tracker_table()
        self.refresh_stat_panel()
        self.refresh_market()

    def calc_streak(self, code):
        streak = 0
        today = datetime.now()
        for i in range(1, 30):
            date = today - pd.Timedelta(days=i)
            fname = f"历史记录/候选池_{date.strftime('%Y%m%d')}.csv"
            if not os.path.exists(fname):
                break
            df = pd.read_csv(fname, dtype={'代码': str})
            if code in df['代码'].values:
                streak += 1
            else:
                break
        return streak

    def refresh_candidate_table(self):
        today = datetime.now().strftime('%Y%m%d')
        fname = f'候选池_{today}_带名称.csv'
        if not os.path.exists(fname):
            self.cand_table.setRowCount(0)
            return
        df = pd.read_csv(fname, dtype={'代码': str})
        self.cand_table.setRowCount(len(df))
        for i in range(len(df)):
            row = df.iloc[i]
            self.cand_table.setItem(i, 0, QTableWidgetItem(row['代码']))
            self.cand_table.setItem(i, 1, QTableWidgetItem(row['名称']))
            self.cand_table.setItem(i, 2, QTableWidgetItem(f"{row['总分']:.2f}"))
            self.cand_table.setItem(i, 3, QTableWidgetItem(f"{row.get('趋势得分', '')}"))
            self.cand_table.setItem(i, 4, QTableWidgetItem(f"{row.get('资金得分', '')}"))
            self.cand_table.setItem(i, 5, QTableWidgetItem(f"{row.get('板块得分', '')}"))
            self.cand_table.setItem(i, 6, QTableWidgetItem(f"{row.get('质量得分', '')}"))
            streak = self.calc_streak(row['代码'])
            self.cand_table.setItem(i, 7, QTableWidgetItem(str(streak)))
            self.cand_table.setItem(i, 8, QTableWidgetItem(""))

    def refresh_tracker_table(self):
        df = tracker.update_tracker()
        if df.empty:
            self.track_table.setRowCount(0)
            self.track_summary.setText("无持仓")
            return

        in_pool_map = tracker.check_in_pool()
        self.track_table.setRowCount(len(df))
        for i in range(len(df)):
            row = df.iloc[i]
            # 入选日期只显示月-日
            date_str = str(row['入选日期'])
            short_date = date_str[5:] if len(date_str) >= 10 else date_str
            self.track_table.setItem(i, 0, QTableWidgetItem(short_date))
            
            self.track_table.setItem(i, 1, QTableWidgetItem(row['代码']))
            self.track_table.setItem(i, 2, QTableWidgetItem(row['名称']))
            self.track_table.setItem(i, 3, QTableWidgetItem(str(row.get('入选评分', ''))))
            self.track_table.setItem(i, 4, QTableWidgetItem(f"{row['成本价']:.2f}"))
            self.track_table.setItem(i, 5, QTableWidgetItem(f"{row['现价']:.2f}"))
            self.track_table.setItem(i, 6, QTableWidgetItem(f"{row['盈亏%']}%"))
            self.track_table.setItem(i, 7, QTableWidgetItem(str(row.get('持仓天数', ''))))
            code = row['代码']
            in_pool = in_pool_map.get(code, False)
            self.track_table.setItem(i, 8, QTableWidgetItem("✅在池" if in_pool else "⚠️掉出"))
            self.track_table.setItem(i, 9, QTableWidgetItem(str(row.get('最新评分', ''))))
            self.track_table.setItem(i, 10, QTableWidgetItem(str(row.get('评分变化', ''))))
            self.track_table.setItem(i, 11, QTableWidgetItem(row.get('行业', '')))
            self.track_table.setItem(i, 12, QTableWidgetItem(str(row.get('市盈率', ''))))
            self.track_table.setItem(i, 13, QTableWidgetItem(str(row.get('市净率', ''))))

        # 自适应列宽
        self.track_table.resizeColumnToContents(0)
        self.track_table.resizeColumnToContents(2)

        total_val = (df['现价'].fillna(df['成本价']) * 1000).sum()
        total_cost = (df['成本价'] * 1000).sum()
        profit = total_val - total_cost
        profit_pct = (profit / total_cost * 100) if total_cost else 0
        self.track_summary.setText(f"总市值：{total_val:.0f}  |  总盈亏：{profit:+.0f} ({profit_pct:+.2f}%)")

    def refresh_stat_panel(self):
        self.streak_label.setText("连续在榜天数统计：已显示在候选池表格中")
        qs = []
        df_track = tracker.load_tracker()
        for code in df_track['代码']:
            qs.append(tracker.quality_check(str(code)))
        if qs:
            from collections import Counter
            count = Counter(qs)
            self.quality_label.setText(f"持仓质量：{dict(count)}")
        else:
            self.quality_label.setText("无持仓")

    def calc_yesterday_performance(self):
        self.yesterday_label.setText("昨日候选池今日表现：功能完善中")

    def refresh_market(self):
        state, desc = market_state.get_market_state()
        self.market_label.setText(f"市场：{state}（{desc}）")

    def export_candidate(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出候选池", f"候选池_{datetime.now():%Y%m%d}.csv", "CSV (*.csv)")
        if path:
            today = datetime.now().strftime('%Y%m%d')
            src = f'候选池_{today}_带名称.csv'
            if os.path.exists(src):
                pd.read_csv(src).to_csv(path, index=False, encoding='utf-8-sig')
                self.log(f"候选池已导出至 {path}")

    def export_tracker(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出跟踪表", f"跟踪表_{datetime.now():%Y%m%d}.csv", "CSV (*.csv)")
        if path:
            df = tracker.load_tracker()
            if not df.empty:
                df.to_csv(path, index=False, encoding='utf-8-sig')
                self.log(f"跟踪表已导出至 {path}")

    def load_history(self):
        date = self.date_edit.date().toPyDate()
        fname = f"历史记录/候选池_{date.strftime('%Y%m%d')}.csv"
        if not os.path.exists(fname):
            QMessageBox.information(self, "提示", "该日期无候选池记录")
            return
        df = pd.read_csv(fname, dtype={'代码': str})
        self.hist_table.setRowCount(len(df))
        for i in range(len(df)):
            row = df.iloc[i]
            self.hist_table.setItem(i, 0, QTableWidgetItem(row['代码']))
            self.hist_table.setItem(i, 1, QTableWidgetItem(row.get('名称', '')))
            self.hist_table.setItem(i, 2, QTableWidgetItem(f"{row['总分']:.2f}"))

    def start_custom_score(self):
        codes = [c.strip() for c in self.custom_input.text().split(',') if c.strip()]
        if not codes:
            QMessageBox.warning(self, "提示", "请输入股票代码")
            return
        self.custom_score_btn.setEnabled(False)
        self.custom_thread = CustomScoreThread(codes)
        self.custom_thread.log.connect(self.log)
        self.custom_thread.finished.connect(self.on_custom_score_finished)
        self.custom_thread.start()

    def on_custom_score_finished(self, results):
        self.custom_score_btn.setEnabled(True)
        self.custom_result_table.setRowCount(len(results))
        for i, res in enumerate(results):
            self.custom_result_table.setItem(i, 0, QTableWidgetItem(res.get('代码', '')))
            self.custom_result_table.setItem(i, 1, QTableWidgetItem(res.get('名称', '')))
            self.custom_result_table.setItem(i, 2, QTableWidgetItem(str(res.get('总分', ''))))
            self.custom_result_table.setItem(i, 3, QTableWidgetItem(str(res.get('趋势得分', ''))))
            self.custom_result_table.setItem(i, 4, QTableWidgetItem(str(res.get('资金得分', ''))))
            self.custom_result_table.setItem(i, 5, QTableWidgetItem(str(res.get('板块得分', ''))))
            self.custom_result_table.setItem(i, 6, QTableWidgetItem(str(res.get('质量得分', ''))))
            rank = f"{res.get('全市场排名', '')}/{res.get('总股票数', '')}"
            self.custom_result_table.setItem(i, 7, QTableWidgetItem(rank))
        self.load_custom_history()

    def load_custom_history(self):
        hist_file = '自定义打分记录.csv'
        if not os.path.exists(hist_file):
            return
        df = pd.read_csv(hist_file, dtype={'代码': str})
        self.custom_hist_table.setRowCount(len(df))
        for i in range(len(df)):
            row = df.iloc[i]
            self.custom_hist_table.setItem(i, 0, QTableWidgetItem(str(row.get('日期', ''))))
            self.custom_hist_table.setItem(i, 1, QTableWidgetItem(row['代码']))
            self.custom_hist_table.setItem(i, 2, QTableWidgetItem(row.get('名称', '')))
            self.custom_hist_table.setItem(i, 3, QTableWidgetItem(str(row.get('总分', ''))))
            self.custom_hist_table.setItem(i, 4, QTableWidgetItem(str(row.get('全市场排名', ''))))
            self.custom_hist_table.setItem(i, 5, QTableWidgetItem(row.get('是否入池', '')))
            self.custom_hist_table.setItem(i, 6, QTableWidgetItem(str(row.get('趋势得分', ''))))
            self.custom_hist_table.setItem(i, 7, QTableWidgetItem(str(row.get('资金得分', ''))))
            self.custom_hist_table.setItem(i, 8, QTableWidgetItem(str(row.get('质量得分', ''))))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())