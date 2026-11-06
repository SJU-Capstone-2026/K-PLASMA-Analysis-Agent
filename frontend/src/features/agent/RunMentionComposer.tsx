import {useEffect, useId, useLayoutEffect, useRef, useState} from 'react';
import type {RunRef, RunSummary} from 'agent';
import {fetchRuns} from '../../api/runs';

function mentionAt(text: string, caret: number) {
  const match = /(?:^|\s)@(RUN(?:-[A-Z0-9-]*)?)$/i.exec(text.slice(0, caret));
  if (!match) return null;
  const start = caret - match[1].length - 1;
  const end = caret + (/^[A-Z0-9-]*/i.exec(text.slice(caret))?.[0].length ?? 0);
  return {query: match[1].toUpperCase(), start, end};
}

export function RunMentionComposer({text, onText, add, disabled, onStop}: {
  text: string;
  onText: (update: (current: string) => string) => void;
  add: (ref: RunRef) => Promise<boolean>;
  disabled: boolean;
  onStop?: () => Promise<void>;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  const suggestions = useRef<HTMLElement>(null);
  const listId = useId();
  const [caret, setCaret] = useState(0);
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [index, setIndex] = useState(0);
  const [catalog, setCatalog] = useState<RunSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [stopping, setStopping] = useState(false);
  const mention = focused && !dismissed && !disabled ? mentionAt(text, caret) : null;
  const open = Boolean(mention);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    fetchRuns(controller.signal).then(runs => {
      if (!controller.signal.aborted) setCatalog(runs);
    }).catch(() => {
      if (!controller.signal.aborted) setFailed(true);
    });
    return () => {
      controller.abort();
      setCatalog(null);
      setFailed(false);
    };
  }, [open]);

  const matches = mention
    ? (catalog ?? []).filter(run => run.runId.toUpperCase().startsWith(mention.query))
    : [];
  const highlighted = Math.min(index, matches.length - 1);

  useLayoutEffect(() => {
    const panel = suggestions.current;
    const option = panel?.querySelector('[aria-selected="true"]');
    if (!panel || !option) return;
    const {top, bottom} = option.getBoundingClientRect();
    const visibleTop = panel.getBoundingClientRect().top + panel.clientTop;
    const visibleBottom = visibleTop + panel.clientHeight;
    if (top < visibleTop) panel.scrollTop += top - visibleTop;
    else if (bottom > visibleBottom) panel.scrollTop += bottom - visibleBottom;
  }, [highlighted, mention?.query]);

  async function choose(run: RunSummary) {
    if (!mention) return;
    const remaining = text.slice(0, mention.start) + text.slice(mention.end);
    setDismissed(true);
    onText(current => current === text ? remaining : current);
    requestAnimationFrame(() => {
      input.current?.focus({preventScroll: true});
      input.current?.setSelectionRange(mention.start, mention.start);
      setCaret(mention.start);
    });
    if (!await add({runId: run.runId, runVersionId: run.runVersionId})) {
      onText(current => current === remaining ? text : current);
    }
  }

  async function stop() {
    if (!onStop || stopping) return;
    setStopping(true);
    try { await onStop(); }
    finally { setStopping(false); }
  }

  return <>
    {open && <section ref={suggestions} className="run-mention-suggestions" aria-label="Run 자동완성">
      {matches.length ? <ul id={listId} role="listbox" aria-label="일치하는 Run">
        {matches.map((run, i) => <li key={run.runVersionId} id={`${listId}-${i}`} role="option"
          aria-selected={i === highlighted} onMouseDown={event => event.preventDefault()}
          onClick={() => void choose(run)}>
          <strong>@{run.runId}</strong>
          <span>{run.pressure} mTorr · Source {run.sourcePower} W · Bias {run.biasPower} W</span>
        </li>)}
      </ul> : <p role="status">{failed ? 'Run 목록을 불러오지 못했습니다.' : catalog ? '일치하는 Run이 없습니다.' : 'Run 목록을 불러오는 중입니다.'}</p>}
    </section>}
    <div className="agent-composer-input">
      <textarea ref={input} id="agent-query" name="queryText" rows={1} required
        aria-label="공정 데이터에 질문하기" aria-autocomplete="list"
        aria-controls={matches.length ? listId : undefined}
        aria-activedescendant={highlighted >= 0 ? `${listId}-${highlighted}` : undefined}
        placeholder="조건, 목표, 변화 이유를 질문하거나 @RUN으로 실험을 추가하세요"
        value={text}
        onFocus={event => {setFocused(true);setCaret(event.currentTarget.selectionStart);}}
        onBlur={() => {setFocused(false);setDismissed(false);}}
        onSelect={event => setCaret(event.currentTarget.selectionStart)}
        onChange={event => {
          const {value, selectionStart} = event.currentTarget;
          onText(() => value);
          setCaret(selectionStart);
          setIndex(0);
          setDismissed(false);
        }}
        onKeyDown={event => {
          if (event.nativeEvent.isComposing || event.keyCode === 229) return;
          if (open && event.key === 'Escape') {
            event.preventDefault();
            setDismissed(true);
          } else if (matches.length && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
            event.preventDefault();
            const direction = event.key === 'ArrowDown' ? 1 : -1;
            setIndex((highlighted + direction + matches.length) % matches.length);
          } else if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            if (disabled) return;
            if (highlighted >= 0) void choose(matches[highlighted]);
            else if (text.trim()) event.currentTarget.form?.requestSubmit();
          }
        }}/>
      {onStop ? <button className="button agent-send agent-send--stop" type="button"
        aria-label="분석 중지" title="분석 중지" aria-busy={stopping} disabled={stopping} onClick={() => void stop()}>
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">
          <rect x="6" y="6" width="12" height="12" rx="2"/>
        </svg>
      </button> : <button className="button agent-send" type="submit" aria-label="분석" disabled={disabled}>
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 19V5m-6 6 6-6 6 6"/>
        </svg>
      </button>}
    </div>
  </>;
}
