import type {Conversation, GraphVersion} from 'agent';

export type AnalysisGraphVersion = 'v2' | 'v2_localLLM';
const retiredVersions = new Set(['v1', 'v3']);

export function isAnalysisGraphVersion(value: unknown): value is AnalysisGraphVersion {
  return value === 'v2' || value === 'v2_localLLM';
}

export function pinnedConversationGraph({agentGraphVersion, turns}: Conversation): GraphVersion | null {
  return agentGraphVersion ?? (turns.length ? 'v1' : null);
}

export function graphDeployment(): {versions: AnalysisGraphVersion[]; defaultVersion: AnalysisGraphVersion} {
  const raw: string = import.meta.env.VITE_AGENT_SUPPORTED_GRAPH_VERSIONS ?? 'v2';
  const configured = [...new Set(raw.split(',').map(value => value.trim()))];
  const versions = configured.filter(isAnalysisGraphVersion);
  const configuredDefault: string = import.meta.env.VITE_AGENT_DEFAULT_GRAPH_VERSION ?? 'v2';
  const defaultVersion = retiredVersions.has(configuredDefault) ? 'v2' : configuredDefault;
  if (configured.some(version => !isAnalysisGraphVersion(version) && !retiredVersions.has(version))
      || !isAnalysisGraphVersion(defaultVersion) || !versions.includes(defaultVersion)) {
    throw new Error('Invalid Agent graph deployment configuration');
  }
  return {versions, defaultVersion};
}
