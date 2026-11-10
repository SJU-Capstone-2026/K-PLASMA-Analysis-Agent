import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve,join,relative,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const require = createRequire(new URL('../../frontend/package.json',import.meta.url));
const {chromium} = require('@playwright/test');
const terminalStatuses = new Set(['COMPLETED','FAILED','CANCELLED']);
const pause = ms => new Promise(resolve=>setTimeout(resolve,ms));
const equal = (a,b) => JSON.stringify(a)===JSON.stringify(b);
const numberText = value => Number(value.toFixed(2)).toLocaleString('ko-KR',{maximumFractionDigits:2});
const normalize = value => String(value??'').normalize('NFKC').replace(/[\s\u200b]+/g,' ').trim();
const escapeRegex = value => value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
const mentions = (text,id) => new RegExp(`(?<![A-Za-z0-9_-])${escapeRegex(id)}(?![A-Za-z0-9_-])`).test(text);
const errorText = error => String(error.message??error).split('\nBrowser logs:')[0].split('\nCall log:')[0].trim();
function demand(condition,message,kind='HITL_MISMATCH') {
  if (!condition) throw Object.assign(new Error(message),{kind});
}

export function planRunSelection(options,pending,expected,fallbackBaseline=null) {
  const ids=expected.runIds;
  demand(Array.isArray(ids)&&new Set(ids).size===ids.length,'Requested Run IDs must be a unique array');
  const min=pending.minSelections??2,max=pending.maxSelections??null;
  demand(ids.length>=min&&(max===null||ids.length<=max),`Run selection count ${ids.length} outside ${min}..${max??'unlimited'}`);
  if (expected.min!==undefined) demand(expected.min===min,`Run selection min differs: expected ${expected.min}, actual ${min}`);
  if (Object.hasOwn(expected,'max')) demand(expected.max===max,`Run selection max differs: expected ${expected.max}, actual ${max}`);
  for (const id of ids) {
    const matches=options.filter(o=>o.ref?.runId===id);
    demand(matches.length>0,`Requested Run is missing: ${id}`);
    demand(matches.length===1,`Requested Run is ambiguous across versions: ${id}`);
    demand(matches[0].selectable===true,`Requested Run is unavailable: ${id}`);
  }
  const chosen=options.filter(o=>ids.includes(o.ref.runId));
  demand(new Set(chosen.map(o=>o.key)).size===chosen.length,'Duplicate Run option keys');
  const baselineId=expected.baselineRunId??(ids.includes(fallbackBaseline)?fallbackBaseline:null);
  const baseline=baselineId?chosen.find(o=>o.ref.runId===baselineId):null;
  demand(!baselineId||!!baseline,'Requested baseline is outside the chosen Runs');
  demand(!pending.baselineRequired||!!baseline,'A required baseline was not configured in the case');
  return {chosen,input:{type:'run_selection',runKeys:chosen.map(o=>o.key),baselineKey:baseline?.key??null}};
}

export function comparisonInput(pending,expected,keyMap) {
  const input={type:'comparison_options'};
  if (pending.fields?.includes('baselineKey')) {
    const id=expected.baselineRunId;
    demand(typeof id==='string'&&id.length>0,'Comparison baseline was not configured');
    const allowed=pending.allowedRunKeys??[];
    const labels=pending.options??[];
    const labelled=labels.filter(o=>allowed.includes(o.input?.baselineKey)&&mentions(o.label,id)).map(o=>o.input.baselineKey);
    const keys=labels.length?labelled:allowed.filter(key=>keyMap.get(key)===id);
    demand(new Set(keys).size===1,`Comparison baseline is missing or ambiguous: ${id}`);
    input.baselineKey=keys[0];
  }
  if (pending.fields?.includes('trendAxis')) {
    demand(typeof expected.trendAxis==='string'&&pending.allowedTrendAxes?.includes(expected.trendAxis),
      `Requested trend axis is unavailable: ${expected.trendAxis}`);
    input.trendAxis=expected.trendAxis;
  }
  demand((pending.fields??[]).every(field=>['baselineKey','trendAxis'].includes(field)),'Unexpected comparison option field');
  return input;
}

function localUrl(value) {
  const url=new URL(value);
  demand(['http:','https:'].includes(url.protocol)&&['localhost','127.0.0.1','[::1]'].includes(url.hostname)
    &&!url.username&&!url.password&&!url.search&&!url.hash,'Bridge URLs must be local server origins','CONFIG');
  return url.origin;
}
function childPath(root,path) {
  const output=resolve(path),rel=relative(root,output);
  demand(rel!==''&&!rel.startsWith(`..${sep}`)&&rel!=='..',
    'Case output must be a child of the init output directory','CONFIG');
  return output;
}

class BrowserBridge {
  async init(command) {
    demand(!this.browser,'Bridge is already initialized','CONFIG');
    this.api=localUrl(command.api);this.web=localUrl(command.web);this.output=resolve(command.output);
    await mkdir(this.output,{recursive:true});
    this.browser=await chromium.launch({headless:command.headless===true});
    this.context=await this.browser.newContext({viewport:{width:1440,height:1000},locale:'ko-KR',
      timezoneId:'Asia/Seoul',colorScheme:'light',reducedMotion:'reduce'});
    this.page=await this.context.newPage();
    this.page.setDefaultTimeout(10000);
    this.page.on('pageerror',error=>this.current?.browserErrors.push({type:'pageerror',message:error.message}));
    this.page.on('console',message=>{
      if(message.type()==='error') this.current?.browserErrors.push({type:'console',message:message.text()});
    });
    this.page.on('response',response=>{
      const path=new URL(response.url()).pathname,current=this.current;
      if(!current||!path.startsWith('/api/'))return;
      if(response.status()>=400)current.httpErrors.push({path,status:response.status(),method:response.request().method()});
      if(path==='/api/run-versions/outputs') {
        const task=response.json().then(body=>current.outputReads.push({request:response.request().postDataJSON(),response:body}))
          .catch(()=>current.httpErrors.push({path,kind:'UNREADABLE_OUTPUT_RESPONSE'}));
        current.readTasks.push(task);
      }
    });
    await this.page.goto(`${this.web}/?view=agent`,{waitUntil:'domcontentloaded',timeout:30000});
    await this.page.getByRole('combobox',{name:'Agent 버전'}).waitFor({state:'visible'});
    await this.page.bringToFront();
    return {ok:true,browser:'chromium',headful:command.headless!==true,ready:true};
  }

  async apiCall(path,{method='GET',body,timeout=10000}={}) {
    const response=await fetch(`${this.api}${path}`,{method,headers:{Accept:'application/json',
      ...(body!==undefined?{'Content-Type':'application/json'}:{})},
      ...(body!==undefined?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(Math.max(1,timeout))});
    demand(response.ok,`API ${method} ${path.split('?')[0]} returned ${response.status}`,'API_ERROR');
    return response.json();
  }

  async poll(id,deadline,minRevision=0) {
    while(Date.now()<deadline) {
      const view=await this.apiCall(`/api/agent/requests/${encodeURIComponent(id)}`,{timeout:Math.min(10000,deadline-Date.now())});
      demand(view.requestId===id,'API returned a different request ID','REQUEST_MISMATCH');
      this.current.view=view;
      if(view.requestRevision>=minRevision&&(terminalStatuses.has(view.status)||view.status==='NEEDS_INPUT'))return view;
      await pause(Math.min(650,Math.max(1,deadline-Date.now())));
    }
    throw Object.assign(new Error('Request did not reach a terminal or input state before the case deadline'),{kind:'TIMEOUT'});
  }

  async resume(view,expected,item,keyMap,deadline) {
    const pending=view.pendingInput;
    demand(view.status==='NEEDS_INPUT'&&pending,'Resume requires the actual NEEDS_INPUT state');
    const interaction={type:pending.type??'text',pending:structuredClone(pending),options:null,input:null,
      requestId:view.requestId,revisionBefore:view.requestRevision,waitingUiVisible:false};
    this.current.interactions.push(interaction);
    const panel=this.page.getByRole('region',{name:'진행 중인 분석 요청'});
    await panel.waitFor({state:'visible',timeout:Math.min(12000,Math.max(1,deadline-Date.now()))});
    interaction.waitingUiVisible=true;
    demand(expected&&pending.type===expected.type,`Unexpected HITL: ${pending.type??'text'}`,'UNEXPECTED_HITL');
    let options=null,input;
    if(pending.type==='run_selection') {
      options=await this.apiCall(`/api/agent/requests/${encodeURIComponent(view.requestId)}/run-options?pendingInputId=${encodeURIComponent(pending.id)}`);
      interaction.options=options;
      demand(options.requestId===view.requestId&&options.pendingInputId===pending.id&&options.requestRevision===view.requestRevision,
        'Run option snapshot differs from the waiting request');
      const planned=planRunSelection(options.options,pending,expected,item.baseline);
      input=planned.input;
      const picker=panel.locator('.v1-run-selection');
      await picker.getByRole('searchbox',{name:'실험 검색'}).waitFor({state:'visible'});
      for(const option of planned.chosen) {
        const checkbox=picker.getByRole('checkbox',{name:`${option.key} · ${option.ref.runId} · ${option.ref.runVersionId}`,exact:true});
        demand(await checkbox.isEnabled(),`Visible checkbox unavailable: ${option.ref.runId}`);
        await checkbox.check();
        demand(await checkbox.isChecked(),`Visible checkbox did not retain selection: ${option.ref.runId}`);
      }
      demand(await picker.getByRole('checkbox',{checked:true}).count()===planned.chosen.length,'Visible selected count differs from intended input');
      if(input.baselineKey) {
        const baseline=picker.getByLabel(/비교 기준/);
        if(!await baseline.isVisible())await picker.getByText('선택 옵션',{exact:true}).click();
        await baseline.selectOption(input.baselineKey);
        demand(await baseline.inputValue()===input.baselineKey,'Visible baseline value differs');
      }
      keyMap.clear();
      for(const option of options.options)keyMap.set(option.key,option.ref.runId);
    } else {
      interaction.options={allowedRunKeys:pending.allowedRunKeys,allowedTrendAxes:pending.allowedTrendAxes,options:pending.options};
      input=comparisonInput(pending,expected,keyMap);
      const form=panel.locator('.comparison-options-form');
      await form.waitFor({state:'visible'});
      if(input.baselineKey)await form.getByRole('combobox',{name:'기준 실험',exact:true}).selectOption(input.baselineKey);
      if(input.trendAxis)await form.getByRole('combobox',{name:'경향을 볼 조건',exact:true}).selectOption(input.trendAxis);
      options={allowedRunKeys:pending.allowedRunKeys,allowedTrendAxes:pending.allowedTrendAxes,options:pending.options};
    }
    interaction.options=options;interaction.expectedInput=input;
    const path=`/api/agent/requests/${view.requestId}/resume`;
    const [response]=await Promise.all([
      this.page.waitForResponse(r=>new URL(r.url()).pathname===path&&r.request().method()==='POST',
        {timeout:Math.min(20000,Math.max(1,deadline-Date.now()))}),
      panel.getByRole('button',{name:pending.type==='run_selection'?'선택한 실험으로 계속':'선택하고 계속',exact:true}).click()
    ]);
    const actual=response.request().postDataJSON();
    interaction.input=actual.input;interaction.resumePayload=actual;interaction.httpStatus=response.status();
    demand(response.ok(),`Visible resume returned HTTP ${response.status()}`,'RESUME_ERROR');
    demand(actual.pendingInputId===pending.id&&actual.expectedRequestRevision===view.requestRevision&&equal(actual.input,input),
      'Actual visible resume payload differs from intended choice');
    const resumed=await response.json();
    interaction.revisionAfter=resumed.requestRevision;interaction.responseStatus=resumed.status;
    demand(resumed.requestId===view.requestId&&resumed.requestRevision>view.requestRevision,
      'Visible resume did not advance the same request revision');
    return this.poll(view.requestId,deadline,view.requestRevision+1);
  }

  check(name,pass,detail) {this.current.uiChecks.push({name,pass,detail});}
  guardDeadline() {
    demand(Date.now()<this.deadline,'Case deadline reached during UI verification','TIMEOUT');
    this.page.setDefaultTimeout(Math.min(10000,Math.max(1,this.deadline-Date.now())));
  }

  async inspectTables(answer) {
    const steps=answer.stepResults??[];
    const root=this.page.locator('.agent-v2-answer').last();
    const details=root.locator(':scope > details');
    for(let index=0;index<await details.count();index++) {
      if(!await details.nth(index).evaluate(node=>node.open))await details.nth(index).locator(':scope > summary').click();
    }
    for(const step of steps) {
      this.guardDeadline();
      const result=step.outputs?.toolResult;
      if(!result||!['forward_lookup','reverse_search','compare_runs'].includes(result.kind))continue;
      // The execution ID identifies its API snapshot even when an earlier step is collapsed.
      const target=root.locator(`[data-execution-id="${step.executionId}"]`);
      if(await target.count()!==1) {
        this.check(`step-visible:${step.stepId}`,false,{executionId:step.executionId,count:await target.count()});continue;
      }
      let runs,fields;
      const comparison=result.kind==='compare_runs';
      if(comparison){runs=result.runs??[];fields=result.metricIds??[];}
      else if(result.kind==='forward_lookup'){runs=result.candidates??(result.selectedRun?[result.selectedRun]:[]);fields=['pressure','sourcePower','biasPower','ionFlux','meanIonEnergy','iedWidth'];}
      else {
        runs=result.searchResultVersion===2?(result.commonRunRefs??[]).map(ref=>{
          const run=result.runsByVersion?.[ref.runVersionId];
          demand(run?.runId===ref.runId&&run?.runVersionId===ref.runVersionId,'Invalid saved compact search reference','UI_SNAPSHOT');
          return run;
        }):(result.commonCandidates??[]).map(candidate=>candidate.run);
        const requested=new Set([...(result.constraints??[]).map(v=>v.metric),...(result.goals??[]).map(v=>v.metric)]);
        fields=['pressure','sourcePower','biasPower','ionFlux','meanIonEnergy','iedWidth'].filter(field=>requested.has(field));
        if(!fields.length)fields=['ionFlux','meanIonEnergy','iedWidth'];
      }
      if(comparison&&(result.plotIds??[]).includes('iead'))fields=fields.filter(field=>!field.startsWith('iead.'));
      const table=target.getByRole('table',{name:comparison?'선택한 실험 수치':'검색 Run 목록',exact:true});
      if(!runs.length){this.check(`empty-result-visible:${step.stepId}`,normalize(await target.innerText()).includes('조건에 맞는 Run이 없습니다'),{apiRunCount:0});continue;}
      if(!fields.length&&comparison){this.current.manualReview.push(`${step.stepId}: IEAD summary requires visual and raw-grid review`);continue;}
      if(!await table.count()){this.check(`run-table-visible:${step.stepId}`,false,{apiRunCount:runs.length});continue;}
      const observed=[],badValues=[],badUnits=[];
      let page=0;
      do {
        this.guardDeadline();
        const rows=await table.locator('tbody > tr').evaluateAll(nodes=>nodes.map(row=>({
          label:row.querySelector('th[scope="row"]')?.textContent??'',cells:[...row.querySelectorAll('td')].map(cell=>cell.textContent??'')
        })));
        for(let index=0;index<rows.length;index++) {
          const run=runs[page*10+index],row=rows[index];observed.push(row.label.trim());
          if(!run)continue;
          for(let column=0;column<fields.length;column++) {
            const field=fields[column];
            const datum=comparison?run.metrics?.[field]:null;
            const value=comparison?(datum?.status==='AVAILABLE'?datum.value:null):
              (['pressure','sourcePower','biasPower'].includes(field)?run[field]:run.metrics?.[field]);
            const actual=row.cells[column+(comparison?1:0)]??'';
            if(typeof value==='number'&&Number.isFinite(value)) {
              const formatted=normalize(numberText(value)),cell=normalize(actual);
              if(comparison?cell!==formatted:cell!==formatted&&!cell.startsWith(`${formatted} `))
                badValues.push({runId:comparison?run.ref.runId:run.runId,field,value,actual});
            }
            const unit=comparison?datum?.unit:run.units?.[field];
            const header=await table.locator('thead th').nth(column+(comparison?2:1)).innerText();
            if(unit&&typeof value==='number'&&!normalize(comparison?header:actual).includes(normalize(unit)))
              badUnits.push({field,unit,actual:comparison?header:actual});
          }
        }
        const next=target.getByRole('button',{name:'다음',exact:true});
        if(!await next.count()||!await next.isEnabled())break;
        await next.click();page++;
        demand(page<=Math.ceil(runs.length/10),'Result pagination did not end','UI_PAGINATION');
      }while(true);
      const ids=runs.map(run=>comparison?run.ref.runId:run.runId);
      this.check(`api-ui-targets:${step.stepId}`,equal(observed,ids),{expected:ids,actual:observed});
      this.check(`api-ui-numbers:${step.stepId}`,badValues.length===0,{checkedRuns:observed.length,fields,mismatches:badValues});
      this.check(`api-ui-units:${step.stepId}`,badUnits.length===0,{mismatches:badUnits});
      const previous=target.getByRole('button',{name:'이전',exact:true});
      while(await previous.count()&&await previous.isEnabled())await previous.click();
      if(!comparison&&result.requestedConditions) {
        const text=normalize(await target.locator('.v2-result-list > p').first().innerText());
        const names={pressure:'압력',sourcePower:'소스 전력',biasPower:'바이어스 전력'};
        const missing=Object.entries(result.requestedConditions).filter(([field,value])=>
          !text.includes(normalize(`${names[field]} ${value} ${field==='pressure'?'mTorr':'W'}`)));
        this.check(`requested-conditions-visible:${step.stepId}`,missing.length===0,{missing});
      }
    }
  }

  async inspectCharts() {
    const charts=this.page.locator('.agent-v2-answer').last().getByRole('region',{name:'비교 그래프',exact:true});
    for(let chartIndex=0;chartIndex<await charts.count();chartIndex++) {
      this.guardDeadline();
      const chart=charts.nth(chartIndex);await chart.scrollIntoViewIfNeeded();
      const expand=chart.getByRole('button',{name:'그래프 펼치기',exact:true});
      if(await expand.count())await expand.click();
      const tabs=chart.getByRole('tab');
      for(let tabIndex=0;tabIndex<await tabs.count();tabIndex++) {
        this.guardDeadline();
        const tab=tabs.nth(tabIndex),name=await tab.innerText();await tab.click();
        await chart.locator('[role="status"]').waitFor({state:'hidden',timeout:15000}).catch(()=>{});
        const figures=await chart.locator('svg[role="img"]').evaluateAll(nodes=>nodes.map(svg=>({
          label:svg.getAttribute('aria-label'),viewBox:svg.getAttribute('viewBox'),
          paths:[...svg.querySelectorAll('path[data-run-id]')].map(path=>({runId:path.dataset.runId,d:path.getAttribute('d'),title:path.textContent})),
          bars:[...svg.querySelectorAll('rect[data-run-key]')].map(rect=>({key:rect.dataset.runKey,title:rect.parentElement.querySelector('title')?.textContent})),
          canvases:[...svg.querySelectorAll('canvas')].map(canvas=>({width:canvas.width,height:canvas.height}))
        })));
        const invalid=figures.filter(figure=>figure.paths.some(path=>!path.d||/NaN|Infinity/.test(path.d))||figure.canvases.some(c=>c.width<=0||c.height<=0));
        const alerts=await chart.getByRole('alert').allTextContents();
        this.check(`chart-render:${chartIndex}:${name}`,invalid.length===0&&alerts.length===0,{figures,alerts});
        this.current.chartObservations.push({chartIndex,tab:name,figures});
      }
      if(await tabs.count())await tabs.first().click();
    }
    if(await charts.count()) {
      this.check('chart-data-correctness',null,'DOM geometry and available labels recorded; independent raw-source/coordinate and canvas visual review is required');
      this.current.manualReview.push('Check plotted source samples, shared axes, extrema, and canvas/grid colors against saved output responses; rendered element presence is not a data-correctness pass.');
    }
  }

  async capture(directory) {
    const artifacts={screens:[],dom:[],accessibility:[],trace:join(directory,'trace.zip'),browser:join(directory,'browser-observations.json')};
    for(const width of [390,800,1008,1440]) {
      await this.page.setViewportSize({width,height:1000});await pause(150);
      const response=this.page.locator('.agent-response').last();
      if(await response.count())await response.scrollIntoViewIfNeeded().catch(()=>{});
      const layout=await this.page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
        horizontalOverflow:document.documentElement.scrollWidth>innerWidth+1,
        alerts:[...document.querySelectorAll('[role="alert"]')].filter(node=>node.getClientRects().length).map(node=>node.textContent),
        mathErrors:[...document.querySelectorAll('.katex-error,.math-error')].map(node=>node.textContent),
        invalidText:[...document.querySelectorAll('.agent-v2-answer td,.agent-v2-answer th,.agent-v2-answer svg text')]
          .filter(node=>/\b(?:NaN|Infinity|undefined)\b/.test(node.textContent??'')).map(node=>node.textContent),
        zeroSizeCharts:[...document.querySelectorAll('.agent-v2-answer svg[role="img"],.agent-v2-answer canvas')]
          .filter(node=>node.getClientRects().length).filter(node=>node.getBoundingClientRect().width<=0||node.getBoundingClientRect().height<=0).length,
        dialogs:[...document.querySelectorAll('[role="dialog"]')].filter(node=>node.getClientRects().length).length
      }));
      this.check(`layout:${width}`,!layout.horizontalOverflow&&!layout.mathErrors.length&&!layout.invalidText.length&&!layout.zeroSizeCharts,layout);
      const screen=join(directory,`viewport-${width}.png`),dom=join(directory,`viewport-${width}.txt`),ax=join(directory,`viewport-${width}.aria.txt`);
      await this.page.screenshot({path:screen,fullPage:true,timeout:15000});artifacts.screens.push(screen);
      await writeFile(dom,await this.page.locator('body').innerText());artifacts.dom.push(dom);
      if(this.page.locator('body').ariaSnapshot) {
        await writeFile(ax,await this.page.locator('body').ariaSnapshot());artifacts.accessibility.push(ax);
      }
    }
    return artifacts;
  }

  async run(command) {
    demand(this.browser&&this.page,'Initialize the browser bridge before running a case','NOT_INITIALIZED');
    const item=command.case;
    demand(item&&typeof item.id==='string'&&typeof item.question==='string'&&Array.isArray(item.selected)&&Array.isArray(item.hitl),
      'Case requires id, question, selected, and hitl','CONFIG');
    const directory=childPath(this.output,command.output);await mkdir(directory,{recursive:true});
    const state={id:item.id,requestId:null,view:null,interactions:[],uiChecks:[],browserErrors:[],httpErrors:[],outputReads:[],readTasks:[],chartObservations:[],manualReview:[],issues:[]};
    this.current=state;
    let artifacts={},visibleText='',traceStarted=false;
    const started=Date.now(),deadline=started+900000;
    this.deadline=deadline;
    const keyMap=new Map(item.selected.map((id,index)=>[`R${index+1}`,id]));
    try {
      await this.context.tracing.start({screenshots:true,snapshots:true,sources:false});traceStarted=true;
      await this.page.setViewportSize({width:1440,height:1000});
      await this.page.goto(`${this.web}/?view=agent`,{waitUntil:'domcontentloaded',timeout:20000});
      await this.page.bringToFront();
      const prepared=await this.apiCall('/api/workspace');
      const preparedRefs=prepared.candidateReference?.runs??(prepared.conversation?.activeRun?[prepared.conversation.activeRun]:[]);
      demand(equal(preparedRefs.map(ref=>ref.runId),item.selected),'Prepared workspace Run tags differ from this case','PREFLIGHT');
      demand(!prepared.activeAgentRequest&&!prepared.conversation?.turns?.length,'Case requires the prepared fresh conversation','PREFLIGHT');
      const version=this.page.getByRole('combobox',{name:'Agent 버전'});
      await version.waitFor({state:'visible'});
      await this.page.waitForFunction(()=>{const select=document.querySelector('select[aria-label="Agent 버전"]');return select&&!select.disabled;},{},{timeout:15000});
      await version.selectOption('v2');
      await this.page.getByRole('textbox',{name:'공정 데이터에 질문하기',exact:true}).fill(item.question);
      const [acceptedResponse]=await Promise.all([
        this.page.waitForResponse(response=>new URL(response.url()).pathname==='/api/agent/requests'&&response.request().method()==='POST',{timeout:20000}),
        this.page.locator('#agent-query-form [type="submit"]').click()
      ]);
      state.submission=acceptedResponse.request().postDataJSON();
      const accepted=await acceptedResponse.json();
      state.requestId=accepted.requestId??null;state.view=accepted;
      artifacts.accepted=join(directory,'accepted.json');
      await writeFile(artifacts.accepted,JSON.stringify(accepted,null,2));
      await writeFile(join(directory,'submission.json'),JSON.stringify(state.submission,null,2));
      demand(acceptedResponse.ok()&&state.requestId,'Actual UI submission was not accepted','SUBMIT_ERROR');
      this.check('v2-request',accepted.graphVersion==='v2',{graphVersion:accepted.graphVersion,requestId:state.requestId});
      this.check('submitted-question',state.submission.text===item.question,{question:state.submission.text});
      this.check('submitted-run-tags',equal(state.submission.attachedRunRefs?.map(ref=>ref.runId)??[],item.selected),
        {expected:item.selected,actual:state.submission.attachedRunRefs??[]});
      demand(accepted.graphVersion==='v2','UI submission did not use v2','WRONG_GRAPH_VERSION');
      let view=await this.poll(state.requestId,deadline);
      let interactionIndex=0;
      while(view.status==='NEEDS_INPUT') {
        view=await this.resume(view,item.hitl[interactionIndex],item,keyMap,deadline);interactionIndex++;
      }
      state.view=view;
      this.check('hitl-sequence',interactionIndex===item.hitl.length,{expected:item.hitl.length,actual:interactionIndex});
      this.check('completed',view.status==='COMPLETED',{status:view.status,error:view.error});
      if(view.status!=='COMPLETED')state.issues.push({kind:`REQUEST_${view.status}`,message:view.error?.code??view.status});
      if(view.status==='COMPLETED') {
        const answer=this.page.locator('.agent-v2-answer').last();
        await answer.waitFor({state:'visible',timeout:15000});
        await this.page.locator('.agent-response').last().scrollIntoViewIfNeeded();
        visibleText=await answer.innerText();
        this.check('final-answer-visible',normalize(visibleText).length>0,{characters:visibleText.length});
        const questions=await this.page.locator('.agent-user-message').allTextContents();
        this.check('same-question-visible',questions.some(text=>normalize(text).includes(normalize(item.question))),{question:item.question});
        await this.inspectTables(view.answerSnapshot??{});
        await this.inspectCharts();
        visibleText=await answer.innerText();
        await this.page.reload({waitUntil:'domcontentloaded',timeout:20000});
        await this.page.locator('.agent-v2-answer').last().waitFor({state:'visible',timeout:15000});
        const restored=await this.apiCall(`/api/agent/requests/${encodeURIComponent(state.requestId)}`);
        const workspace=await this.apiCall('/api/workspace');
        const saved=workspace.conversation?.turns?.find(turn=>turn.id===view.turnId||turn.id===view.requestId);
        this.check('refresh-restores-same-answer',equal(restored.answerSnapshot,view.answerSnapshot)&&!!saved&&equal(saved.answerSnapshot,view.answerSnapshot),
          {requestId:restored.requestId,turnId:view.turnId,turnPresent:!!saved});
        this.check('refresh-renders-answer',normalize(await this.page.locator('.agent-v2-answer').last().innerText()).length>0,{requestId:state.requestId});
      }
    }catch(error) {
      state.issues.push({kind:error.kind??error.name??'BROWSER_ERROR',message:errorText(error)});
      this.check('case-execution',false,state.issues.at(-1));
      if(!state.requestId) {
        try {const workspace=await this.apiCall('/api/workspace');const active=workspace.activeAgentRequest;
          if(active?.question===item.question){state.requestId=active.requestId;state.view=active;}
        }catch{};
      }
      if(state.requestId&&!terminalStatuses.has(state.view?.status)) {
        try {state.view=await this.apiCall(`/api/agent/requests/${encodeURIComponent(state.requestId)}/cancel`,{method:'POST',body:{}});state.cancelledForCleanup=true;}
        catch(cancelError){state.issues.push({kind:'CLEANUP_FAILED',message:cancelError.message});}
      }
    }finally {
      try{artifacts={...artifacts,...await this.capture(directory)};}catch(error){state.issues.push({kind:'ARTIFACT_ERROR',message:error.message});}
      if(traceStarted) {
        artifacts.trace=join(directory,'trace.zip');
        await this.context.tracing.stop({path:artifacts.trace}).catch(error=>state.issues.push({kind:'TRACE_ERROR',message:error.message}));
      }
      await Promise.allSettled(state.readTasks);
      if(!visibleText)visibleText=await this.page.locator('.agent-page').innerText().catch(()=> '');
      this.check('browser-runtime-errors',state.browserErrors.length===0,{errors:state.browserErrors});
      this.check('browser-http-errors',state.httpErrors.length===0,{errors:state.httpErrors});
      const observations=join(directory,'browser-observations.json');artifacts.browser=observations;
      const {readTasks,...serializable}=state;
      await writeFile(observations,JSON.stringify({...serializable,visibleText,artifacts,elapsedMs:Date.now()-started},null,2));
      this.current=null;
    }
    return {ok:true,view:state.view,requestId:state.requestId,interactions:state.interactions,uiChecks:state.uiChecks,
      uiPass:state.issues.length===0&&state.uiChecks.every(check=>check.pass!==false),visibleText,artifacts,
      manualReview:state.manualReview,issues:state.issues,...(state.issues[0]?{kind:state.issues[0].kind}:
        state.uiChecks.some(check=>check.pass===false)?{kind:'UI_CHECK_FAILED'}:{}),elapsedMs:Date.now()-started};
  }

  async close() {if(this.browser)await this.browser.close();this.browser=null;return {ok:true};}
}

async function main() {
  const bridge=new BrowserBridge();
  const lines=createInterface({input:process.stdin,crlfDelay:Infinity});
  try {
    for await(const line of lines) {
      if(!line.trim())continue;
      let close=false,response;
      try {
        const command=JSON.parse(line);
        if(command.cmd==='init')response=await bridge.init(command);
        else if(command.cmd==='run')response=await bridge.run(command);
        else if(command.cmd==='close'){response=await bridge.close();close=true;}
        else throw Object.assign(new Error('Unknown bridge command'),{kind:'PROTOCOL'});
      }catch(error){response={ok:false,kind:error.kind??error.name??'ERROR',error:errorText(error)};}
      process.stdout.write(`${JSON.stringify(response)}\n`);
      if(close)break;
    }
  }finally{await bridge.close();}
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  main().catch(error=>{process.stderr.write(`browser bridge stopped: ${error.message}\n`);process.exitCode=1;});
}
