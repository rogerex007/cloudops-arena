import {after,before,test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import React from 'react';
import {renderToString} from 'react-dom/server';
let root,Timer,Shop,formatTime;
before(async()=>{
 root=mkdtempSync(join(process.cwd(),'.workshop-test-'));
 for(const name of ['MissionTimer','HintShop']){
  const outfile=join(root,name+'.mjs');
  await build({entryPoints:['src/'+name+'.tsx'],outfile,bundle:true,platform:'node',format:'esm',jsx:'automatic',define:{'import.meta.env':'{}'},external:['react','react/jsx-runtime','react-dom','lucide-react']});
  const module=await import(pathToFileURL(outfile).href);
  if(name==='MissionTimer'){Timer=module.default;formatTime=module.formatTime;}else Shop=module.default;
 }
});
after(()=>{if(root)rmSync(root,{recursive:true,force:true});});
test('timer shows closure at zero and preserves paused seconds',()=>{
 assert.equal(formatTime(65),'01:05');
 const expired=renderToString(React.createElement(Timer,{clock:{server_now:100,deadline:100,remaining_seconds:0,paused:false,closed:true}}));
 assert.ok(expired.includes('MISIÓN CERRADA')&&expired.includes('00:00'));
 const paused=renderToString(React.createElement(Timer,{clock:{server_now:100,deadline:120,remaining_seconds:20,paused:true,closed:false}}));
 assert.ok(paused.includes('RELOJ EN PAUSA')&&paused.includes('00:20'));
});
test('shop hides unpurchased content and blocks purchase after deadline',()=>{
 const props={token:'test',mission:'mission',hints:[{id:'hint',title:'Orientation',cost:3,purchased:false,content:'PRIVATE HINT'}],balance:10,closed:true,onChanged:async()=>{}};
 const locked=renderToString(React.createElement(Shop,props));
 assert.ok(!locked.includes('PRIVATE HINT'));
 assert.ok(locked.includes('Misión cerrada')&&locked.includes('disabled'));
 assert.ok(renderToString(React.createElement(Shop,{...props,balance:0})).includes('Misión cerrada'));
 const owned=renderToString(React.createElement(Shop,{...props,hints:[{...props.hints[0],purchased:true}]}));
 assert.ok(owned.includes('PRIVATE HINT'));
 assert.ok(!owned.includes('Comprar por'));
});
