"""Read existing timing logs; release local k6 waiters without pausing product workers."""
import asyncio
import json
import math
import threading
import time


class ProcessingState:
    def __init__(self):
        self.jobs=set();self.parsing=set()

    def accept(self,event):
        if event.get('kind')!='job':return
        ident=event['id'];phase=event['phase']
        if phase=='job.claimed':self.jobs.add(ident)
        elif phase=='source.load':self.parsing.add(ident)
        elif phase=='parse.graph':self.parsing.discard(ident)
        elif phase=='job':self.jobs.discard(ident);self.parsing.discard(ident)

    def ready(self):
        return len(self.jobs)==8 and len(self.parsing & self.jobs)==8


class PhaseGate:
    def __init__(self,timing,offset,output):
        self.output=output;self.result=None;self.error=None;self.initialized=threading.Event()
        self.thread=threading.Thread(target=lambda:asyncio.run(self.run(timing,offset)),daemon=True)
        self.thread.start()
        if not self.initialized.wait(5):raise TimeoutError('Local gate failed to start')

    async def run(self,timing,offset):
        self.loop=asyncio.get_running_loop();self.stop=asyncio.Event();self.release=asyncio.Event();self.waiters=set()
        server=await asyncio.start_server(self.handle,'127.0.0.1',0,backlog=128)
        self.url=f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}";self.initialized.set()
        watcher=asyncio.create_task(self.watch(timing,offset))
        await self.stop.wait();self.release.set();watcher.cancel()
        server.close();await server.wait_closed()
        try:await watcher
        except asyncio.CancelledError:pass

    async def handle(self,reader,writer):
        try:
            header=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),10)
            method,path,_=header.split(b'\r\n',1)[0].decode().split()
            ident=path.removeprefix('/wait/')
            if method!='GET' or not path.startswith('/wait/') or not ident.isdigit():raise ValueError('Invalid waiter')
            self.waiters.add(ident)
            await asyncio.wait_for(self.release.wait(),55)
            if self.result is None:raise RuntimeError('Gate closed without processing phase')
            body=json.dumps(self.result).encode();status='200 OK'
        except Exception:
            body=b'{"error":"processing phase unavailable"}';status='504 Gateway Timeout'
        try:
            writer.write(f'HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode()+body)
            await writer.drain()
        finally:writer.close()

    async def watch(self,timing,offset):
        state=ProcessingState();pending=b'';last=None
        try:
            with timing.open('rb') as stream:
                stream.seek(offset)
                while not self.stop.is_set():
                    pending+=stream.read();lines=pending.split(b'\n');pending=lines.pop()
                    for line in lines:
                        if line:
                            event=json.loads(line);state.accept(event);last=event['endNs']
                    # Process the whole flushed chunk before deciding; never pause a product worker.
                    if len(self.waiters)==100 and state.ready():
                        self.result=dict(releaseEpochMs=time.time()*1000,releaseMonotonicNs=time.monotonic_ns(),
                            lastEventNs=last,observedActiveJobs=8,observedParsingJobs=8,waiters=100,
                            jobIds=sorted(state.jobs))
                        self.result['dispatchEpochMs']=math.ceil(self.result['releaseEpochMs'])+100
                        self.output.write_text(json.dumps(self.result,indent=2));self.release.set();return
                    await asyncio.sleep(.001)
        except Exception as error:
            self.error=repr(error);self.output.write_text(json.dumps(dict(error=self.error)));self.release.set()

    def close(self):
        self.loop.call_soon_threadsafe(self.stop.set);self.thread.join(5)
