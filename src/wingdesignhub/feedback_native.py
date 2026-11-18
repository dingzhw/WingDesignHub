"""Native trials for the existing overall iteration; never forge a converged parent."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json
import math
import shutil
import sys
from .adapters import execute, sha256, tool_paths
from .aircraft_geometry import build_geometry_contract
from .aircraft_aero import make_contract, AeroOptions
from .aircraft_trim import solve_trim, TrimOptions
from .aircraft_drag import solve_drag
from .service import write_json


class NativeFeedbackGeometry:
    def __init__(self,root,work,project,geo,cg,design_mass,drag_options,*,execution_mode='reuse'):
        self.root=Path(root);self.work=Path(work);self.p=project;self.geo=geo
        self.drag_options=drag_options;self.design_mass=design_mass;self.prepared=None;self.points=[]
        self.execution_mode=execution_mode;self.session=None
        self.work.mkdir(parents=True,exist_ok=False);self.geometry_work=self.work/'geometry';self.geometry_work.mkdir()
        write_json(self.work/'input.json',project.to_dict())
        record={'run_id':self.work.name,'mode':'overall_trial','status':'trial',
                'input_hash':sha256(self.work/'input.json'),'definition_sha256':project.definition_hash(),
                'summary':{'geometry':geo,'cg':{'cg_x_m':cg},'converged':False,'status':'trial'}}
        contract=build_geometry_contract(project,record,trial=True)
        contract['limits']=['内部总体迭代试算外形；最终总体收敛与气动检查独立记录。',*contract['limits'][1:5]]
        write_json(self.geometry_work/'geometry_contract.json',contract)
        from .computation_identity import sources,environment
        from .exact_cache import ExactCache
        cache=ExactCache(self.root/'local/cache/computation','geometry')
        identity={'contract':{k:v for k,v in contract.items() if k not in ('parent_run_id','parent_input_hash','definition_sha256','name')},
                  'sources':sources(('aircraft_vsp_worker',)),'environment':environment(root,'geometry')}
        hit=execution_mode=='reuse' and cache.restore(identity,self.geometry_work)
        if not hit:
            execute([sys.executable,'-X','utf8','-m','wingdesignhub.aircraft_vsp_worker',str(self.geometry_work)],self.geometry_work,timeout=180)
        geom=json.loads((self.geometry_work/'summary.json').read_text('utf-8'))
        if not geom['passed']:raise ValueError('总体试算几何检查失败')
        if not hit and execution_mode=='reuse':
            cache.publish(identity,self.geometry_work,[p.relative_to(self.geometry_work).as_posix() for p in self.geometry_work.rglob('*')
                if p.is_file() and p.name!='geometry_contract.json'])
        write_json(self.geometry_work/'cache_reuse.json',{'cache_hit':hit,'identity':identity})
        self.interface=json.loads((self.geometry_work/'aerodynamic_geometry.json').read_text('utf-8'))
        # Cached numerical geometry is rebound to this trial's explicit provenance.
        self.interface.update(source_run_id=self.geometry_work.name,parent_run_id=contract['parent_run_id'])
        geom.update(parent_run_id=contract['parent_run_id'],parent_status=contract['parent_status'])
        write_json(self.geometry_work/'aerodynamic_geometry.json',self.interface);write_json(self.geometry_work/'summary.json',geom)
        if hit:
            from .geometry_report import write_geometry_report
            write_geometry_report(self.geometry_work,contract,geom)
        self.tools=tool_paths(root)

    def batch(self,requests):
        """Exact Mach grouping only changes scheduling; output retains request order."""
        if self.execution_mode=='native_audit':return [self(*r) for r in requests]
        from .avl_session import AVLSession
        def mach(r):return r[2]/math.sqrt(1.4*287.05287*(288.15-.0065*r[3]))
        answers={}
        with AVLSession(self.tools['avl'],self.work/'avl_session',cache=self.root/'local/cache/computation') as session:
            self.session=session
            try:
                for i in sorted(range(len(requests)),key=lambda i:mach(requests[i])):answers[i]=self(*requests[i])
            finally:self.session=None
        return [answers[i] for i in range(len(requests))]

    def __call__(self,mass,cg,speed,altitude,roc):
        work=self.work/f'point_{len(self.points):03d}';work.mkdir()
        from .job_events import event
        event('aero_point',directory=str(work),mass_kg=mass,speed_m_s=speed,altitude_m=altitude,roc_m_s=roc)
        gamma=math.asin(roc/speed)
        if abs(gamma)>math.radians(10):raise ValueError('任务航迹角超过 ±10° 的定常模型范围')
        options=TrimOptions(mass_state='explicit',mass_kg=mass,cg_x_m=cg,source_note='overall trial dry-mass ledger plus remaining fuel',
                            speed_m_s=speed,altitude_m=altitude)
        contract=deepcopy(make_contract(self.interface,self.p,{'design_mtow_kg':self.design_mass},
                         AeroOptions(speed_m_s=speed,altitude_m=altitude,mass_kg=mass),trial=True))
        contract['geometry_references']=deepcopy(contract['references'])
        contract['references']['moment_reference_geometry_m']=[cg,0.,0.]
        contract['references']['reference_source']='mission fuel-state CG, conceptual dry component stations'
        contract['coordinates']['body_origin_geometry_m']=[cg,0.,0.]
        state={'operating_mass_kg':mass,'cg_geometry_m':[cg,0.,0.],
               'design_mtow_kg':self.design_mass,'mass_state':'overall_trial','source':options.source_note,
               'flight_path_angle_deg':math.degrees(gamma),'thrust_model':'along flight path through CG; no slipstream or propulsive moment'}
        contract['flow'].update(normal_weight_factor=math.cos(gamma),flight_path_angle_deg=math.degrees(gamma))
        contract.update(flight_state=state,trim_options=asdict(options),model='mission_lifting_surface_trim_v1')
        write_json(work/'trim_contract.json',contract)
        trim=solve_trim(contract,self.tools['avl'],work,solver=self.session.solve if self.session else None)
        write_json(work/'trim_summary.json',trim)
        if not trim['trim']['converged']:
            from .aero_feedback import FeedbackError
            raise FeedbackError(trim['status'],trim['trim']['diagnostic'],point=work.name,mass_kg=mass,cg_x_m=cg,
                                speed_m_s=speed,altitude_m=altitude,roc_m_s=roc)
        final=json.loads((work/'final_aero_contract.json').read_text('utf-8'))
        drag={'options':asdict(self.drag_options),'flow':final['flow'],'references':final['references'],
              'flight_state':state,'trim_options':final['options'],'induced_cd':trim['coefficients']['CDff'],
              'lift_coefficient':trim['coefficients']['CLtot'],
              'correction_source':'uncalibrated user-visible conceptual allowances; no aircraft fit'}
        write_json(work/'drag_contract.json',drag)
        shutil.copy2(work/'strip_loads.json',work/'trim_strip_loads.json')
        for name in ('aircraft.vsp3','geometry_contract.json'):shutil.copy2(self.geometry_work/name,work/name)
        result=solve_drag(drag,work,self.root,self.tools['xfoil'],prepared_geometry=self.prepared,polar_workers=3,
                          use_geometry_cache=self.execution_mode=='reuse')
        write_json(work/'drag_summary.json',result)
        if self.prepared is None:self.prepared=work
        point={'mass_kg':mass,'cg_x_m':cg,'speed_m_s':speed,'altitude_m':altitude,'roc_m_s':roc,
               'cd':result['ledger']['cd_total'],'components':result['components'],
               'strut_cd':sum(row['cd'] for row in result['ledger']['rows'] if row['component'].endswith('Strut')),
               'alpha_deg':trim['trim']['alpha_deg'],'elevator_deg':trim['trim']['elevator_deg'],
               'residual_cl':trim['trim']['residual_cl'],'residual_cm':trim['trim']['residual_cm'],
               'point_directory':work.name,'polar_coverage':result['polar_coverage']}
        self.points.append(point);write_json(self.work/'points.json',self.points)
        print('native point',self.work.name,work.name,round(mass,2),round(speed,2),round(altitude,1),round(point['cd'],6),flush=True)
        return point

    def evidence(self):
        return {'directory':self.work.name,'points':len(self.points),'geometry_sha256':sha256(self.geometry_work/'aircraft.vsp3'),
                'avl_sha256':sha256(self.tools['avl']),'xfoil_sha256':sha256(self.tools['xfoil'])}
