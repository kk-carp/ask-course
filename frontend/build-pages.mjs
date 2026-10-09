import { copyFile, cp, writeFile } from 'node:fs/promises';
await writeFile('dist/index.html', `<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>探界 · 课程助手</title></head>
<body><script defer src="./widget.js" data-preview="true"></script></body></html>\n`);
await writeFile('dist/consult.html', `<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>探界 · 课程咨询</title>
<style>body{margin:0;background:#f5f7fb;color:#233047;font:16px/1.8 system-ui,sans-serif}main{max-width:640px;margin:12vh auto;padding:32px}h1{font-size:32px}p{color:#52617a}</style></head>
<body><main><h1>课程咨询</h1><p>咨询入口开放时，可在右下角开始选课咨询。</p><p>对话记录与本浏览器绑定，默认保留 24 小时；清除 Cookie 或换设备后无法恢复。本页暂不连接官网会员账号。</p></main><script defer src="./widget.js" data-mode="site"></script></body></html>\n`);
await copyFile('admin.html', 'dist/admin.html');
await copyFile('answer-format.js', 'dist/answer-format.js');
await cp('vendor', 'dist/vendor', {recursive: true});
