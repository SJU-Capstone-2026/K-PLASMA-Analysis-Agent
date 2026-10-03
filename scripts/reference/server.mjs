import {createServer} from 'node:http';
import {readFile,stat,realpath} from 'node:fs/promises';
import {resolve,relative,extname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadReference} from './load.mjs';

export async function serveReference(reference, port = 0) {
  const root = await realpath(reference.prototypeRoot);
  const server = createServer(async(req,res)=>{
    try {
      const path = resolve(root, `.${decodeURIComponent(new URL(req.url,'http://localhost').pathname)}`);
      const file = (await stat(path)).isDirectory() ? resolve(path,'index.html') : path;
      const rel = relative(root, await realpath(file));
      if (rel.startsWith('..') || rel.includes('\\')) {res.writeHead(403).end();return;}
      const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml'};
      res.setHeader('Content-Type',mime[extname(file)] ?? 'application/octet-stream');
      res.end(await readFile(file));
    } catch {res.writeHead(404).end();}
  });
  await new Promise(resolve=>server.listen(port,'127.0.0.1',resolve));
  return {url:`http://127.0.0.1:${server.address().port}`,close:()=>new Promise(resolve=>server.close(resolve))};
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const server = await serveReference(await loadReference(process.env.KPLASMA_REFERENCE_ROOT),Number(process.env.KPLASMA_REFERENCE_PORT ?? 8085));
  console.log(`Checked local prototype: ${server.url}`);
}
