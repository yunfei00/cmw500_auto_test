from __future__ import annotations
"""LTE V1 sensitivity scan and operator policy."""
import re, time
from typing import Any
from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox
from core.test_states import TestState
from core.test_worker import TestWorker
from core.android_dut_control import airplane_cycle as dut_airplane_cycle, apply_scene as apply_dut_scene
from ui.left_panel import LeftPanel

FAST_PACKET_DEFAULT=100; START_LEVEL_DEFAULT=-90.0; MAX_STEP_DEFAULT=0.3; MIN_STEP_DEFAULT=0.1; BLER_THRESHOLD_DEFAULT=5.0
FAST_CONFIRM_TRIGGER=1.2; CONFIRM_DIRECT_MIN=4.8; CONFIRM_DIRECT_MAX=5.0
RECONNECT_BOOST_DB=5.0; RECONNECT_ATTEMPTS=3; ATTACH_ATTEMPTS=3
FULL_CELL_BW_POWER_QUERY="SENSe:LTE:SIGN:DL:PCC:FCPOWer?"
RSRP_QUERY="SENSe:LTE:SIGN:UEReport:PCC:RSRP?"
RSRQ_QUERY="SENSe:LTE:SIGN:UEReport:PCC:RSRQ?"
PUSCH_OPEN_LOOP_COMMAND="CONFigure:LTE:SIGN:UL:PCC:PUSCh:OLNPower"; PUSCH_CLOSED_LOOP_COMMAND="CONFigure:LTE:SIGN:UL:PCC:PUSCh:TPC:CLTPower"; SETTINGS_PREFIX="lte/"
_original_create_lte_instrument_group=LeftPanel._create_lte_instrument_group; _original_create_lte_channel_group=LeftPanel._create_lte_channel_group; _original_create_lte_band_group=LeftPanel._create_lte_band_group; _original_collect_lte_config=LeftPanel.collect_lte_config; _original_measure_level=TestWorker._measure_level; _original_build_result=TestWorker._build_result; _original_configure_lte_run=TestWorker._configure_lte_run

def _setting(self,name,default,value_type): return self.settings.value(f"{SETTINGS_PREFIX}{name}",default,value_type)
def _create_lte_instrument_group(self):
    group=_original_create_lte_instrument_group(self); form=group.layout(); self.start_level_spin.setValue(float(_setting(self,"start_level",START_LEVEL_DEFAULT,float))); self.cable_loss_spin.setValue(float(_setting(self,"cable_loss",35.0,float))); self.packet_count_spin.setValue(int(_setting(self,"packet_count",1000,int))); self.max_step_spin.setValue(float(_setting(self,"max_step",MAX_STEP_DEFAULT,float))); self.min_step_spin.setValue(float(_setting(self,"min_step",MIN_STEP_DEFAULT,float))); self.bler_threshold_spin.setValue(float(_setting(self,"bler_threshold",BLER_THRESHOLD_DEFAULT,float))); self.settle_time_spin.setValue(int(_setting(self,"settle_time",2,int))); self.retry_count_spin.setValue(int(_setting(self,"retry_count",1,int))); cp=int(_setting(self,"com_port",1,int)); self.com_port_combo.setCurrentText(f"COM{cp}" if cp in {1,2,3,4} else "COM1")
    self.sensitivity_upper_spin.setVisible(False); self.stop_level_spin.setVisible(False)
    if hasattr(form,"labelForField"):
        for w in (self.sensitivity_upper_spin,self.stop_level_spin):
            label=form.labelForField(w)
            if label is not None: label.setVisible(False)
    self.fast_packet_count_spin=QSpinBox(); self.fast_packet_count_spin.setRange(1,999999); self.fast_packet_count_spin.setValue(int(_setting(self,"fast_packet_count",FAST_PACKET_DEFAULT,int)))
    self.pusch_open_loop_nom_power_spin=QDoubleSpinBox(); self.pusch_open_loop_nom_power_spin.setRange(-50.0,23.0); self.pusch_open_loop_nom_power_spin.setDecimals(1); self.pusch_open_loop_nom_power_spin.setSuffix(" dBm"); self.pusch_open_loop_nom_power_spin.setValue(float(_setting(self,"pusch_open_loop_nom_power",23.0,float)))
    self.pusch_closed_loop_target_power_spin=QDoubleSpinBox(); self.pusch_closed_loop_target_power_spin.setRange(-50.0,33.0); self.pusch_closed_loop_target_power_spin.setDecimals(1); self.pusch_closed_loop_target_power_spin.setSuffix(" dBm"); self.pusch_closed_loop_target_power_spin.setValue(float(_setting(self,"pusch_closed_loop_target_power",0.0,float)))
    row=max(0,form.rowCount()-6) if hasattr(form,"insertRow") else None
    if row is not None: form.insertRow(row,"快速测试包个数：",self.fast_packet_count_spin); form.insertRow(row+1,"PUSCH开环标称功率：",self.pusch_open_loop_nom_power_spin); form.insertRow(row+2,"PUSCH闭环目标功率：",self.pusch_closed_loop_target_power_spin)
    else: form.addRow("快速测试包个数：",self.fast_packet_count_spin); form.addRow("PUSCH开环标称功率：",self.pusch_open_loop_nom_power_spin); form.addRow("PUSCH闭环目标功率：",self.pusch_closed_loop_target_power_spin)
    return group
def _create_lte_channel_group(self):
    group=_original_create_lte_channel_group(self); selected={x for x in str(_setting(self,"test_items","三信道测试",str)).split("|") if x}
    for name,cb in self.lte_test_item_checkboxes.items(): cb.setChecked(name in selected)
    return group
def _create_lte_band_group(self):
    group=_original_create_lte_band_group(self); selected={x for x in str(_setting(self,"bands","",str)).split("|") if x}
    for band,cb in self.band_checkboxes.items(): cb.setChecked(f"B{band}" in selected)
    return group
def _save_lte_settings(self,config):
    values={"cable_loss":config.cable_loss,"start_level":config.start_level,"packet_count":config.packet_count,"fast_packet_count":getattr(config,"fast_packet_count",FAST_PACKET_DEFAULT),"max_step":config.max_step,"min_step":config.min_step,"bler_threshold":config.bler_threshold,"settle_time":config.settle_time,"retry_count":config.retry_count,"com_port":config.com_port,"pusch_open_loop_nom_power":config.pusch_open_loop_nom_power,"pusch_closed_loop_target_power":config.pusch_closed_loop_target_power,"bands":"|".join(config.selected_bands),"test_items":"|".join(config.lte_test_items)}
    for k,v in values.items(): self.settings.setValue(f"{SETTINGS_PREFIX}{k}",v)
    self.settings.remove(f"{SETTINGS_PREFIX}sensitivity_upper"); self.settings.sync()
def _collect_lte_config(self):
    config=_original_collect_lte_config(self); config.sensitivity_upper=config.start_level; config.fast_packet_count=int(self.fast_packet_count_spin.value()); config.reconnect_boost_db=RECONNECT_BOOST_DB; config.reconnect_attempts=RECONNECT_ATTEMPTS; config.pusch_open_loop_nom_power=float(self.pusch_open_loop_nom_power_spin.value()); config.pusch_closed_loop_target_power=float(self.pusch_closed_loop_target_power_spin.value()); _save_lte_settings(self,config); return config
def _configure_lte_run(self):
    _original_configure_lte_run(self)
    if bool(getattr(self.instrument,"is_simulation",False)): return
    write=getattr(self.instrument,"write",None)
    if not callable(write): return
    op=float(getattr(self.config,"pusch_open_loop_nom_power",23.0)); cp=float(getattr(self.config,"pusch_closed_loop_target_power",0.0)); write(f"{PUSCH_OPEN_LOOP_COMMAND} {op:g}"); write(f"{PUSCH_CLOSED_LOOP_COMMAND} {cp:g}"); self.log_signal.emit("INFO",f"PUSCH功控：Open Loop={op:g} dBm，Closed Loop={cp:g} dBm")
def _build_result(self,*args,**kwargs):
    result=_original_build_result(self,*args,**kwargs); result.scene=str(getattr(args[0] if args else kwargs.get("item"),"scene","灭屏")); self._last_built_test_result=result; return result
def _wait_connected(worker,timeout):
    method=getattr(worker.instrument,"wait_for_attach",None)
    if not callable(method): return True
    result=worker._call_with_supported_kwargs(method,timeout=timeout,cancel_check=worker._is_stopped); worker._raise_if_stopped(); worker._emit_instrument_warning(); return bool(result)
def _prepare_cell(self,item):
    self.set_state(TestState.CELL_CONFIGURING,f"状态切换：CELL_CONFIGURING - 配置 LTE 小区 {item.band}/{item.channel}"); self._call_lte_prepare_cell(item); self._raise_if_stopped(); self._emit_instrument_warning(); self.log_signal.emit("INFO",f"LTE 小区配置完成：{item.band} 信道 {item.channel} BW={item.bw}")
    for attempt in range(1,ATTACH_ATTEMPTS+1):
        self.set_state(TestState.CELL_ON,"状态切换：CELL_ON - LTE Cell ON"); self._call_lte_cell_on(item); self._raise_if_stopped(); self._emit_instrument_warning()
        self.log_signal.emit("INFO","LTE Cell ON 后执行 DUT 飞行模式快速连接")
        dut_airplane_cycle(self)
        self.set_state(TestState.WAITING_ATTACH,"状态切换：WAITING_ATTACH - 等待 UE Attach"); started=time.monotonic(); connected=self._call_wait_for_attach(); elapsed=time.monotonic()-started
        if connected: self._raise_if_stopped(); self._emit_instrument_warning(); self.set_state(TestState.ATTACHED,"状态切换：ATTACHED - UE 已连接"); self.log_signal.emit("INFO",f"UE 已连接，耗时 {elapsed:.2f} s"); self._run_before_measure(); return
        self._emit_instrument_warning(); self.log_signal.emit("WARNING",f"UE Attach 超时：已等待 {elapsed:.2f} s（{attempt}/{ATTACH_ATTEMPTS}）")
        if attempt>=ATTACH_ATTEMPTS: break
        self.log_signal.emit("WARNING",f"Attach 超时，Cell OFF → ON 重试 {attempt+1}/{ATTACH_ATTEMPTS}")
        if not self._safe_cell_off(): raise RuntimeError("UE Attach 超时后 Cell OFF 失败")
    raise RuntimeError(f"UE Attach 连续 {ATTACH_ATTEMPTS} 次超时，连接失败")
def _ensure_connected_for_probe(worker,item,requested_level):
    level=float(requested_level); worker.instrument.set_rx_level(worker._instrument_level_for_dut(item,level)); worker._raise_if_stopped(); worker._emit_instrument_warning()
    if _wait_connected(worker,0.0): return level,False
    boost=float(getattr(worker.config,"reconnect_boost_db",RECONNECT_BOOST_DB)); attempts=int(getattr(worker.config,"reconnect_attempts",RECONNECT_ATTEMPTS)); worker.log_signal.emit("WARNING",f"{item.band}/{item.channel} UE 已掉线，开始 +{boost:g} dB 恢复"); recovery=level
    for attempt in range(1,attempts+1):
        recovery=round(recovery+boost,10); worker.instrument.set_rx_level(worker._instrument_level_for_dut(item,recovery)); worker._raise_if_stopped(); worker._emit_instrument_warning()
        worker.log_signal.emit("WARNING",f"UE 掉线恢复 {attempt}/{attempts}：执行 DUT 飞行模式循环")
        dut_airplane_cycle(worker)
        started=time.monotonic()
        if _wait_connected(worker,10.0): worker.log_signal.emit("INFO",f"UE 已恢复连接，耗时 {time.monotonic()-started:.2f} s"); return recovery,True
        worker.log_signal.emit("WARNING",f"UE 重连超时：已等待 {time.monotonic()-started:.2f} s（{attempt}/{attempts}）")
    raise RuntimeError(f"UE 掉线后连续 {attempts} 次 +{boost:g} dB 仍无法恢复连接")
def _parse_numeric(response):
    match=re.search(r"[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?",str(response).strip())
    if not match: raise ValueError(f"无法解析返回值：{response!r}")
    return float(match.group(0))
def _query_full_cell_bw_power(worker):
    if bool(getattr(worker.instrument,"is_simulation",False)): return None
    query=getattr(worker.instrument,"query",None)
    if not callable(query): return None
    try: return _parse_numeric(query(FULL_CELL_BW_POWER_QUERY))
    except Exception as exc: worker.log_signal.emit("WARNING",f"Full Cell BW Power 查询失败：{exc}"); return None
def _collect_final_reference_metrics(worker):
    result=getattr(worker,"_last_built_test_result",None)
    if result is None or bool(getattr(worker.instrument,"is_simulation",False)): return
    query=getattr(worker.instrument,"query",None)
    if not callable(query): return
    try:
        result.rsrp=_parse_numeric(query(RSRP_QUERY))
        result.rsrq=_parse_numeric(query(RSRQ_QUERY))
        result.reference_metrics_status="AVAILABLE"
        worker.log_signal.emit("INFO",f"最终参考值：RSRP={result.rsrp:g} dBm，RSRQ={result.rsrq:g} dB")
    except Exception as exc:
        result.rsrp=None; result.rsrq=None; result.reference_metrics_status="UNAVAILABLE"
        worker.log_signal.emit("WARNING",f"最终 RSRP/RSRQ 查询失败（不影响 BLER 灵敏度结果）：{exc}")

def _measure_with_packets(worker,item,level,phase,current,total,packet_count):
    op=worker.config.packet_count; oretry=worker.config.retry_count; worker.config.packet_count=int(packet_count); worker.config.retry_count=0
    try:
        passed=_original_measure_level(worker,item,level,phase,current,total); power=_query_full_cell_bw_power(worker)
        if power is not None: worker.log_signal.emit("INFO",f"{phase} {item.band}/{item.channel} Full Cell BW Power={power:g} dBm")
        return passed
    finally: worker.config.packet_count=op; worker.config.retry_count=oretry
def _last_bler(worker):
    result=getattr(worker,"_last_built_test_result",None)
    if result is None or str(getattr(result,"metric_type","")).upper()!="BLER" or getattr(result,"metric_value",None) is None: return None
    return float(result.metric_value)
def _scan_item(self,item,current,total):
    level=float(self.config.start_level); fast=int(getattr(self.config,"fast_packet_count",FAST_PACKET_DEFAULT)); formal=int(self.config.packet_count); max_step=float(self.config.max_step); min_step=float(self.config.min_step); self.log_signal.emit("INFO",f"LTE 快速灵敏度扫描：起点={level:g} dBm，快速={fast}包/{max_step:g}dB，BLER>{FAST_CONFIRM_TRIGGER:g}%触发确认，确认={formal}包，细扫={min_step:g}dB")
    while True:
        level,recovered=_ensure_connected_for_probe(self,item,level)
        if recovered and level>float(self.config.start_level): self.log_signal.emit("WARNING",f"恢复电平 {level:g} dBm 高于初始电平 {self.config.start_level:g} dBm")
        _measure_with_packets(self,item,level,"FAST",current,total,fast); fast_bler=_last_bler(self)
        if fast_bler is None: raise RuntimeError("FAST BLER 结果为空")
        if fast_bler<=FAST_CONFIRM_TRIGGER: level=round(level-max_step,10); continue
        self.log_signal.emit("INFO",f"FAST BLER={fast_bler:.2f}% > {FAST_CONFIRM_TRIGGER:g}%，当前点使用 {formal} 包二次确认")
        confirm,recovered=_ensure_connected_for_probe(self,item,level)
        if recovered: level=confirm; continue
        _measure_with_packets(self,item,level,"CONFIRM",current,total,formal); confirm_bler=_last_bler(self)
        if confirm_bler is None: raise RuntimeError("CONFIRM BLER 结果为空")
        if CONFIRM_DIRECT_MIN<=confirm_bler<=CONFIRM_DIRECT_MAX:
            self.log_signal.emit("INFO",f"CONFIRM BLER={confirm_bler:.2f}% 位于 {CONFIRM_DIRECT_MIN:g}%~{CONFIRM_DIRECT_MAX:g}%，直接确定 Sensitivity={level:g} dBm，不再向上回溯")
            result=getattr(self,"_last_built_test_result",None)
            if result is not None:
                result.scan_phase="FINE"; result.result="PASS"; result.status="PASS"; _collect_final_reference_metrics(self); self.row_signal.emit(result)
            return
        if confirm_bler<float(self.config.bler_threshold): level=round(level-max_step,10); continue
        fail_level=level; fine=round(fail_level+min_step,10)
        while True:
            fine,recovered=_ensure_connected_for_probe(self,item,fine)
            if recovered: level=fine; break
            if _measure_with_packets(self,item,fine,"FINE",current,total,formal):
                _collect_final_reference_metrics(self); self.row_signal.emit(getattr(self,"_last_built_test_result",None)); self.log_signal.emit("INFO",f"Sensitivity 边界：PASS={fine:g} dBm，FAIL={fail_level:g} dBm"); return
            fail_level=fine; fine=round(fine+min_step,10)
def apply_lte_fast_scan_policy():
    if getattr(TestWorker,"_lte_fast_scan_policy_applied",False): return
    LeftPanel._create_lte_instrument_group=_create_lte_instrument_group; LeftPanel._create_lte_channel_group=_create_lte_channel_group; LeftPanel._create_lte_band_group=_create_lte_band_group; LeftPanel.collect_lte_config=_collect_lte_config; TestWorker._configure_lte_run=_configure_lte_run; TestWorker._prepare_cell=_prepare_cell; TestWorker._build_result=_build_result; TestWorker._scan_item=_scan_item; TestWorker._lte_fast_scan_policy_applied=True
