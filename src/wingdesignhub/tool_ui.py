import json
from pathlib import Path
import streamlit as st
from .adapters import inventory,tool_paths


def render(root):
    st.subheader('本机计算工具')
    st.caption('路径配置、原生导入检查与工程验证分别记录；本页不安装或修改已有软件环境。')
    st.dataframe([{'工具':k,**v} for k,v in inventory(root).items()],hide_index=True)
    local=Path(root)/'local';path=local/'propulsion-tools.json'
    cfg=json.loads(path.read_text('utf-8')) if path.exists() else {}
    with st.form('tools'):
        labels={'avl':'AVL 程序路径','xfoil':'XFOIL 程序路径','openvsp':'OpenVSP 安装目录','calculix':'CalculiX 2.23 程序路径'}
        config={k:st.text_input(labels[k],v) for k,v in tool_paths(root).items()}
        propulsion={k:st.text_input(label,cfg.get(k,'')) for k,label in [('julia','Julia 程序路径'),('project','已安装 CCBlade 的 Julia 项目目录'),('package','CCBlade 1.0.0 包目录')]}
        if st.form_submit_button('保存本机路径'):
            from .jobs import atomic
            local.mkdir(exist_ok=True)
            atomic(local/'tools.json',config);atomic(path,propulsion)
            st.success('路径已保存；运行前继续核查文件、版本与实际加载的包。')
    if st.button('检查 Julia 与 CCBlade 实际加载',key='check_ccblade'):
        from .job_ui import submit
        submit(root,'tools')
