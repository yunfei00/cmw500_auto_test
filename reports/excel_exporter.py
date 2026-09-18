from __future__ import annotations
import json, os, tempfile
from pathlib import Path

RAW_HEADERS=["Run ID","序号","数据来源","场景","制式","Band","信道","频点类型","测试模式","带宽(MHz)","仪表下发电平(dBm)","全局线损(dB)","信道线损(dB)","总线损(dB)","指标类型","指标值","包数","BLER门限(%)","尝试次数","扫描阶段","结果","状态","错误信息","时间"]
SUMMARY_HEADERS=["Run ID","数据来源","场景","制式","Band","信道","频点类型","测试模式","带宽(MHz)","灵敏度(dBm)","相对Idle劣化(dB)","最终BLER(%)","RSRP(dBm)","RSRQ(dB)","PASS数量","FAIL数量","总数","结果","备注"]

def export_results_to_excel(raw_results,summary_results,file_path,run_metadata=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment,Font,PatternFill
    wb=Workbook(); raw=wb.active; raw.title="RawResults"; summary=wb.create_sheet("Summary"); metadata_sheet=wb.create_sheet("RunMetadata"); trace_sheet=wb.create_sheet("SCPITrace")
    fills={"PASS":PatternFill("solid",fgColor="EAF7EA"),"FAIL":PatternFill("solid",fgColor="FDECEC"),"ERROR":PatternFill("solid",fgColor="FFF0C2"),"FAILED":PatternFill("solid",fgColor="FFF0C2"),"FAILED_UNSAFE":PatternFill("solid",fgColor="F8C4C4"),"STOPPED":PatternFill("solid",fgColor="FFF0C2")}; hf=PatternFill("solid",fgColor="E5EBF0"); font=Font(bold=True); center=Alignment(horizontal="center",vertical="center"); md=dict(run_metadata or {})
    if any(str(getattr(r,"data_source","")).upper()=="SIMULATION" for r in raw_results): md["contains_simulation_data"]=True
    warnings=_run_warnings(md); banner=" | ".join(warnings); _write_sheet(raw,RAW_HEADERS,[_raw_result_row(r) for r in raw_results],fills,hf,font,center,"结果",banner); _write_sheet(summary,SUMMARY_HEADERS,[_summary_result_row(r) for r in summary_results],fills,hf,font,center,"结果",banner); _write_metadata_sheet(metadata_sheet,md,warnings,hf,font); _write_trace_sheet(trace_sheet,md.get("command_trace",[]),hf,font)
    out=Path(file_path); out.parent.mkdir(parents=True,exist_ok=True); tmp=None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{out.stem}_",suffix=".xlsx",dir=out.parent,delete=False) as f: tmp=Path(f.name)
        wb.save(tmp); os.replace(tmp,out)
    finally:
        if tmp and tmp.exists(): tmp.unlink()

def _write_sheet(sheet,headers,rows,fills,hf,font,center,result_column_name,banner=""):
    from openpyxl.styles import Font,PatternFill
    hr=1
    if banner:
        sheet.append([banner]); sheet.merge_cells(start_row=1,start_column=1,end_row=1,end_column=len(headers)); c=sheet.cell(1,1); c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="9B1C1C"); c.alignment=center; hr=2
    sheet.append(headers)
    for row in rows: sheet.append([_excel_safe_value(v) for v in row])
    ri=headers.index(result_column_name)+1
    for c in sheet[hr]: c.font=font; c.fill=hf; c.alignment=center
    for row in sheet.iter_rows(min_row=hr+1,max_row=sheet.max_row):
        fill=fills.get(str(row[ri-1].value or "").upper())
        for c in row:
            c.alignment=center
            if fill: c.fill=fill
    sheet.freeze_panes=f"A{hr+1}"; _auto_fit_columns(sheet)

def _auto_fit_columns(sheet):
    from openpyxl.utils import get_column_letter
    for i,cells in enumerate(sheet.iter_cols(),1): sheet.column_dimensions[get_column_letter(i)].width=min(max(max((len("" if c.value is None else str(c.value)) for c in cells),default=0)+2,10),32)

def _raw_result_row(r): return [getattr(r,"run_id",""),r.index,getattr(r,"data_source",""),getattr(r,"scene_id","default"),r.mode,r.band,r.channel,r.channel_type,r.test_mode,getattr(r,"bw",None),getattr(r,"instrument_level",None),getattr(r,"global_cable_loss",None),getattr(r,"channel_loss",None),getattr(r,"total_loss",None),r.metric_type,r.metric_value,getattr(r,"packet_count",None),getattr(r,"bler_threshold",None),getattr(r,"attempt",1),getattr(r,"scan_phase",""),r.result,r.status,getattr(r,"error_message",""),r.timestamp]
def _summary_result_row(r):
    unavailable=getattr(r,"reference_metrics_status","")=="UNAVAILABLE"; final_bler=getattr(r,"final_bler",None)
    return [getattr(r,"run_id",""),getattr(r,"data_source",""),getattr(r,"scene_id","default"),r.mode,r.band,r.channel,r.channel_type,r.test_mode,getattr(r,"bw",None),"-" if r.sensitivity is None else r.sensitivity,"N/A" if getattr(r,"delta_vs_idle",None) is None else getattr(r,"delta_vs_idle",None),"N/A" if final_bler is None else final_bler,"N/A" if unavailable or getattr(r,"rsrp",None) is None else r.rsrp,"N/A" if unavailable or getattr(r,"rsrq",None) is None else r.rsrq,r.pass_count,r.fail_count,r.total_count,r.result,r.remark]
def _write_metadata_sheet(sheet,md,warnings,hf,font):
    from openpyxl.styles import Font,PatternFill
    sheet.append(["Field","Value"])
    for c in sheet[1]: c.fill=hf; c.font=font
    for w in warnings:
        sheet.append(["WARNING",w])
        for c in sheet[sheet.max_row]: c.fill=PatternFill("solid",fgColor="9B1C1C"); c.font=Font(bold=True,color="FFFFFF")
    for k,v in md.items():
        if k=="command_trace": continue
        rendered=json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(dict,list)) else v; sheet.append([_excel_safe_text(str(k)),_excel_safe_text(str(rendered))])
    sheet.freeze_panes="A2"; _auto_fit_columns(sheet)
def _write_trace_sheet(sheet,trace,hf,font):
    headers=["timestamp","stage","operation","command","response","success","error"]; sheet.append(headers)
    for c in sheet[1]: c.fill=hf; c.font=font
    if isinstance(trace,list):
        for e in trace:
            if isinstance(e,dict): sheet.append([_excel_safe_text(str(e.get(h,""))) for h in headers])
    sheet.freeze_panes="A2"; _auto_fit_columns(sheet)
def _excel_safe_text(v): return f"'{v}" if v.startswith(("=","+","-","@")) else v
def _excel_safe_value(v): return _excel_safe_text(v) if isinstance(v,str) else v
def _run_warnings(md):
    w=[]
    if str(md.get("data_source","")).upper()=="SIMULATION" or bool(md.get("contains_simulation_data",False)): w.append("SIMULATED DATA - 非实测结果，不得作为正式报告")
    status=str(md.get("status","")).strip().upper()
    if status and status!="COMPLETED": w.append("UNSAFE / INCOMPLETE RUN - 仪表安全清理未确认，结果无效，必须人工确认 RF 状态" if status=="FAILED_UNSAFE" else f"INCOMPLETE RUN ({status}) - 测试未正常完成，结果不得作为正式 PASS 结论")
    return w
