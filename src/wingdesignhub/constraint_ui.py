"""User-facing units and four-state labels; leave stored engineering values intact."""
import streamlit as st
from .constraint_states import display_rows


def render(summary,p=None):
    rows=display_rows(summary,p)
    for row in rows:
        factor,unit={'W':(.001,'kW'),'MAC':(100.,'% MAC'),'fraction':(100.,'%')}.get(row['单位'],(1.,row['单位']))
        def fmt(value):
            if value is None:return '—'
            if isinstance(value,(list,tuple)):return ' ～ '.join(fmt(v) for v in value)
            return f'{value*factor:.4g}' if isinstance(value,(int,float)) else str(value)
        for key in ('计算值','限值','余量'):row[key]=fmt(row[key])
        row['单位']=unit
    st.dataframe(rows,hide_index=True)
