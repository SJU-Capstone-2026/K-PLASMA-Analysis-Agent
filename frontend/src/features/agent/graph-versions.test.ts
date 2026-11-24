import {afterEach,expect,test,vi} from 'vitest';
import {graphDeployment} from './graph-versions';

afterEach(()=>vi.unstubAllEnvs());

test('cloud deployment preserves v1/v2 defaults and enables v3 only explicitly',()=>{
 expect(graphDeployment()).toEqual({versions:['v1','v2'],defaultVersion:'v1'});
 vi.stubEnv('VITE_AGENT_SUPPORTED_GRAPH_VERSIONS','v1,v2,v3');
 expect(graphDeployment().versions).toEqual(['v1','v2','v3']);
});

test('shared deployment exposes all configured graph identities in the same app',()=>{
 vi.stubEnv('VITE_AGENT_SUPPORTED_GRAPH_VERSIONS','v1,v2,v3,v2_localLLM');
 vi.stubEnv('VITE_AGENT_DEFAULT_GRAPH_VERSION','v2_localLLM');
 expect(graphDeployment()).toEqual({versions:['v1','v2','v3','v2_localLLM'],defaultVersion:'v2_localLLM'});
});

test.each(['','v1,','unknown','v2,v2_localLLM'])('invalid deployment %s fails closed',versions=>{
 vi.stubEnv('VITE_AGENT_SUPPORTED_GRAPH_VERSIONS',versions);
 expect(()=>graphDeployment()).toThrow('Invalid Agent graph deployment configuration');
});
