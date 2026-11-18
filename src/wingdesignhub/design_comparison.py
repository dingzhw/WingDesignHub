from dataclasses import replace
"""Explicit comparison conditions; no ranking across different requirements."""
from dataclasses import dataclass,field,asdict
import hashlib
import json
from .requirements import DesignProject

PURPOSES={'design_trade':'同任务设计比较','requirements_sensitivity':'需求变化敏感性'}
MODELS={'initial':'初步总体（概念气动与推进）','coupled':'增强总体（AVL/XFOIL＋CCBlade/发动机）'}
AXES={'sizing.aspect_ratio':'机翼展弦比','assumptions.cruise_speed_m_s':'巡航真空速',
      'payload_kg':'任务载荷','mission.range_m':'主任务航程','mission.endurance_s':'主任务航时/留空时间'}


def flatten(value,prefix=''):
    result={}
    for key,item in value.items():
        path=prefix+'.'+key if prefix else key
        if isinstance(item,dict): result.update(flatten(item,path))
        else: result[path]=item
    return result


@dataclass(frozen=True)
class ComparisonRequest:
    projects: tuple
    purpose: str = 'design_trade'
    schema_version: int = 1
    analysis_model: str = 'initial'
    analysis_options: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict) or set(data)-{'projects','purpose','schema_version','analysis_model','analysis_options'}:
            raise ValueError('三方案配置字段无效')
        if not isinstance(data.get('projects'),list): raise ValueError('三方案配置需要 projects 列表')
        result=cls(tuple(DesignProject.from_dict(p) for p in data['projects']),data.get('purpose','design_trade'),data.get('schema_version',1),
                   data.get('analysis_model','initial'),data.get('analysis_options',{}))
        result.validate();return result

    def to_dict(self):
        result={'schema_version':self.schema_version,'purpose':self.purpose,'projects':[p.to_dict() for p in self.projects]}
        if self.schema_version==2:result.update(analysis_model=self.analysis_model,analysis_options=self.options_dict())
        return result

    def options_dict(self):
        if self.analysis_model=='initial':return {}
        from .propulsion_feedback import CoupledOptions
        options=asdict(CoupledOptions.from_dict(self.analysis_options))
        aero=self.analysis_options.get('aero')
        # Preserve archived pre-V0.3.2 definitions; a new execution expands its
        # defaults explicitly before creating the new run and confirmation hash.
        if isinstance(aero,dict) and aero and 'execution_mode' not in aero:
            options['aero'].pop('execution_mode')
        return options

    def definition_hash(self):
        value={'purpose':self.purpose,'schema_version':self.schema_version,'definitions':[p.definition_hash() for p in self.projects]}
        if self.schema_version==2:value.update(analysis_model=self.analysis_model,analysis_options=self.options_dict())
        return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

    def differences(self):
        base=flatten(self.projects[0].to_dict());rows=[]
        for i,p in enumerate(self.projects[1:],1):
            other=flatten(p.to_dict())
            for key in sorted(base.keys()|other.keys()):
                if key not in ('name','confirmation_sha256') and base.get(key)!=other.get(key):
                    rows.append({'scheme':i,'field':key,'base':base.get(key),'value':other.get(key)})
        return rows

    def validate(self):
        if type(self.schema_version) is not int or self.schema_version not in (1,2) or self.purpose not in PURPOSES:
            raise ValueError('三方案配置版本或用途无效')
        if self.analysis_model not in MODELS or not isinstance(self.analysis_options,dict):raise ValueError('比较分析模型或选项无效')
        if self.schema_version==1 and (self.analysis_model!='initial' or self.analysis_options):raise ValueError('增强比较需要配置版本 2')
        if self.analysis_model=='initial' and self.analysis_options:raise ValueError('初步模型不接受增强分析选项')
        self.options_dict()
        if len(self.projects)!=3 or any(not isinstance(p,DesignProject) for p in self.projects):
            raise ValueError('每次比较必须有三个飞机方案')
        for p in self.projects:p.check_schema()
        if len({p.name for p in self.projects})!=3:raise ValueError('三个方案名称须不同')
        allowed=({'sizing.aspect_ratio','assumptions.cruise_speed_m_s'} if self.purpose=='design_trade'
                 else {'payload_kg','mission.range_m','mission.endurance_s'})
        physical={d['field'] for d in self.differences() if '.sources.' not in d['field'] and d['field']!='sizing.source'}
        if not physical<=allowed:
            raise ValueError('比较条件不一致；本用途允许变化：'+', '.join(AXES[x] for x in sorted(allowed)))
        if len(physical)!=1:raise ValueError('一次选择一个变化参数，以便解释原因；三个取值至少有两个不同')
        return self


def check_record(request,project,record):
    mode='overall_propulsion' if request.analysis_model=='coupled' else 'overall_sizing'
    # An initial calculation that cannot seed the enhanced solver remains a diagnostic only.
    blocked=(request.analysis_model=='coupled' and record.get('mode')=='overall_sizing'
             and not record.get('summary',{}).get('converged'))
    if (record.get('mode')!=mode and not blocked) or record.get('definition_sha256')!=project.definition_hash():
        raise ValueError('总体运行与方案定义或分析模型不匹配')
    if record.get('status')=='running':raise ValueError('运行尚未完成，不能重复启动或比较')
    if not record.get('version') or not record.get('source_hashes'):raise ValueError('总体运行缺少版本或源码证据')
    identity=record.get('calculation_identity')
    if identity and any(record['source_hashes'].get(n)!=h for n,h in identity['sources'].items()):
        raise ValueError('计算身份与源码审计记录不一致，拒绝比较')
    if mode=='overall_propulsion' and not blocked and record.get('options')!=request.options_dict():
        raise ValueError('增强分析选项不一致，请使用共同设置重新计算')
    return blocked


def summarize_comparison(request,records):
    from .design_cards import make_card
    request.validate()
    if len(records)!=3:raise ValueError('比较需要三个运行记录')
    for p,r in zip(request.projects,records):
        check_record(request,p,r)
    from .computation_identity import comparison_compatible
    if not comparison_compatible(records):
        raise ValueError('软件版本或源码不同，请使用同一模型重新计算后比较')
    computed=[r['summary'] for r in records if 'geometry' in r.get('summary',{})
              and (request.analysis_model=='initial' or r['mode']=='overall_propulsion')]
    if any(not s.get('versions') for s in computed) or len({json.dumps(s['versions'],sort_keys=True) for s in computed})>1:
        raise ValueError('求解器版本缺失或不同，拒绝比较')
    if any(not s.get('model_signature') for s in computed) or len({s['model_signature'] for s in computed})>1:
        raise ValueError('上游模型/数据证据缺失或不同，请重新计算后比较')
    cards=[make_card(p,r) for p,r in zip(request.projects,records)]
    for card,r in zip(cards,records):
        if request.analysis_model=='coupled' and r['mode']=='overall_sizing':
            card.update(eligible=False,converged=False,geometry=None,metrics={k:None for k in card['metrics']})
            card['diagnostics'].append('初步总体未提供已收敛初值，增强闭环未执行。')
    deltas=[]
    for i,card in enumerate(cards):
        # Failed/unconverged outputs are never filled with zeros or used as a ranking input.
        values={}
        if cards[0]['eligible'] and card['eligible']:
            for key,value in card['metrics'].items():
                base=cards[0]['metrics'][key]
                if value is not None and base is not None:
                    values[key]={'absolute':value-base,'relative':None if abs(base)<1e-12 else (value-base)/abs(base)}
        deltas.append({'scheme':i,'against':0,'values':values})
    eligible=[i for i,c in enumerate(cards) if c['eligible']]
    result={'status':'compared_with_limits' if len(eligible)==3 else 'comparison_incomplete',
            'purpose':request.purpose,'differences':request.differences(),'cards':cards,'deltas':deltas,
            'eligible_schemes':eligible,'ranking':None,
            'interpretation':('在相同任务和约束下查看重量、功率、燃油的取舍；当前证据不足以自动选出综合最优方案。'
                if request.purpose=='design_trade' else '需求变化的代价与响应；不同任务负担不用于设计优劣排名。'),
            'physical_validation_passed':False}
    if request.schema_version==2:result.update(analysis_model=request.analysis_model,analysis_label=MODELS[request.analysis_model],analysis_options=request.options_dict())
    return result


def variants(base,axis,values):
    plans=[]
    for i,value in enumerate(values):
        name=f'{base.name} · {"ABC"[i]}'
        if '.' in axis:
            group,field=axis.split('.')
            p=replace(base,name=name,**{group:replace(getattr(base,group),**{field:value})},confirmation_sha256=None)
        else:p=replace(base,name=name,**{axis:value},confirmation_sha256=None)
        plans.append(p)
    purpose='design_trade' if axis in ('sizing.aspect_ratio','assumptions.cruise_speed_m_s') else 'requirements_sensitivity'
    return ComparisonRequest(tuple(plans),purpose).validate()
