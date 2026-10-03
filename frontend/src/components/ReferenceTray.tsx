import type {RunRef} from 'agent';
import {buildReferenceDisplayModel} from '../prototype/view-models';
export function RunChip({runId}:{runId:string}){return <span className="run-context-chip"><i aria-hidden="true"/><strong>{runId}</strong></span>;}
export function ReferenceTray({references,onRemove}:{references:RunRef[];onRemove?:()=>void}){
 const model=buildReferenceDisplayModel({ids:references.map(ref=>ref.runId)});if(!model)return null;
 return <div className={`reference-tray ${model.count>1?'is-group':'is-single'}`}>{model.count>1&&<span className="reference-tray-label">후보 집합 · {model.count}개</span>}<div className="reference-tray-runs">{model.visibleItems.map(item=><RunChip key={item.runId} runId={item.runId}/>)}{model.remainingCount>0&&<details className="reference-tray-more"><summary><span className="reference-more-label">+{model.remainingCount}개 후보 더보기 ↓</span><span className="reference-less-label">후보 접기 ↑</span></summary><div className="reference-tray-more-grid">{model.hiddenItems.map(item=><RunChip key={item.runId} runId={item.runId}/>)}</div></details>}</div>{onRemove&&<button className="reference-tray-clear" type="button" onClick={onRemove} aria-label="참조 대상 해제">×</button>}</div>;
}
