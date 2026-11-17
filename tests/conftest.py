"""Existing result-rendering tests use immediate services as a deterministic queue double.

The real persisted queue, polling, cancellation and reconnection are exercised by
test_jobs/test_job_ui and native release validation. No native background work is
started accidentally by the result/archive regression suite.
"""
import importlib
import pytest


@pytest.fixture(autouse=True)
def immediate_ui_jobs(request,monkeypatch):
    if request.path.name not in {'test_design_ui.py','test_design_workflow.py','test_aircraft_geometry.py',
        'test_aircraft_aero.py','test_aircraft_trim.py','test_aircraft_drag.py','test_comparison.py',
        'test_feedback_service.py','test_propulsion_service.py','test_coupled_service.py','test_enhanced_comparison.py'}:return
    from wingdesignhub import job_ui
    monkeypatch.setattr(job_ui.jobs,'list_jobs',lambda root:[])
    entries={
        'size':('sizing_service','run_sizing','sizing_result'),
        'fastga_reference':('design_service','run_fastga_reference','design_reference_result'),
        'compare':('comparison_service','run_comparison','comparison_result'),
        'geometry':('geometry_service','run_aircraft_geometry','aircraft_geometry_result'),
        'aero':('aero_ui','run_aircraft_aero','aircraft_aero_result'),
        'trim':('trim_ui','run_aircraft_trim','aircraft_trim_result'),
        'drag':('drag_ui','run_aircraft_drag','aircraft_drag_result'),
        'feedback':('feedback_ui','run_aero_feedback','aero_feedback_result'),
        'propulsion':('propulsion_ui','run_propulsion','propulsion_result'),
        'coupled':('coupled_ui','run_coupled','coupled_result')}
    def submit(root,kind,project=None,parent_run_id=None,options=None):
        import streamlit as st
        mod,name,key=entries[kind];fn=getattr(importlib.import_module('wingdesignhub.'+mod),name)
        if kind=='fastga_reference':result=fn(root)
        elif kind in ('size','compare'):result=fn(project,root)
        elif kind=='geometry':result=fn(project,root,parent_run_id)
        else:result=fn(project,root,parent_run_id,options)
        # Result-focused tests omit optional mode/version fields in their small doubles.
        if kind=='size':result.setdefault('mode','overall_sizing')
        st.session_state[key]=result
        return result
    monkeypatch.setattr(job_ui,'submit',submit)
