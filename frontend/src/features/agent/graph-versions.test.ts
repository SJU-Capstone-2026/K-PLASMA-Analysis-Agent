import {afterEach,expect,test,vi} from 'vitest';
import {graphDeployment} from './graph-versions';

afterEach(()=>vi.unstubAllEnvs());

test('standard deployment defaults to v2',()=>{
 expect(graphDeployment()).toEqual({versions:['v2'],defaultVersion:'v2'});
});

test('shared deployment exposes all configured graph identities in the same app',()=>{
 vi.stubEnv('VITE_AGENT_SUPPORTED_GRAPH_VERSIONS','v2,v2_localLLM');
 vi.stubEnv('VITE_AGENT_DEFAULT_GRAPH_VERSION','v2_localLLM');
 expect(graphDeployment()).toEqual({versions:['v2','v2_localLLM'],defaultVersion:'v2_localLLM'});
});

test.each([
 ['v1,v2','v1',['v2'],'v2'],
 ['v1,v2,v3,v2_localLLM','v3',['v2','v2_localLLM'],'v2'],
 ['v1,v2,v2_localLLM','v2_localLLM',['v2','v2_localLLM'],'v2_localLLM'],
])('legacy deployment %s with default %s keeps only active modes',(supported,configuredDefault,versions,defaultVersion)=>{
 vi.stubEnv('VITE_AGENT_SUPPORTED_GRAPH_VERSIONS',supported);
 vi.stubEnv('VITE_AGENT_DEFAULT_GRAPH_VERSION',configuredDefault);
 expect(graphDeployment()).toEqual({versions,defaultVersion});
});

test.each([['v1,v2_localLLM','v1'],['v1,v2','v2_localLLM'],['v2,v2_localLLM','unknown']])(
 'deployment %s rejects incompatible default %s',(versions,defaultVersion)=>{
  vi.stubEnv('VITE_AGENT_SUPPORTED_GRAPH_VERSIONS',versions);
  vi.stubEnv('VITE_AGENT_DEFAULT_GRAPH_VERSION',defaultVersion);
  expect(()=>graphDeployment()).toThrow('Invalid Agent graph deployment configuration');
 });

test.each(['','v2,','v2,unknown','v1,v3','v2_localLLM'])('invalid deployment %s fails closed',versions=>{
 vi.stubEnv('VITE_AGENT_SUPPORTED_GRAPH_VERSIONS',versions);
 expect(()=>graphDeployment()).toThrow('Invalid Agent graph deployment configuration');
});
