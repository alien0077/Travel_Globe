#!/usr/bin/env node
import fs from 'node:fs';

const [htmlPath] = process.argv.slice(2);

if (!htmlPath) {
  console.error('Usage: prepare-ios-replay-html.mjs <index.html>');
  process.exit(1);
}

const html = fs.readFileSync(htmlPath, 'utf8');
const preparedHtml = html
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
  .replace(/\.\/assets\/index\.css/g, './index.css')
  .replace(/[ \t]+$/gm, '');

fs.writeFileSync(htmlPath, preparedHtml);
