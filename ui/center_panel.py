from __future__ import annotations

from collections.abc import Callable
from dataclasses import is_dataclass
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.models import TestResult
from core.paths import ensure_user_data_dir
from core.result_summary import SummaryResult, build_lte_summary
from reports.excel_exporter import export_results_to_excel

LogCallback = Callable[[str, str], None]

class CenterPanel(QWidget):
    HEADERS = ["Run ID", "序号", "数据来源", "制式", "Band", "信道", "频点类型", "测试模式", "带宽(MHz)", "仪表下发电平(dBm)", "总线损(dB)", "指标类型", "指标值", "尝试次数", "扫描阶段", "结果", "状态", "错误信息", "时间"]
    SUMMARY_HEADERS = ["Run ID", "数据来源", "制式", "Band", "信道", "频点类型", "测试模式", "带宽(MHz)", "灵敏度(dBm)", "RSRP(dBm)", "RSRQ(dB)", "PASS数量", "FAIL数量", "总数", "结果", "备注"]

    def __init__(self) -> None:
        super().__init__(); self._logger=None; self.summary_labels={}; self.test_results=[]; self.summary_results=[]; self.run_metadata={}; self.run_active=False; self.setMinimumWidth(520)
        layout=QVBoxLayout(self); layout.setContentsMargins(8,8,8,8); layout.setSpacing(8)
        self.simulation_banner=QLabel("SIMULATION / 模拟数据，不得作为正式实测报告"); self.simulation_banner.setAlignment(Qt.AlignmentFlag.AlignCenter); self.simulation_banner.setStyleSheet("background:#9b1c1c;color:white;font-weight:bold;padding:6px;border-radius:3px;"); self.simulation_banner.hide(); layout.addWidget(self.simulation_banner)
        layout.addWidget(self._create_summary_bar()); layout.addLayout(self._create_table_toolbar()); self.tab_widget=QTabWidget(); self.realtime_tab=QWidget(); self.summary_tab=QWidget(); self.table=self._create_table(self.HEADERS); self.summary_table=self._create_table(self.SUMMARY_HEADERS)
        rl=QVBoxLayout(self.realtime_tab); rl.setContentsMargins(0,0,0,0); rl.addWidget(self.table); sl=QVBoxLayout(self.summary_tab); sl.setContentsMargins(0,0,0,0); sl.addWidget(self.summary_table); self.tab_widget.addTab(self.summary_tab,"汇总结果"); self.tab_widget.addTab(self.realtime_tab,"实时数据"); layout.addWidget(self.tab_widget,1); self.tab_widget.setCurrentWidget(self.summary_tab)
    def set_logger(self,logger): self._logger=logger
    def begin_run(self,metadata):
        # Do not clear previous runs automatically. The operator explicitly owns
        # the lifetime of the on-screen history through "清除测试结果".
        self.run_metadata=dict(metadata); self.run_active=True; self.update_summary({"当前制式":"-","当前Band":"-","当前信道":"-","当前电平":"-","当前进度":"0/0"}); self.tab_widget.setCurrentWidget(self.summary_tab)
        simulated=self.run_metadata.get("data_source")=="SIMULATION"; self.simulation_banner.setText("SIMULATION / 模拟数据，不得作为正式实测报告"); self.simulation_banner.setVisible(simulated); self.clear_button.setEnabled(False); self.export_button.setEnabled(False); self._log("INFO",f"新建测试任务：{self.run_metadata.get('run_id','-')}；保留此前测试结果")
    def finish_run(self,metadata):
        self.run_metadata=dict(metadata); self.run_active=False; self.clear_button.setEnabled(True); self.export_button.setEnabled(True); self.generate_summary_from_current_results(); terminal_status=str(self.run_metadata.get("status","FAILED")).upper(); self.run_metadata["status"]=terminal_status; msgs=[]
        if self.run_metadata.get("data_source")=="SIMULATION": msgs.append("SIMULATION / 模拟数据")
        if terminal_status!="COMPLETED": msgs.append("安全清理未确认：结果无效，请立即人工确认 RF 状态" if terminal_status=="FAILED_UNSAFE" else f"测试未完整结束（{terminal_status}）：不得作为正式 PASS 结论")
        self.simulation_banner.setText(" | ".join(msgs)); self.simulation_banner.setVisible(bool(msgs))
        current_run_id=str(self.run_metadata.get("run_id",""))
        if terminal_status!="COMPLETED":
            for r in self.summary_results:
                if str(getattr(r,"run_id",""))==current_run_id:
                    r.result=terminal_status; r.remark=f"Run {terminal_status}; {r.remark}"
            self.update_summary_table(self.summary_results)
        current_raw=[r for r in self.test_results if str(getattr(r,"run_id",""))==current_run_id]
        current_summary=[r for r in self.summary_results if str(getattr(r,"run_id",""))==current_run_id]
        d=ensure_user_data_dir()/"runs"; d.mkdir(parents=True,exist_ok=True); p=d/f"{current_run_id or 'unknown'}.xlsx"; self.run_metadata["autosave_path"]=str(p)
        try: export_results_to_excel(current_raw,current_summary,str(p),run_metadata=self.run_metadata); self._log("INFO",f"本次任务结果已自动保存：{p}")
        except Exception as exc: self._log("ERROR",f"任务结果自动保存失败：{exc}")
        self._log("INFO",f"测试任务终态：{terminal_status}")
    def add_test_row(self,result):
        if isinstance(result,TestResult) and any(existing is result for existing in self.test_results):
            self.summary_results=build_lte_summary(self.test_results); self.update_summary_table(self.summary_results); return
        row=self.table.rowCount(); self.table.insertRow(row)
        if isinstance(result,TestResult): self.test_results.append(result)
        rd=self._normalize_row_data(result); rd.setdefault("序号",str(row+1)); rr=str(rd.get("结果","")).upper(); bg=self._result_background(rr)
        for col,h in enumerate(self.HEADERS):
            item=QTableWidgetItem(str(rd.get(h,""))); item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if bg: item.setBackground(bg)
            if h=="结果" and rr=="PASS": item.setForeground(Qt.GlobalColor.darkGreen)
            elif h=="结果" and rr in {"FAIL","FAILED"}: item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row,col,item)
        if self.auto_scroll_checkbox.isChecked(): self.table.scrollToBottom()
        self.summary_results=build_lte_summary(self.test_results); self.update_summary_table(self.summary_results)
    def update_summary(self,data):
        km={"current_mode":"当前制式","current_band":"当前Band","current_channel":"当前信道","current_level":"当前电平","progress":"当前进度"}
        for k,v in {km.get(k,k):v for k,v in data.items()}.items():
            if k in self.summary_labels: self.summary_labels[k].setText(f"{k}：{v}")
    def update_summary_table(self,results):
        self.summary_table.setRowCount(0)
        for sr in results:
            row=self.summary_table.rowCount(); self.summary_table.insertRow(row); rd=self._summary_result_to_row_data(sr); rr=str(rd.get("结果","")).upper(); bg=self._result_background(rr)
            for col,h in enumerate(self.SUMMARY_HEADERS):
                item=QTableWidgetItem(str(rd.get(h,""))); item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if bg: item.setBackground(bg)
                if h=="结果" and rr=="PASS": item.setForeground(Qt.GlobalColor.darkGreen)
                elif h=="结果" and rr in {"FAIL","FAILED"}: item.setForeground(Qt.GlobalColor.red)
                self.summary_table.setItem(row,col,item)
    def generate_summary_from_current_results(self): self._log("INFO","刷新汇总结果"); self.summary_results=build_lte_summary(self.test_results); self.update_summary_table(self.summary_results); self._log("INFO",f"当前保留 {len(self.summary_results)} 条汇总结果"); self.tab_widget.setCurrentWidget(self.summary_tab)
    def _log(self,level,message):
        if self._logger: self._logger(level,message)
    def _create_summary_bar(self):
        f=QFrame(); f.setObjectName("summaryBar"); f.setFrameShape(QFrame.Shape.StyledPanel); f.setStyleSheet("QFrame#summaryBar {background:#ffffff;border:1px solid #c3cbd4;border-radius:4px;}"); l=QHBoxLayout(f); l.setContentsMargins(10,8,10,8); l.setSpacing(14)
        for k in ["当前制式","当前Band","当前信道","当前电平","当前进度"]:
            label=QLabel(f"{k}：{'0/0' if k=='当前进度' else '-'}"); label.setMinimumWidth(88); self.summary_labels[k]=label; l.addWidget(label)
        l.addStretch(1); return f
    def _create_table_toolbar(self):
        l=QHBoxLayout(); self.clear_button=QPushButton("清除测试结果"); self.export_button=QPushButton("导出当前结果"); self.auto_scroll_checkbox=QCheckBox("自动滚动到底部"); self.auto_scroll_checkbox.setChecked(True); self.clear_button.clicked.connect(self._clear_table); self.export_button.clicked.connect(self._export_current_results); l.addWidget(self.clear_button); l.addWidget(self.export_button); l.addStretch(1); l.addWidget(self.auto_scroll_checkbox); return l
    def _clear_table(self):
        if self.run_active: self._log("WARNING","测试运行中不能清除测试结果"); return
        self._reset_results(); self.run_metadata={}; self.simulation_banner.hide(); self._log("INFO","已清除界面中的全部测试结果")
    def _reset_results(self): self.table.setRowCount(0); self.summary_table.setRowCount(0); self.test_results.clear(); self.summary_results.clear(); self.update_summary({"当前制式":"-","当前Band":"-","当前信道":"-","当前电平":"-","当前进度":"0/0"}); self.tab_widget.setCurrentWidget(self.summary_tab)
    def _create_table(self,headers):
        t=QTableWidget(0,len(headers)); t.setHorizontalHeaderLabels(headers); t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); t.setAlternatingRowColors(True); t.verticalHeader().setVisible(False); t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); t.horizontalHeader().setMinimumSectionSize(72); return t
    def _export_current_results(self):
        if not self.summary_results and self.test_results: self.summary_results=build_lte_summary(self.test_results); self.update_summary_table(self.summary_results)
        rid=str(self.run_metadata.get("run_id",""))[:8]; suffix=f"_{rid}" if rid else ""; name=f"cmw500_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}.xlsx"; path,_=QFileDialog.getSaveFileName(self,"导出当前结果",name,"Excel 工作簿 (*.xlsx);;所有文件 (*.*)")
        if not path: return
        if not path.lower().endswith(".xlsx"): path=f"{path}.xlsx"
        try: export_results_to_excel(self.test_results,self.summary_results,path,run_metadata=self.run_metadata)
        except Exception as exc: self._log("ERROR",f"结果导出失败：{exc}"); return
        self._log("INFO",f"结果已导出：{path}")
    def _normalize_row_data(self,r):
        if isinstance(r,TestResult) or is_dataclass(r): return {"Run ID":getattr(r,"run_id",""),"序号":r.index,"数据来源":getattr(r,"data_source",""),"制式":r.mode,"Band":r.band,"信道":r.channel,"频点类型":r.channel_type,"测试模式":r.test_mode,"带宽(MHz)":self._format_number(getattr(r,"bw",None)),"仪表下发电平(dBm)":self._format_number(getattr(r,"instrument_level",None)),"总线损(dB)":self._format_number(getattr(r,"total_loss",None)),"指标类型":r.metric_type,"指标值":self._format_number(r.metric_value,2),"尝试次数":getattr(r,"attempt",1),"扫描阶段":getattr(r,"scan_phase",""),"结果":r.result,"状态":r.status,"错误信息":getattr(r,"error_message",""),"时间":r.timestamp}
        return dict(r)
    def _summary_result_to_row_data(self,r):
        ref_unavailable=getattr(r,"reference_metrics_status","")=="UNAVAILABLE"
        return {"Run ID":getattr(r,"run_id",""),"数据来源":getattr(r,"data_source",""),"制式":r.mode,"Band":r.band,"信道":r.channel,"频点类型":r.channel_type,"测试模式":r.test_mode,"带宽(MHz)":self._format_number(getattr(r,"bw",None)),"灵敏度(dBm)":"-" if r.sensitivity is None else f"{r.sensitivity:g}","RSRP(dBm)":"N/A" if ref_unavailable or r.rsrp is None else f"{r.rsrp:g}","RSRQ(dB)":"N/A" if ref_unavailable or r.rsrq is None else f"{r.rsrq:g}","PASS数量":r.pass_count,"FAIL数量":r.fail_count,"总数":r.total_count,"结果":r.result,"备注":r.remark}
    def _result_background(self,r):
        if r=="PASS": return QColor("#eaf7ea")
        if r in {"FAIL","FAILED"}: return QColor("#fdecec")
        if r in {"ERROR","异常"}: return QColor("#fff7d6")
        if r in {"STOPPED","FAILED_UNSAFE"}: return QColor("#fff0c2")
        return None
    @staticmethod
    def _format_number(value,decimals=None):
        if value is None: return "-"
        try: n=float(value)
        except (TypeError,ValueError): return str(value)
        return f"{n:.{decimals}f}" if decimals is not None else f"{n:g}"
