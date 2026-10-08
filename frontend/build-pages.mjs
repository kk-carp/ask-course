import { copyFile, cp, writeFile } from 'node:fs/promises';
await writeFile('dist/index.html', `<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>探界 · 课程助手</title></head>
<body><script defer src="./widget.js" data-preview="true"></script></body></html>\n`);
await copyFile('admin.html', 'dist/admin.html');
await copyFile('answer-format.js', 'dist/answer-format.js');
await cp('vendor', 'dist/vendor', {recursive: true});
