import type {View} from '../../App';
export function FlowPage({decisionCount=0,onNavigate}:{decisionCount?:number;onNavigate:(view:View)=>void}){
return <><div className="page-header"><div><span className="eyebrow">QUICK GUIDE</span><h1>세 단계로 사용하는 K-PLASMA</h1><p>정방향·역방향을 별도 메뉴로 고르지 않아도, Agent가 질문 의도를 구분해 실제 Run 근거로 답합니다.</p></div><div className="page-actions"><button className="button button--primary" type="button" data-action="flow-start" onClick={()=>onNavigate("agent")}>분석 Agent 시작</button></div></div>
      <section className="flow-hero"><div className="flow-path">
        <article><span className="flow-number">01</span><div className="flow-icon" aria-hidden="true">⌁</div><span className="section-kicker">ASK</span><h2>자연어 질문</h2><p>공정 조건, 원하는 특성, 관찰된 변화 중 무엇을 묻는지 Agent가 구분합니다.</p><ul><li>조건 조회</li><li>후보 탐색</li><li>변화 설명</li></ul><button className="text-button" type="button" data-action="go-agent" onClick={()=>onNavigate("agent")}>분석 Agent 열기 →</button></article>
        <div className="flow-connector" aria-hidden="true"><span>해석을 확인하고</span>→</div>
        <article><span className="flow-number">02</span><div className="flow-icon" aria-hidden="true">⌗</div><span className="section-kicker">VERIFY</span><h2>답변과 근거 확인</h2><p>답변 옆에서 실제 수치, 분포·파형, 수렴·품질, 매뉴얼 근거를 함께 검토합니다.</p><ul><li>예측값 생성 없음</li><li>관찰·해석·한계 구분</li><li>원본 파일 추적</li></ul><button className="text-button" type="button" data-action="go-analysis" onClick={()=>onNavigate("analysis")}>실험 데이터 탐색 →</button></article>
        <div className="flow-connector" aria-hidden="true"><span>근거와 선택을 남겨</span>→</div>
        <article><span className="flow-number">03</span><div className="flow-icon" aria-hidden="true">▤</div><span className="section-kicker">DECIDE</span><h2>코멘트·판단 저장</h2><p>채택·보류·제외와 필수 코멘트를 분석 문맥과 함께 로컬에 보존합니다.</p><ul><li>비교 Run 기록</li><li>분석 조건 보존</li><li>필터·상세 조회</li></ul><button className="text-button" type="button" data-action="go-archive" onClick={()=>onNavigate("archive")}>의사결정 기록 열기 →</button></article>
      </div></section>
      <section className="flow-status panel"><div><span className="section-kicker">WORKFLOW STATUS</span><h2>프로토타입 연결 상태</h2></div><div className="flow-status-items"><span><b>150</b> Actual Runs</span><span><b>125</b> 분포 있는 Run</span><span><b>{decisionCount}</b> 저장된 결정</span><span><b>Local</b> 저장 범위</span></div></section></>;
}
