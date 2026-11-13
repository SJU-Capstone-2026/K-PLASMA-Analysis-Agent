import {afterEach, expect, test, vi} from 'vitest';

afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();vi.resetModules();window.history.replaceState({},'','/');});

test('local bootstrap is removed from browser history before the one-time exchange',async()=>{
 vi.stubEnv('VITE_AGENT_DEFAULT_GRAPH_VERSION','v2_localLLM');
 window.history.replaceState({},'','/#local-bootstrap=synthetic-one-use');
 const fetch=vi.fn(async(_path:string,init:RequestInit)=>{
  expect(window.location.hash).toBe('');
  expect(init.headers).toEqual({'X-Local-Bootstrap':'synthetic-one-use'});
  return {ok:true,status:204};
 });
 vi.stubGlobal('fetch',fetch);
 const session=await import('./local-session');
 await Promise.all([session.bootstrapLocalSession(),session.bootstrapLocalSession()]);
 expect(fetch).toHaveBeenCalledTimes(1);
 expect(fetch.mock.calls[0][0]).toBe('/api/local-runtime/session');
 expect(window.localStorage.getItem('synthetic-one-use')).toBeNull();
});

test('bootstrap failure propagates without exposing its value',async()=>{
 vi.stubEnv('VITE_AGENT_DEFAULT_GRAPH_VERSION','v2_localLLM');
 window.history.replaceState({},'','/#local-bootstrap=synthetic-private');
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status:401})));
 const session=await import('./local-session');
 await expect(session.bootstrapLocalSession()).rejects.toThrow('LOCAL_SESSION_UNAVAILABLE');
 expect(window.location.href).not.toContain('synthetic-private');
});

test('cloud UI does not exchange or consume a local bootstrap',async()=>{
 vi.stubEnv('VITE_AGENT_DEFAULT_GRAPH_VERSION','v2');
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
 const session=await import('./local-session');
 await session.bootstrapLocalSession();
 expect(fetch).not.toHaveBeenCalled();
});

test('shared UI bootstraps before its first data request even with a cloud default',async()=>{
 vi.stubEnv('VITE_AGENT_DEFAULT_GRAPH_VERSION','v2');
 vi.stubEnv('VITE_AGENT_SUPPORTED_GRAPH_VERSIONS','v1,v2,v3,v2_localLLM');
 window.history.replaceState({},'','/#local-bootstrap=synthetic-shared-session');
 const fetch=vi.fn(async(path:string)=>path==='/api/local-runtime/session'
  ?{ok:true,status:204}:new Response('{}',{headers:{'Content-Type':'application/json'}}));
 vi.stubGlobal('fetch',fetch);
 const {request}=await import('./client');
 await request('/api/workspace');
 expect(fetch.mock.calls.map(call=>call[0])).toEqual(['/api/local-runtime/session','/api/workspace']);
 expect(window.location.hash).toBe('');
});

test('an already authenticated local page keeps the existing synchronous request start',async()=>{
 vi.stubEnv('VITE_AGENT_DEFAULT_GRAPH_VERSION','v2_localLLM');
 const fetch=vi.fn(async()=>new Response('{}',{headers:{'Content-Type':'application/json'}}));
 vi.stubGlobal('fetch',fetch);
 const {request}=await import('./client');
 const result=request('/api/workspace');
 expect(fetch).toHaveBeenCalledTimes(1);
 await result;
});
