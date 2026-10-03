// Browser-only synthetic harness. Production main.tsx never imports this module.
import {createRoot} from 'react-dom/client';
import {useState} from 'react';
import {App} from '../src/App';
import {ReferenceTray} from '../src/components/ReferenceTray';
import {fixtureRuns} from '../src/test/runs';
function Harness(){const [references,setReferences]=useState(Array.from({length:8},(_,index)=>({runId:`SYNTHETIC-${index}`,runVersionId:`synthetic-${index}`})));return <App pages={{agent:context=><><button className="button" onClick={()=>context.openRunDetail(fixtureRuns[0])}>실험 자세히 보기</button><ReferenceTray references={references} onRemove={()=>setReferences([])}/></>}}/>;}
createRoot(document.getElementById('root')!).render(<Harness/>);
