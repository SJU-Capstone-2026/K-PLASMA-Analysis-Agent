import type {V3Options} from 'agent';
import './v3-records.css';

export function V3ModeSummary({mode}:{mode:V3Options}){
 return <p className="v3-mode-summary" aria-label="답변에 사용한 기능">
  <span>판단 기록 규칙 {mode.rulesEnabled?'ON':'OFF'}</span><span>RAG {mode.ragEnabled?'ON':'OFF'}</span>
 </p>;
}

export function V3OptionsControls({mode,disabled,onChange}:{mode:V3Options;disabled:boolean;onChange:(mode:V3Options)=>void}){
 return <fieldset className="v3-options" disabled={disabled}>
  <legend>V3 판단 기록 기능</legend>
  <div className="v3-options__switches">
   <label><input type="checkbox" role="switch" aria-label="판단 기록 규칙" checked={mode.rulesEnabled}
    onChange={event=>onChange({...mode,rulesEnabled:event.target.checked})}/><span>판단 기록 규칙 <strong>{mode.rulesEnabled?'ON':'OFF'}</strong></span></label>
   <label><input type="checkbox" role="switch" aria-label="RAG" checked={mode.ragEnabled}
    onChange={event=>onChange({...mode,ragEnabled:event.target.checked})}/><span>RAG <strong>{mode.ragEnabled?'ON':'OFF'}</strong></span></label>
  </div>
  <p>{disabled?'진행 중인 요청은 시작할 때 선택한 설정을 유지합니다.':'다음 질문에 적용할 기능을 선택하세요.'} 수치 검증과 계획 검토는 계속 수행됩니다.</p>
 </fieldset>;
}
