"""Owned, bounded AVL session; the native matrix is reused, never approximated."""
from copy import deepcopy
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from .adapters import sha256
from .aircraft_aero import avl_input, commands
from .avl_aircraft import read_solution
from .processes import launch_owned, stop_owned
from .service import write_json

FILES=('case.run','total.mrf','strips.mrf','elements.mrf','stability.mrf')


def topology(contract):
    c=deepcopy(contract)
    c['flow']['mach']=0.
    c['references']['moment_reference_geometry_m']=[0.,0.,0.]
    return avl_input(c)


class AVLSession:
    def __init__(self,executable,work,*,timeout=120,output_limit=8*1024*1024,cache=None):
        self.exe=str(executable);self.work=Path(work);self.work.mkdir(parents=True,exist_ok=False)
        self.timeout=timeout;self.limit=output_limit;self.process=None;self.owner=None
        self.messages=queue.Queue(maxsize=128);self.reader=None;self.closed=False
        self.total=0;self.count=0;self.geometry=None;self.started=time.monotonic()
        self.log=(self.work/'stdout.log').open('wb');self.status='created'
        self.exe_hash=sha256(self.exe)
        from .computation_identity import sources
        from .exact_cache import ExactCache
        self.dependencies=sources(('avl_session',))
        self.cache=ExactCache(cache,'avl') if cache is not None else None
        self.hits=0;self.misses=0

    def _reader(self):
        try:
            while data:=self.process.stdout.read1(4096):
                # A bounded queue also bounds memory if the caller is parsing outputs.
                while not self.closed:
                    try:self.messages.put(data,timeout=.1);break
                    except queue.Full:pass
                if self.closed:return
        finally:
            if not self.closed:
                try:self.messages.put(None,timeout=1)
                except queue.Full:pass

    def _exchange(self,text,*,prompts=1):
        if text:
            with (self.work/'stdin.txt').open('a',encoding='ascii') as f:f.write(text)
            self.process.stdin.write(text.encode('ascii'));self.process.stdin.flush()
        end=time.monotonic()+self.timeout;data=bytearray()
        while True:
            if time.monotonic()>end:raise TimeoutError('AVL 会话工况超时，已停止')
            try:chunk=self.messages.get(timeout=.05)
            except queue.Empty:
                if self.process.poll() is not None:raise RuntimeError('AVL 会话提前退出')
                continue
            if chunk is None:raise RuntimeError('AVL 会话输出提前关闭')
            remaining=max(0,self.limit-self.total);self.log.write(chunk[:remaining]);self.log.flush()
            self.total+=len(chunk);data.extend(chunk)
            if self.total>self.limit:raise RuntimeError('AVL 会话输出超过容量限制，已停止')
            if data.count(b'AVL   c>')>=prompts and data.rstrip().endswith(b'AVL   c>'):
                result=data.decode('utf-8',errors='replace')
                if re.search(r'not recognized|forrtl:|convergence failed',result,re.I):raise ValueError('AVL 会话命令或求解失败')
                return result

    def solve(self,contract,executable,work):
        if self.closed:raise RuntimeError('AVL 会话已关闭')
        work=Path(work);began=time.monotonic()
        try:
            if str(executable)!=self.exe or sha256(executable)!=self.exe_hash:raise ValueError('AVL 会话求解器改变')
            shape=topology(contract)
            if self.geometry is not None and shape!=self.geometry:raise ValueError('AVL 会话几何/离散改变，必须新建会话')
            self.geometry=shape
            key={'schema':1,'model':avl_input(contract),'commands':commands(contract),
                 'moment_reference_geometry_m':contract['references']['moment_reference_geometry_m'],
                 'solver':self.exe_hash,'sources':self.dependencies}
            if self.cache and self.cache.restore(key,work):
                result=read_solution(contract,executable,work,(work/'stdout.log').read_text('utf-8'))
                self.hits+=1
                write_json(work/'cache_reuse.json',{'cache_hit':True,'identity':key,'elapsed_s':time.monotonic()-began})
                return result
            first=self.process is None
            if first:
                self.geometry=shape
                (self.work/'model.avl').write_text(avl_input(contract),encoding='ascii')
                self.process,self.owner=launch_owned([self.exe],cwd=self.work,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                self.reader=threading.Thread(target=self._reader,daemon=True);self.reader.start()
                banner=self._exchange('')
                if not re.search(r'Program\s+Version\s+3\.40\b',banner):raise ValueError('AVL 会话仅支持已验证的 3.40')
            text=commands(contract).replace('LOAD model.avl\n','').removesuffix('QUIT\n')
            ref=contract['references']['moment_reference_geometry_m']
            text=text.replace('M\nMN ',f'M\nX {ref[0]}\nY {ref[1]}\nZ {ref[2]}\nMN ',1)
            if first:text='LOAD model.avl\n'+text
            prefix=f'c{self.count:05d}_'
            for name in FILES:text=text.replace(name,prefix+name)
            # LOAD returns to the main prompt before OPER starts. Wait for both
            # acknowledgements on the first call, not a timing-dependent read.
            out=self._exchange(text,prompts=2 if first else 1)
            (work/'model.avl').write_text(avl_input(contract),encoding='ascii')
            for name in FILES:shutil.copy2(self.work/(prefix+name),work/name)
            result=read_solution(contract,executable,work,'Program Version 3.40\n'+out)
            self.count+=1;self.misses+=1;self.status='running'
            (work/'stdout.log').write_text('Program Version 3.40\n'+out,encoding='utf-8')
            write_json(work/'session_call.json',{'session':str(self.work),'call':self.count,'elapsed_s':time.monotonic()-began,
                'solver_sha256':self.exe_hash,'commands':text,'matrix_reuse':'native AVL; unchanged geometry, exact Mach and explicit CG'})
            if self.cache:self.cache.publish(key,work,[*FILES,'model.avl','stdout.log','session_call.json'])
            write_json(work/'cache_reuse.json',{'cache_hit':False,'identity':key,'elapsed_s':time.monotonic()-began})
            return result
        except BaseException:
            self.status='failed';self.close();raise

    def close(self):
        if self.closed:return
        try:
            if self.process and self.process.poll() is None:
                if self.status!='failed':
                    try:
                        self.process.stdin.write(b'QUIT\n');self.process.stdin.flush();self.process.wait(timeout=3)
                    except (OSError,subprocess.TimeoutExpired):stop_owned(self.process,self.owner)
                else:stop_owned(self.process,self.owner)
            if self.status!='failed':self.status='completed'
        finally:
            self.closed=True
            if self.owner:self.owner.close()
            if self.reader:self.reader.join(timeout=2)
            self.log.close()
            write_json(self.work/'session.json',{'status':self.status,'calls':self.count,'elapsed_s':time.monotonic()-self.started,
                'solver_sha256':self.exe_hash,'observed_bytes':self.total,'stored_bytes':min(self.total,self.limit),
                'output_limit':self.limit,'truncated':self.total>self.limit,'returncode':self.process.poll() if self.process else None,
                'cache_hits':self.hits,'cache_misses':self.misses})
            from .job_events import event
            event('avl_session_finished',directory=str(self.work),calls=self.count,cache_hits=self.hits,status=self.status,
                  elapsed_s=time.monotonic()-self.started)

    def __enter__(self):return self
    def __exit__(self,*exc):
        if exc[0]:self.status='failed'
        self.close()
