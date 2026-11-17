"""Own one process tree. Windows jobs close descendants even if the owner dies."""
import os
import signal
import subprocess
import time
import psutil


def identity(pid):
    p = psutil.Process(pid)
    return {'pid': pid, 'created': p.create_time()}


def matching_process(saved):
    if not saved:
        return None
    try:
        p = psutil.Process(saved['pid'])
        return p if abs(p.create_time() - saved['created']) < .001 and p.status() != psutil.STATUS_ZOMBIE else None
    except psutil.AccessDenied as exc:
        raise PermissionError('无法核查任务进程身份；请用启动任务的本机账户查看。') from exc
    except (psutil.NoSuchProcess, KeyError):
        return None


class ProcessOwner:
    def __init__(self):
        self.handle = None
        self.process = None
        if os.name == 'nt':
            import ctypes as c
            from ctypes import wintypes as w
            class Basic(c.Structure):
                _fields_ = [('user',c.c_longlong),('job',c.c_longlong),('flags',w.DWORD),
                    ('minws',c.c_size_t),('maxws',c.c_size_t),('active',w.DWORD),
                    ('affinity',c.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
            class IO(c.Structure):
                _fields_ = [(n,c.c_ulonglong) for n in ('read','write','other','readbytes','writebytes','otherbytes')]
            class Extended(c.Structure):
                _fields_ = [('basic',Basic),('io',IO),('process_memory',c.c_size_t),
                    ('job_memory',c.c_size_t),('peak_process',c.c_size_t),('peak_job',c.c_size_t)]
            self.api = c.WinDLL('kernel32',use_last_error=True)
            signatures = {
                'CreateJobObjectW': ([c.c_void_p,w.LPCWSTR],w.HANDLE),
                'SetInformationJobObject': ([w.HANDLE,c.c_int,c.c_void_p,w.DWORD],w.BOOL),
                'QueryInformationJobObject': ([w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.c_void_p],w.BOOL),
                'IsProcessInJob': ([w.HANDLE,w.HANDLE,c.POINTER(w.BOOL)],w.BOOL),
                'AssignProcessToJobObject': ([w.HANDLE,w.HANDLE],w.BOOL),
                'TerminateJobObject': ([w.HANDLE,w.UINT],w.BOOL),
                'CloseHandle': ([w.HANDLE],w.BOOL),
                'OpenProcess': ([w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
                'OpenThread': ([w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
                'ResumeThread': ([w.HANDLE],w.DWORD),
            }
            for name,(args,result) in signatures.items():
                getattr(self.api,name).argtypes = args
                getattr(self.api,name).restype = result
            self.handle = self.api.CreateJobObjectW(None,None)
            if not self.handle:
                raise c.WinError(c.get_last_error())
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.api.SetInformationJobObject(self.handle,9,c.byref(limits),c.sizeof(limits)):
                self.close()
                raise c.WinError(c.get_last_error())

    def attach_and_resume(self, process):
        self.process = process
        self.saved = identity(process.pid)
        if os.name != 'nt':
            return
        import ctypes as c
        handle = self.api.OpenProcess(0x0100 | 0x0001,False,process.pid)
        if not handle:
            raise c.WinError(c.get_last_error())
        try:
            if not self.api.AssignProcessToJobObject(self.handle,handle):
                raise c.WinError(c.get_last_error())
        finally:
            self.api.CloseHandle(handle)
        # The newly created process is suspended: no descendant can escape before assignment.
        for thread in psutil.Process(process.pid).threads():
            th = self.api.OpenThread(0x0002,False,thread.id)
            if not th:
                raise c.WinError(c.get_last_error())
            try:
                if self.api.ResumeThread(th) == 0xffffffff:
                    raise c.WinError(c.get_last_error())
            finally:
                self.api.CloseHandle(th)

    def process_ids(self, capacity=64):
        """Query kernel membership, including nested jobs; PPIDs can be reused."""
        if os.name != 'nt' or not self.handle:
            raise RuntimeError('Windows Job Object is not open')
        import ctypes as c
        from ctypes import wintypes as w
        while capacity <= 65536:
            class ProcessIds(c.Structure):
                _fields_ = [('assigned',w.DWORD),('count',w.DWORD),('ids',c.c_size_t*capacity)]
            data = ProcessIds()
            ok = self.api.QueryInformationJobObject(self.handle,3,c.byref(data),c.sizeof(data),None)
            error = c.get_last_error()
            if ok and data.count >= data.assigned:
                return list(data.ids[:data.count])
            if not ok and error != 234:  # ERROR_MORE_DATA
                raise c.WinError(error)
            capacity = max(capacity*2,int(data.assigned))
        raise RuntimeError('任务进程列表超过受控容量，无法确认归属')

    def contains(self,pid):
        import ctypes as c
        from ctypes import wintypes as w
        handle = self.api.OpenProcess(0x1000,False,pid)
        if not handle:
            error = c.get_last_error()
            if error == 87:return False  # process exited before the handle was opened
            raise c.WinError(error)
        try:
            member = w.BOOL()
            if not self.api.IsProcessInJob(handle,self.handle,c.byref(member)):
                raise c.WinError(c.get_last_error())
            return bool(member.value)
        finally:self.api.CloseHandle(handle)

    def terminate(self):
        if os.name == 'nt' and self.handle:
            if not self.api.TerminateJobObject(self.handle,1):
                import ctypes as c
                raise c.WinError(c.get_last_error())
        elif self.process and matching_process(self.saved):
            try:
                os.killpg(self.process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None
        elif os.name != 'nt' and self.process:
            self.terminate()


def launch_owned(args, **kwargs):
    owner = ProcessOwner()
    try:
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW | 0x00000004  # CREATE_SUSPENDED
        else:
            kwargs['start_new_session'] = True
        process = subprocess.Popen(args,**kwargs)
        try:
            owner.attach_and_resume(process)
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            raise
        return process,owner
    except BaseException:
        owner.close()
        raise


def stop_owned(process,owner,timeout=8):
    owner.terminate()
    process.wait(timeout=timeout)


def tree_snapshot(process,owner=None):
    try:
        if os.name == 'nt' and owner is not None:
            # An orphan's historical PPID can equal a newly started solver PID.
            # Only the owning Job Object determines Windows task membership.
            members = []
            for pid in owner.process_ids():
                try:members.append(psutil.Process(pid))
                except psutil.NoSuchProcess:pass
        else:
            if process.poll() is not None:return []
            parent = psutil.Process(process.pid)
            members = [parent];pending = [parent]
            while pending:
                current = pending.pop()
                for child in current.children():
                    if child.create_time() >= current.create_time():
                        members.append(child);pending.append(child)
        rows = []
        for p in members:
            try:
                row = {**identity(p.pid),'rss':p.memory_info().rss,'name':p.name()}
                if os.name == 'nt' and owner is not None and not owner.contains(p.pid):continue
                rows.append(row)
            except (psutil.NoSuchProcess,psutil.AccessDenied):
                pass
        return rows
    except psutil.NoSuchProcess:
        return []
