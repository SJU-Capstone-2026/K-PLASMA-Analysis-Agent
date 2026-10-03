import {createRoot} from 'react-dom/client';
import {RunDetailDialog} from '../analysis/RunDetail';
import '../../prototype/styles.css';

// Only immutable reference identity comes from the URL; all displayed data uses the real API.
const params=new URLSearchParams(window.location.search);
const runRef={runId:params.get('runId')!,runVersionId:params.get('runVersionId')!};
createRoot(document.getElementById('root')!).render(<RunDetailDialog runRef={runRef} onClose={()=>{}}/>);
