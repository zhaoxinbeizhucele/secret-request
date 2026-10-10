"""Windows execution-tree lifetime: assign a suspended process before it can spawn."""
import ctypes
from ctypes import wintypes as w

k=ctypes.WinDLL("kernel32",use_last_error=True)
SIZE=ctypes.c_size_t
class Basic(ctypes.Structure):
    _fields_=[("process_time",ctypes.c_int64),("job_time",ctypes.c_int64),("flags",w.DWORD),("min_working",SIZE),("max_working",SIZE),("active",w.DWORD),("affinity",SIZE),("priority",w.DWORD),("scheduling",w.DWORD)]
class Io(ctypes.Structure):
    _fields_=[(name,ctypes.c_uint64) for name in ("read_ops","write_ops","other_ops","read_bytes","write_bytes","other_bytes")]
class Extended(ctypes.Structure):
    _fields_=[("basic",Basic),("io",Io),("process_memory",SIZE),("job_memory",SIZE),("peak_process",SIZE),("peak_job",SIZE)]
class ThreadEntry(ctypes.Structure):
    _fields_=[("size",w.DWORD),("usage",w.DWORD),("thread_id",w.DWORD),("process_id",w.DWORD),("base_priority",w.LONG),("delta_priority",w.LONG),("flags",w.DWORD)]
for name,args,result in [
    ("CreateJobObjectW",[w.LPVOID,w.LPCWSTR],w.HANDLE),
    ("SetInformationJobObject",[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD],w.BOOL),
    ("AssignProcessToJobObject",[w.HANDLE,w.HANDLE],w.BOOL),
    ("CloseHandle",[w.HANDLE],w.BOOL),
    ("CreateToolhelp32Snapshot",[w.DWORD,w.DWORD],w.HANDLE),
    ("Thread32First",[w.HANDLE,ctypes.POINTER(ThreadEntry)],w.BOOL),
    ("Thread32Next",[w.HANDLE,ctypes.POINTER(ThreadEntry)],w.BOOL),
    ("OpenThread",[w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
    ("ResumeThread",[w.HANDLE],w.DWORD)]:
    fn=getattr(k,name);fn.argtypes=args;fn.restype=result

def checked(result):
    if not result: raise ctypes.WinError(ctypes.get_last_error())
    return result

class Job:
    def __init__(self):
        self.handle=checked(k.CreateJobObjectW(None,None))
        limits=Extended();limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try: checked(k.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)))
        except Exception: self.close();raise
    def start(self,process):
        checked(k.AssignProcessToJobObject(self.handle,w.HANDLE(int(process._handle))))
        snapshot=k.CreateToolhelp32Snapshot(4,0)  # TH32CS_SNAPTHREAD
        if snapshot==w.HANDLE(-1).value: raise ctypes.WinError(ctypes.get_last_error())
        thread=None
        try:
            entry=ThreadEntry();entry.size=ctypes.sizeof(entry)
            exists=k.Thread32First(snapshot,ctypes.byref(entry))
            while exists:
                if entry.process_id==process.pid:
                    thread=checked(k.OpenThread(2,False,entry.thread_id));break
                exists=k.Thread32Next(snapshot,ctypes.byref(entry))
            if not thread: raise RuntimeError("suspended process thread not found")
            if k.ResumeThread(thread)==0xFFFFFFFF: raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if thread:k.CloseHandle(thread)
            k.CloseHandle(snapshot)
    def close(self):
        if self.handle:k.CloseHandle(self.handle);self.handle=None
