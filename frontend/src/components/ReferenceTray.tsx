import type {RunRef} from 'agent';
import {buildReferenceDisplayModel} from '../prototype/view-models';
export function RunChip({runId,onRemove}:{runId:string;onRemove?:()=>void}){return <span className="run-context-chip"><i aria-hidden="true"/><strong title={runId}>{runId}</strong>{onRemove&&<button type="button" onClick={onRemove} aria-label={`${runId} 채팅에서 제거`}>×</button>}</span>;}
export function ReferenceTray({references,onRemove,onRemoveRun}:{references:RunRef[];onRemove?:()=>void;onRemoveRun?:(ref:RunRef)=>void}){
 const model=buildReferenceDisplayModel({ids:references.map(ref=>ref.runId)});if(!model)return null;
 const chip=(item:{runId:string})=><RunChip key={item.runId} runId={item.runId} onRemove={onRemoveRun?()=>onRemoveRun(references.find(ref=>ref.runId===item.runId)!):undefined}/>;
 return <div className={`reference-tray ${model.count>1?'is-group':'is-single'}`}>{model.count>1&&<span className="reference-tray-label">후보 집합 · {model.count}개</span>}<div className="reference-tray-runs">{model.visibleItems.map(chip)}{model.remainingCount>0&&<details className="reference-tray-more"><summary><span className="reference-more-label">+{model.remainingCount}개 후보 더보기 ↓</span><span className="reference-less-label">후보 접기 ↑</span></summary><div className="reference-tray-more-grid">{model.hiddenItems.map(chip)}</div></details>}</div>{onRemove&&<button className="reference-tray-clear" type="button" onClick={onRemove} aria-label="참조 대상 해제">×</button>}</div>;
}
