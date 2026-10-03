// Explicit test-only entry: production main never imports this synthetic harness.
import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {App} from '../../App';
import {CatalogPage,initialCatalogState} from './CatalogPage';
function Harness(){const [state,setState]=useState(initialCatalogState);return <App pages={{catalog:context=><CatalogPage context={context} state={state} onStateChange={setState} onReference={ref=>context.notify(`선택 ${ref.runId}`)}/>}}/>;}
createRoot(document.getElementById('root')!).render(<Harness/>);
