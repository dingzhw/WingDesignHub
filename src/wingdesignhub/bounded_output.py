"""Bounded stdout capture; never accumulate an unbounded communicate buffer."""
import threading
import time


def capture(process, owner, stdin, log, timeout, limit):
    from .processes import stop_owned
    if type(limit) is not int or limit < 16384:
        raise ValueError('日志限额至少 16384 字节')
    exceeded=threading.Event();errors=[];total=0;tail=b''
    def drain():
        nonlocal total,tail
        try:
            with log.open('wb') as f:
                while chunk := process.stdout.read(65536):
                    remaining=max(0,limit-total)
                    f.write(chunk[:remaining]);total+=len(chunk)
                    tail=(tail+chunk)[-8192:]
                    if total>limit:exceeded.set()
        except BaseException as exc:errors.append(exc);exceeded.set()
    def feed():
        try:process.stdin.write(stdin);process.stdin.close()
        except (BrokenPipeError,OSError):pass
    reader=threading.Thread(target=drain,daemon=True)
    writer=threading.Thread(target=feed,daemon=True)
    reader.start();writer.start();start=time.monotonic();reason=None
    try:
        while process.poll() is None:
            if exceeded.is_set():reason='output_limit';break
            if time.monotonic()-start>=timeout:reason='timeout';break
            time.sleep(.02)
    finally:
        # Includes inherited pipe handles in grandchildren and parent exceptions.
        if process.poll() is None or reader.is_alive():stop_owned(process,owner)
        reader.join(5);writer.join(5)
        if reader.is_alive() or writer.is_alive():raise RuntimeError('输出管道未确认关闭')
        process.stdout.close()
    if errors:raise RuntimeError('写入求解日志失败') from errors[0]
    if exceeded.is_set():
        reason='output_limit'
        with log.open('r+b') as f:f.seek(limit-len(tail));f.write(tail);f.truncate(limit)
    return {'status':reason or 'completed','observed_bytes':total,'stored_bytes':log.stat().st_size,
            'limit_bytes':limit,'truncated':total>limit,'retention':'head and final 8192 bytes when truncated'}
