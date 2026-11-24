import {isGraphVersion, type GraphVersion} from 'agent';

export function graphDeployment(): {versions: GraphVersion[]; defaultVersion: GraphVersion} {
 const raw:string=import.meta.env.VITE_AGENT_SUPPORTED_GRAPH_VERSIONS??'v1,v2';
 const values=[...new Set(raw.split(',').map(value=>value.trim()))];
 const defaultVersion:string=import.meta.env.VITE_AGENT_DEFAULT_GRAPH_VERSION??'v1';
 if(!values.length||!values.every(isGraphVersion)||!isGraphVersion(defaultVersion)
  ||!values.includes(defaultVersion))
  throw new Error('Invalid Agent graph deployment configuration');
 return {versions:values,defaultVersion};
}
