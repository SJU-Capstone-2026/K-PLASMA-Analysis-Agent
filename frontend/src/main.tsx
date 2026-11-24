import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import {App} from './App';
import {bootstrapLocalSession} from './api/local-session';

const render=()=>createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
const bootstrap=bootstrapLocalSession();
if(bootstrap)void bootstrap.then(render,render);
else render();
