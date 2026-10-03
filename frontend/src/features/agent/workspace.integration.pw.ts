import {registerWorkspaceDecisionGate} from './workspace.integration';
registerWorkspaceDecisionGate({api:process.env.KPLASMA_E2E_API??'http://127.0.0.1:18087',baseURL:process.env.KPLASMA_E2E_BASE_URL??'http://127.0.0.1:5187'});
