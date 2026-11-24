let pending:Promise<void>|undefined;

/** Consume the private launcher's fragment before any data request or page render. */
export function bootstrapLocalSession():Promise<void>|undefined{
 if(import.meta.env.VITE_AGENT_DEFAULT_GRAPH_VERSION!=='v2_localLLM'
  &&!(import.meta.env.VITE_AGENT_SUPPORTED_GRAPH_VERSIONS??'').split(',').some((version:string)=>version.trim()==='v2_localLLM'))return;
 if(pending)return pending;
 const fragment=new URLSearchParams(window.location.hash.slice(1));
 const token=fragment.get('local-bootstrap');
 if(!token)return;
 fragment.delete('local-bootstrap');
 const remaining=fragment.toString();
 window.history.replaceState(window.history.state,'',`${window.location.pathname}${window.location.search}${remaining?`#${remaining}`:''}`);
 pending=fetch('/api/local-runtime/session',{method:'POST',credentials:'same-origin',
  headers:{'X-Local-Bootstrap':token},cache:'no-store',referrerPolicy:'no-referrer'})
  .then(response=>{if(!response.ok)throw new Error('LOCAL_SESSION_UNAVAILABLE');pending=undefined;});
 return pending;
}
