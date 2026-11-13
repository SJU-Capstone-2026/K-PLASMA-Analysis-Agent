import react from '@vitejs/plugin-react';
import { randomBytes } from 'node:crypto';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', 'VITE_');
  const local = env.VITE_AGENT_DEFAULT_GRAPH_VERSION === 'v2_localLLM'
    || (env.VITE_AGENT_SUPPORTED_GRAPH_VERSIONS || '').split(',').some(version => version.trim() === 'v2_localLLM');
  const nonce = local ? randomBytes(18).toString('base64') : undefined;
  const target = env.VITE_API_TARGET || (local ? 'http://127.0.0.1:8080' : 'http://localhost:8080');
  if (local) {
    const url = new URL(target);
    if (url.protocol !== 'http:' || !['127.0.0.1', '[::1]'].includes(url.hostname) || !url.port
        || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
      throw new Error('LOCAL_API_TARGET_INVALID');
    }
  }
  return {
    plugins: [react()],
    html: { cspNonce: nonce },
    server: {
      port: 5173,
      strictPort: true,
      host: local ? '127.0.0.1' : undefined,
      headers: local ? {
        'Content-Security-Policy': `default-src 'self'; script-src 'self' 'nonce-${nonce}'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' ws://127.0.0.1:5173; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`,
        'Referrer-Policy': 'no-referrer',
      } : undefined,
      proxy: { '/api': { target, changeOrigin: true } },
    },
  };
});
