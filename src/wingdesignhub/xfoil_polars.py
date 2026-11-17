"""Bounded, auditable XFOIL 6.99 polars. Missing points are never interpolated away."""
from dataclasses import asdict, dataclass, replace
from pathlib import Path
import hashlib
import json
import math
import re
import shutil
import numpy as np
from .adapters import execute, sha256
from .service import write_json


class PolarError(ValueError):
    def __init__(self, status, message, **context):
        super().__init__(message)
        self.status = status
        self.context = context


@dataclass(frozen=True)
class PolarSpec:
    reynolds: float
    mach: float
    cl_grid: tuple
    ncrit: float = 9.
    trip_top: float = 1.
    trip_bottom: float = 1.
    flap_deg: float = 0.
    hinge_xc: float = .7
    panels: int = 160

    def validate(self):
        values = [self.reynolds, self.mach, self.ncrit, self.trip_top,
                  self.trip_bottom, self.flap_deg, self.hinge_xc, *self.cl_grid]
        if not np.isfinite(values).all():
            raise PolarError('polar_invalid', '极曲线条件含非有限数值')
        if not 2e5 <= self.reynolds <= 2e7 or not 0 <= self.mach <= .3 or any(abs(x) > 1.2 for x in self.cl_grid):
            raise PolarError('polar_out_of_domain', 'XFOIL 接口范围：Re 20万–2000万、Mach≤0.3、|cl|≤1.2', conditions=asdict(self))
        if (not 1 <= self.ncrit <= 14 or not 0 < self.trip_top <= 1 or not 0 < self.trip_bottom <= 1 or
                abs(self.flap_deg) > 10 or not .5 <= self.hinge_xc < 1 or self.panels not in (160, 240, 280, 320, 360, 400)):
            raise PolarError('polar_invalid', '转捩、舵偏、铰链或面元条件无效')
        if not self.cl_grid or len(self.cl_grid) > 51 or list(self.cl_grid) != sorted(set(self.cl_grid)):
            raise PolarError('polar_invalid', 'cl 网格须有序、唯一且不超过 51 点')


def commands(spec, warm_start=None):
    spec.validate()
    text = 'PLOP\nG\n\nLOAD foil.dat\n'
    if spec.flap_deg:
        text += f'GDES\nFLAP\n{spec.hinge_xc}\n0.0\n{spec.flap_deg:.15g}\nEXEC\n\n'
    text += (f'PPAR\nN {spec.panels}\n\n\nPANE\nPSAV analyzed_foil.dat\nOPER\n'
             f'VISC {spec.reynolds:.15g}\nMACH {spec.mach:.15g}\nITER 200\n'
             f'VPAR\nN {spec.ncrit}\nXTR {spec.trip_top} {spec.trip_bottom}\n\n')
    if warm_start is not None:text+=f'CL {warm_start:.10g}\n'
    text+='PACC\npolar.txt\n\n'
    # Start near zero; each sign proceeds outward, with an explicit BL restart.
    groups = [sorted(x for x in spec.cl_grid if x >= 0), sorted((x for x in spec.cl_grid if x < 0), reverse=True)]
    for i, group in enumerate(groups):
        if i and group and groups[0]:text += 'INIT\n'
        text += ''.join(f'CL {cl:.10g}\n' for cl in group)
    return text + 'PACC\n\nQUIT\n'


def parse_polar(text, spec, *, allow_missing=False):
    spec.validate()
    version = re.search(r'XFOIL\s+Version\s+(\S+)', text)
    conditions = re.search(r'Mach\s*=\s*([\d.]+)\s+Re\s*=\s*([\d.]+)\s*e\s*([+-]?\d+)\s+Ncrit\s*=\s*([\d.]+)', text)
    trips = re.search(r'xtrf\s*=\s*([\d.]+)\s*\(top\)\s*([\d.]+)\s*\(bottom\)', text)
    if not version or version[1] != '6.99' or not conditions or not trips or 'Reynolds number fixed' not in text or 'Mach number fixed' not in text:
        raise PolarError('polar_invalid', 'XFOIL 版本或固定 Re/Mach 极曲线头不完整')
    actual = [float(conditions[1]), float(conditions[2])*10**int(conditions[3]), float(conditions[4]), float(trips[1]), float(trips[2])]
    expected = [spec.mach, spec.reynolds, spec.ncrit, spec.trip_top, spec.trip_bottom]
    # XFOIL writes Mach/trips to .001 and Re mantissa to .001e6.
    if any(abs(a-b) > tol for a,b,tol in zip(actual, expected, [.000501, 501., .000501, .000501, .000501])):
        raise PolarError('polar_invalid', '极曲线条件读回与请求不符', actual=actual, expected=expected)
    rows = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 7:continue
        try:values = list(map(float, fields))
        except ValueError:continue
        if not np.isfinite(values).all() or values[2] <= 0:
            raise PolarError('polar_invalid', '极曲线存在非有限数值或非正阻力')
        rows.append(dict(zip(('alpha_deg','cl','cd','cd_pressure','cm','transition_top','transition_bottom'), values)))
    ordered = [];missing=[]
    for target in spec.cl_grid:
        matches = [r for r in rows if abs(r['cl']-target) <= .000051]
        if not matches and allow_missing:
            missing.append(target);continue
        if len(matches) != 1:
            raise PolarError('polar_missing', 'XFOIL 未提供唯一收敛点，禁止跨缺点插值', cl=target, reynolds=spec.reynolds, found=len(matches))
        ordered.append({**matches[0], 'requested_cl': target})
    if len(rows) != len(ordered):raise PolarError('polar_invalid', '极曲线含未请求点或重复点')
    result={'solver_version':version[1], 'condition_readback':actual, 'rows':ordered}
    if allow_missing:result['missing_cl']=missing
    return result


def read_attempts(work,spec):
    """Reconstruct every accepted point from an original solver output, including recovery."""
    work=Path(work)
    if not (work/'recovery.json').is_file():return parse_polar((work/'polar.txt').read_text('utf-8'),spec)
    result=parse_polar((work/'polar.txt').read_text('utf-8'),spec,allow_missing=True)
    recovery=json.loads((work/'recovery.json').read_text('utf-8'))
    missing=result.pop('missing_cl')
    if not missing or len(missing)>3 or [r['cl'] for r in recovery]!=missing:
        raise PolarError('polar_invalid','极曲线恢复清单与原始缺点不符')
    for i,item in enumerate(recovery):
        attempts=item.get('attempts',[{'directory':f'recovery_{i}','panels':spec.panels}])
        allowed={f'recovery_{i}':spec.panels,f'recovery_{i}_direct':spec.panels,
                 **{f'recovery_{i}_mesh_{n}':n for n in (280,320,360,400) if n>spec.panels}}
        if (not attempts or len(attempts)>6 or len({a['directory'] for a in attempts})!=len(attempts) or
            any(allowed.get(a['directory'])!=a['panels'] for a in attempts) or item['directory']!=attempts[-1]['directory']):
            raise PolarError('polar_invalid','恢复目录或面元记录无效')
        single=replace(spec,cl_grid=(item['cl'],),panels=attempts[-1]['panels'])
        parsed=parse_polar((work/item['directory']/'polar.txt').read_text('utf-8'),single)
        result['rows'].extend(parsed['rows'])
    result['rows'].sort(key=lambda r:r['requested_cl']);result['recovery']=recovery
    return result


def run_polar(foil, spec, executable, work, cache=None, cache_only=False):
    """An immutable local cache; every child retains raw inputs, logs and readback."""
    spec.validate();foil=Path(foil);executable=Path(executable);work=Path(work)
    if not foil.is_file():raise PolarError('polar_missing', '翼型坐标文件缺失', foil=str(foil))
    if not executable.is_file():raise PolarError('polar_missing', 'XFOIL 可执行文件缺失，请检查工具配置')
    identity={'spec':asdict(spec), 'foil_sha256':sha256(foil), 'solver_sha256':sha256(executable), 'adapter_sha256':sha256(Path(__file__))}
    identity=json.loads(json.dumps(identity));key=hashlib.sha256(json.dumps(identity,sort_keys=True,allow_nan=False).encode()).hexdigest()
    stored=Path(cache)/key if cache is not None else None
    work.mkdir(parents=True,exist_ok=False)
    if stored is not None and stored.exists():
        try:
            manifest=json.loads((stored/'cache.json').read_text('utf-8'))
            if manifest['identity']!=identity:raise ValueError('缓存键不一致')
            raw={'foil.dat','polar.txt','analyzed_foil.dat','command.json','stdin.txt','stdout.log'}
            required=raw|{'parsed.json'}
            if 'recovery.json' in manifest['files']:
                recovery=json.loads((stored/'recovery.json').read_text('utf-8'))
                if not 1<=len(recovery)<=3:raise ValueError('恢复次数无效')
                required|={'recovery.json'}|{a['directory']+'/'+n for i,r in enumerate(recovery)
                    for a in r.get('attempts',[{'directory':f'recovery_{i}'}]) for n in raw}
                # Validate directory names before using any manifest path.
                read_attempts(stored,spec)
            if set(manifest['files'])!=required:raise ValueError('缓存文件清单无效')
            if any(not (stored/n).is_file() or sha256(stored/n)!=h for n,h in manifest['files'].items()):raise ValueError('缓存文件哈希不符')
            parsed=read_attempts(stored,spec)
            if parsed!=json.loads((stored/'parsed.json').read_text('utf-8')):raise ValueError('缓存解析结果不符')
            for n in required:
                (work/n).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stored/n,work/n)
        except (KeyError,ValueError,OSError) as exc:
            raise PolarError('polar_invalid', '极曲线缓存损坏：'+str(exc), cache_key=key) from exc
        hit=True
    else:
        if cache_only:raise PolarError('polar_missing', '当前条件没有已验证极曲线缓存', cache_key=key, conditions=identity['spec'])
        shutil.copy2(foil,work/'foil.dat')
        try:execute([str(executable)],work,stdin=commands(spec),timeout=60)
        except (RuntimeError,OSError) as exc:raise PolarError('polar_failed', 'XFOIL 运行失败或超时：'+str(exc), conditions=identity['spec']) from exc
        if not (work/'polar.txt').is_file():raise PolarError('polar_missing', 'XFOIL 未输出极曲线', conditions=identity['spec'])
        partial=parse_polar((work/'polar.txt').read_text('utf-8'),spec,allow_missing=True)
        missing=partial['missing_cl'];recovery=[]
        if len(missing)>3:raise PolarError('polar_missing','极曲线超过三处缺点，停止恢复', missing_cl=missing, reynolds=spec.reynolds)
        for i,target in enumerate(missing):
            good=[r['requested_cl'] for r in partial['rows']]
            opposite=[x for x in good if x>target] if target>=0 else [x for x in good if x<target]
            # At a grid endpoint, approach from the other side too. The seed is
            # initialization only, never an accepted or interpolated polar point.
            seed=min(opposite,key=lambda x:abs(x-target)) if opposite else max(-1.2,min(1.2,target+(.1 if target>=0 else -.1)))
            attempts=[]
            plan=[(f'recovery_{i}',spec.panels,seed),
                  *[(f'recovery_{i}_mesh_{n}',n,seed) for n in (280,320) if n>spec.panels],
                  (f'recovery_{i}_direct',spec.panels,None),
                  *[(f'recovery_{i}_mesh_{n}',n,None) for n in (360,400) if n>spec.panels]]
            # A failed warm seed can contaminate all panel retries. One independent
            # direct target starts without that boundary-layer state, at base density.
            # Only after existing recovery fails, refine with two bounded independent
            # starts. Transition/BL discretization can oscillate on 240--320 panels.
            # Reynolds, Mach, foil/flap, transition and requested CL stay identical.
            for name,panels,start in plan:
                directory=work/name;directory.mkdir();shutil.copy2(foil,directory/'foil.dat')
                single=replace(spec,cl_grid=(target,),panels=panels)
                try:execute([str(executable)],directory,stdin=commands(single,warm_start=start),timeout=60)
                except (RuntimeError,OSError) as exc:raise PolarError('polar_failed','缺点恢复失败：'+str(exc),cl=target,reynolds=spec.reynolds) from exc
                attempts.append({'directory':name,'panels':panels})
                try:
                    if not (directory/'polar.txt').is_file():raise PolarError('polar_missing','缺点恢复未输出极曲线')
                    parse_polar((directory/'polar.txt').read_text('utf-8'),single);break
                except PolarError as exc:
                    if exc.status!='polar_missing' or name==plan[-1][0]:
                        exc.context.update(cl=target,reynolds=spec.reynolds,attempts=attempts);raise
            recovery.append({'cl':target,'warm_start_cl':seed,'directory':directory.name,'attempts':attempts,
                'policy':'opposite-side seed; refinement 280/320; independent base target; final independent refinement 360/400; unchanged physical inputs, first converged point only'})
        if recovery:write_json(work/'recovery.json',recovery)
        parsed=read_attempts(work,spec)
        if not (work/'analyzed_foil.dat').is_file():raise PolarError('polar_invalid', '缺少实际分析翼型读回')
        write_json(work/'parsed.json',parsed);hit=False
        manifest={'identity':identity,'files':{p.relative_to(work).as_posix():sha256(p) for p in work.rglob('*') if p.is_file()}}
        if stored is not None:
            # Publish the manifest last. This also works on Windows workspaces that
            # permit ordinary writes but disallow directory renames.
            stored.parent.mkdir(parents=True,exist_ok=True)
            try:stored.mkdir()
            except FileExistsError:pass  # another writer; never overwrite it
            else:
                for n in manifest['files']:
                    (stored/n).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(work/n,stored/n)
                write_json(stored/'cache.json',manifest)
    write_json(work/'cache.json',{**manifest,'cache_key':key,'cache_hit':hit})
    return {**parsed,'reynolds':spec.reynolds,'cl_grid':list(spec.cl_grid),'cache_key':key,'cache_hit':hit}


def interpolate(polars, reynolds, cl):
    """Bilinear cl/log(Re), no extrapolation and no missing-cell repair."""
    if not polars:raise PolarError('polar_missing','没有可供查询的极曲线')
    polars=sorted(polars,key=lambda p:p['reynolds']);res=[p['reynolds'] for p in polars]
    if not math.isfinite(reynolds) or not math.isfinite(cl) or reynolds < res[0]*(1-1e-12) or reynolds > res[-1]*(1+1e-12):
        raise PolarError('polar_out_of_domain','条带雷诺数超出极曲线覆盖范围', reynolds=reynolds, bounds=res)
    index=int(np.searchsorted(res,reynolds));a=max(0,index-1);b=min(index,len(res)-1)
    def at(p):
        grid=np.array(p['cl_grid']);rows=p['rows']
        if cl < grid[0]-1e-12 or cl > grid[-1]+1e-12:raise PolarError('polar_out_of_domain','条带 cl 超出极曲线覆盖范围', cl=cl, bounds=[float(grid[0]),float(grid[-1])])
        if len(rows)!=len(grid) or any(abs(r['requested_cl']-x)>1e-10 for r,x in zip(rows,grid)):
            raise PolarError('polar_missing','极曲线网格含缺失点，禁止跨缺点插值')
        return {k:float(np.interp(cl,grid,[r[k] for r in rows])) for k in ('cd','cm','alpha_deg')}
    x,y=at(polars[a]),at(polars[b]);f=0. if a==b else (math.log(reynolds)-math.log(res[a]))/(math.log(res[b])-math.log(res[a]))
    return {k:x[k]*(1-f)+y[k]*f for k in x}
