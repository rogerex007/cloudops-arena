import {after, before, test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, rmSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import React from 'react';
import {renderToString} from 'react-dom/server';

let directory, App;
function storage(initial={}) {
  const data=new Map(Object.entries(initial));
  return {getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key)};
}
function render(path,local={}) {
  globalThis.window={location:{pathname:path,search:'',origin:'https://arena.test'}};
  globalThis.localStorage=storage(local);
  globalThis.sessionStorage=storage();
  return renderToString(React.createElement(App));
}

before(async()=>{
  directory=mkdtempSync(join(process.cwd(),'.route-test-'));
  const outfile=join(directory,'app.mjs');
  await build({entryPoints:['src/App.tsx'],outfile,bundle:true,platform:'node',format:'esm',jsx:'automatic',
    loader:{'.css':'empty'},define:{'import.meta.env':'{}'},external:['react','react/jsx-runtime','react-dom','lucide-react']});
  App=(await import(pathToFileURL(outfile).href)).default;
});
after(()=>{if(directory)rmSync(directory,{recursive:true,force:true});});

test('public page only renders participant entry, including legacy admin browsers',()=>{
  for(const local of [{},{'arena-token':'old-admin','arena-role':'admin'}]) {
    const html=render('/',local);
    assert.ok(html.includes('Entra a la Arena'));
    assert.ok(!html.includes('Acceso del instructor'));
    assert.ok(!html.includes('Panel del instructor'));
    assert.ok(!html.includes('LOCAL DEMO'));
  }
});

test('instructor and its children render login without overwriting participant session',()=>{
  for(const path of ['/instructor','/instructor/','/instructor/events']) {
    const html=render(path,{'arena-token':'player','arena-role':'participant'});
    assert.ok(html.includes('Panel del instructor'));
    assert.ok(!html.includes('Entra a la Arena'));
    assert.ok(html.includes('href="/"'));
    assert.equal(localStorage.getItem('arena-token'),'player');
  }
});
