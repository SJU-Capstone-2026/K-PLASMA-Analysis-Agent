/* eslint-disable @typescript-eslint/no-unused-vars -- Preserve original omission destructuring and storage catch bindings. */
// v12.3.1: preserved pure implementation; only IIFE/module boundaries changed.


const STORAGE_KEY = 'kplasma.prototype.agentConversation.v1';
const VERSION = 1;
const ALLOWED_UI_KEYS = new Set([
  'collapsed',
  'openRunIds',
  'runDetailTabs',
  'activeCandidateGroup',
  'continuedRunId',
  'lookupExpanded',
  'selectedCandidateRunId',
]);
let sequence = 0;

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function createTurnUi() {
  return {
    collapsed: false,
    openRunIds: [],
    runDetailTabs: {},
    activeCandidateGroup: 'common',
    continuedRunId: null,
    lookupExpanded: false,
    selectedCandidateRunId: null,
  };
}

function createEmpty() {
  return { version: VERSION, activeRunId: null, turns: [] };
}

function isCompactSnapshot(value, key = '') {
  if (value === null || typeof value !== 'object') return true;
  if (key === 'run' || key === 'graphs' || key === 'series' || key === 'analysis') return false;
  if (Array.isArray(value)) return value.every((item) => isCompactSnapshot(item, key));
  return Object.entries(value).every(([childKey, child]) => isCompactSnapshot(child, childKey));
}

function normalizeTurn(input) {
  if (!input || typeof input !== 'object') throw new Error('대화 턴 정보가 필요합니다.');
  if (!input.answerSnapshot || !isCompactSnapshot(input.answerSnapshot)) {
    throw new Error('대화에는 압축된 답변 스냅샷만 저장할 수 있습니다.');
  }
  sequence += 1;
  return {
    id: String(input.id || `turn-${Date.now()}-${sequence}`),
    askedAt: String(input.askedAt || new Date().toISOString()),
    question: String(input.question || '').trim(),
    intent: String(input.intent || 'UNSUPPORTED'),
    contextRunId: input.contextRunId ? String(input.contextRunId) : null,
    answerSnapshot: clone(input.answerSnapshot),
    ui: { ...createTurnUi(), ...(input.ui ? clone(input.ui) : {}) },
  };
}

function appendTurn(conversation, input) {
  const current = conversation && conversation.version === VERSION ? conversation : createEmpty();
  return {
    version: VERSION,
    activeRunId: current.activeRunId || null,
    turns: [...current.turns.map(clone), normalizeTurn(input)],
  };
}

function setActiveRun(conversation, runId) {
  const current = conversation && conversation.version === VERSION ? conversation : createEmpty();
  return {
    version: VERSION,
    activeRunId: runId ? String(runId) : null,
    turns: current.turns.map(clone),
  };
}

function updateTurnUi(conversation, turnId, patch) {
  const current = conversation && conversation.version === VERSION ? conversation : createEmpty();
  const safePatch = Object.fromEntries(
    Object.entries(patch || {}).filter(([key]) => ALLOWED_UI_KEYS.has(key)),
  );
  return {
    version: VERSION,
    activeRunId: current.activeRunId || null,
    turns: current.turns.map((turn) => {
      if (turn.id !== turnId) return clone(turn);
      return {
        ...clone(turn),
        ui: { ...createTurnUi(), ...clone(turn.ui || {}), ...clone(safePatch) },
      };
    }),
  };
}

function normalizeLoaded(parsed) {
  if (!parsed || parsed.version !== VERSION || !Array.isArray(parsed.turns)) return createEmpty();
  return {
    version: VERSION,
    activeRunId: parsed.activeRunId ? String(parsed.activeRunId) : null,
    turns: parsed.turns.map((turn) => ({
      id: String(turn.id),
      askedAt: String(turn.askedAt || ''),
      question: String(turn.question || ''),
      intent: String(turn.intent || 'UNSUPPORTED'),
      contextRunId: turn.contextRunId ? String(turn.contextRunId) : null,
      answerSnapshot: clone(turn.answerSnapshot || {}),
      ui: { ...createTurnUi(), ...clone(turn.ui || {}) },
    })),
  };
}

function load(storage) {
  try {
    const raw = storage && typeof storage.getItem === 'function' && storage.getItem(STORAGE_KEY);
    if (!raw) return createEmpty();
    return normalizeLoaded(JSON.parse(raw));
  } catch (error) {
    return createEmpty();
  }
}

function save(storage, conversation) {
  const current = normalizeLoaded(conversation);
  try {
    if (storage && typeof storage.setItem === 'function') {
      storage.setItem(STORAGE_KEY, JSON.stringify(current));
    }
  } catch (error) {
    // Browsers can deny storage in private or file modes; in-memory state remains usable.
  }
  return current;
}

function clear(storage) {
  try {
    if (storage && typeof storage.removeItem === 'function') storage.removeItem(STORAGE_KEY);
  } catch (error) {
    // Clearing is best-effort when browser storage is unavailable.
  }
  return createEmpty();
}

export {
    STORAGE_KEY,
    VERSION,
    createEmpty,
    createTurnUi,
    appendTurn,
    setActiveRun,
    updateTurnUi,
    load,
    save,
    clear,
  };
