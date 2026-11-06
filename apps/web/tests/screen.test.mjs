import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import React from 'react';
import {renderToString} from 'react-dom/server';

test('projection handles empty scores and safely renders participant names and equal ranks',async()=>{
 const directory=mkdtempSync(join(process.cwd(),'.screen-test-'));
 try{
  const outfile=join(directory,'screen.mjs');
  await build({entryPoints:['src/LeaderboardScreen.tsx'],outfile,bundle:true,platform:'node',format:'esm',jsx:'automatic',define:{'import.meta.env':'{}'},external:['react','react/jsx-runtime','lucide-react']});
  const {ScreenTable}=await import(pathToFileURL(outfile).href);
  const html=renderToString(React.createElement(ScreenTable,{data:{participation_mode:'individual',leaderboard:[{rank:1,name:'<script>alert(1)</script>',score:0},{rank:1,name:'Beto',score:0}]}}));
  assert.ok(html.includes('Participante'));assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;script&gt;'));
  assert.equal((html.match(/>01</g)||[]).length,2);
 }finally{rmSync(directory,{recursive:true,force:true});}
});
