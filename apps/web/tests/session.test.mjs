import {test} from 'node:test';
import assert from 'node:assert/strict';
import {isInstructorPath, loadSession, saveSession, clearSession} from '../src/session.ts';

function storage(initial={}) {
  const data=new Map(Object.entries(initial));
  return {getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key)};
}

test('only canonical instructor routes select the console',()=>{
  for(const path of ['/instructor','/instructor/','/instructor/events']) assert.equal(isInstructorPath(path),true);
  for(const path of ['/','/instructor-public','/INSTRUCTOR','/participant','/api/v1/admin']) assert.equal(isInstructorPath(path),false);
});

test('participant and instructor can coexist and log out independently',()=>{
  const local=storage(),tab=storage();
  saveSession(false,'participant-token','participant',local,tab);
  local.setItem('arena-participant','participant-info');
  tab.setItem('arena-team-invite','invitation');
  saveSession(true,'admin-token','admin',local,tab);
  assert.deepEqual(loadSession(false,local,tab),{token:'participant-token',role:'participant'});
  assert.deepEqual(loadSession(true,local,tab),{token:'admin-token',role:'admin'});
  clearSession(true,local,tab);
  assert.equal(local.getItem('arena-token'),'participant-token');
  assert.equal(tab.getItem('arena-team-invite'),'invitation');
  saveSession(true,'admin-token','admin',local,tab);
  clearSession(false,local,tab);
  assert.equal(local.getItem('arena-participant'),null);
  assert.equal(tab.getItem('arena-team-invite'),null);
  assert.equal(loadSession(true,local,tab).token,'admin-token');
});

test('the public portal ignores an old shared administrator session',()=>{
  const local=storage({'arena-token':'legacy-admin','arena-role':'admin'}),tab=storage();
  assert.deepEqual(loadSession(false,local,tab),{token:'',role:''});
  assert.equal(local.getItem('arena-token'),'legacy-admin');
  assert.deepEqual(loadSession(true,local,tab),{token:'legacy-admin',role:'admin'});
  assert.equal(local.getItem('arena-token'),null);
  assert.equal(loadSession(true,local,tab).token,'legacy-admin');
});

test('entering instructor does not reuse a participant token',()=>{
  const local=storage({'arena-token':'player','arena-role':'participant'}),tab=storage();
  assert.deepEqual(loadSession(true,local,tab),{token:'',role:''});
  assert.equal(local.getItem('arena-token'),'player');
  assert.throws(()=>saveSession(false,'admin','admin',local,tab));
  assert.throws(()=>saveSession(true,'player','participant',local,tab));
});
