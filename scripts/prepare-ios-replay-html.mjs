#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const [htmlPath] = process.argv.slice(2);

if (!htmlPath) {
  console.error('Usage: prepare-ios-replay-html.mjs <index.html>');
  process.exit(1);
}

const html = fs.readFileSync(htmlPath, 'utf8');
const cssPath = path.join(path.dirname(htmlPath), 'index.css');
const css = fs.existsSync(cssPath) ? fs.readFileSync(cssPath, 'utf8') : '';
const preparedHtml = html
  .replace(/\.\/assets\/index\.css/g, './index.css')
  .replace(/<link\b[^>]*href=["']\.\/index\.css(?:\?v=[^"']*)?["'][^>]*>/g, `<style>\n${css}\n</style>`)
  .replace(/[ \t]+$/gm, '');

fs.writeFileSync(htmlPath, preparedHtml);
