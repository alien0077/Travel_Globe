#!/usr/bin/env node
import fs from 'node:fs';
import crypto from 'node:crypto';
import path from 'node:path';

const [htmlPath] = process.argv.slice(2);

if (!htmlPath) {
  console.error('Usage: prepare-ios-replay-html.mjs <index.html>');
  process.exit(1);
}

const html = fs.readFileSync(htmlPath, 'utf8');
const cssPath = path.join(path.dirname(htmlPath), 'index.css');
const cssHash = fs.existsSync(cssPath)
  ? crypto.createHash('sha256').update(fs.readFileSync(cssPath)).digest('hex').slice(0, 12)
  : String(Date.now());
const preparedHtml = html
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
  .replace(/\.\/assets\/index\.css/g, './index.css')
  .replace(/(["'])\.\/index\.css(?:\?v=[^"']*)?\1/g, `$1./index.css?v=${cssHash}$1`)
  .replace(/[ \t]+$/gm, '');

fs.writeFileSync(htmlPath, preparedHtml);
