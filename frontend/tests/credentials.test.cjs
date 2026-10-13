const {test}=require('node:test');
const assert=require('node:assert/strict');

test('host credentials only reach same-origin Agent requests and are refreshed per request',async()=>{
 const {authHeaders}=await import('../src/credentials.js');
 global.location={href:'https://site.test/course/42',origin:'https://site.test'};
 let token='synthetic-A';global.ArborseekAgentAuth={getCredential:()=>token};
 assert.deepEqual(authHeaders('https://other.test/agent/widget/config'),{});
 assert.deepEqual(authHeaders('https://site.test/miniapp/me'),{});
 assert.deepEqual(authHeaders('/agent/widget/config'),{Authorization:'Bearer synthetic-A'});
 token='synthetic-B';assert.deepEqual(authHeaders('/agent/ask/stream'),{Authorization:'Bearer synthetic-B'});
 token='';assert.deepEqual(authHeaders('/agent/widget/conversations'),{});
 delete global.ArborseekAgentAuth;assert.deepEqual(authHeaders('/agent/widget/config'),{});
});

test('config-independent history and SSE transport carry the host credential',async()=>{
 const {json,streamAsk}=await import('../src/api.js');
 global.location={href:'https://site.test/course/42',origin:'https://site.test'};
 global.ArborseekAgentAuth={getCredential:()=> 'synthetic-current'};
 const original=global.fetch;const calls=[];
 global.fetch=async(url,options)=>{calls.push({url,options});return url.endsWith('ask/stream')?new Response('event: final\ndata: {"answer":"ok"}\n\n'):new Response('{}')};
 try{
  const api=p=>'https://site.test/agent/'+p;
  await json(api,'widget/conversations');await json(api,'widget/conversations/test/associate','POST');
  assert.equal((await streamAsk(api,{question:'test'},()=>{})).answer,'ok');
  assert.equal(calls.length,3);
  assert.ok(calls.every(c=>c.options.headers.Authorization==='Bearer synthetic-current'));
 }finally{global.fetch=original;delete global.ArborseekAgentAuth}
});

test('non-browser callers and malformed URLs never receive host credentials',async()=>{
 const {authHeaders}=await import('../src/credentials.js');
 const previous=global.location;
 try{
  delete global.location;
  assert.deepEqual(authHeaders('ask/stream'),{});
  global.location={href:'https://site.test/',origin:'https://site.test'};
  assert.deepEqual(authHeaders('http://['),{});
 }finally{if(previous===undefined)delete global.location;else global.location=previous}
});

test('course links use the actual page origin and reject foreign or mismatched destinations',async()=>{
 const {courseUrl}=await import('../src/api.js');
 const previous=global.location;
 try{
  global.location={href:'http://local.test:5173/course/42',origin:'http://local.test:5173'};
  assert.equal(courseUrl({id:'42',source_url:'http://local.test:5173/course/42'}),'http://local.test:5173/course/42');
  assert.equal(courseUrl({id:'42',source_url:'https://foreign.test/course/42'}),'');
  assert.equal(courseUrl({id:'42',source_url:'/course/43'}),'');
  assert.equal(courseUrl({id:'42',source_url:'javascript:alert(1)'}),'');
  assert.equal(courseUrl({id:'42'}),'http://local.test:5173/course/42');
 }finally{if(previous===undefined)delete global.location;else global.location=previous}
});
