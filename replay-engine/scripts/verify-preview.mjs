import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const url = process.env.TRAVEL_GLOBE_PREVIEW_URL ?? 'http://127.0.0.1:4173/';
const allowedHosts = new Set(['127.0.0.1', 'localhost', new URL(url).hostname]);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const screenshotDir = path.resolve(scriptDir, '../test-results');
fs.mkdirSync(screenshotDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const results = [];

for (const viewport of [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 }
]) {
  const page = await browser.newPage({ viewport });
  const errors = [];
  const assetRequests = [];
  let blockedExternalRequests = 0;

  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') {
      errors.push(message.text());
    }
  });
  await page.route('**/*', (route) => {
    const requestUrl = new URL(route.request().url());
    if (allowedHosts.has(requestUrl.hostname)) {
      if (requestUrl.pathname.includes('blue-marble-land-ocean-ice-2048')) {
        assetRequests.push(requestUrl.pathname);
      }
      void route.continue();
      return;
    }
    blockedExternalRequests += 1;
    void route.abort();
  });

  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForSelector('canvas', { state: 'attached' });
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(screenshotDir, `preview-${viewport.name}.png`) });

  const check = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    const hud = document.querySelector('.hud-stats')?.textContent ?? '';
    const title = document.querySelector('.hud-title')?.textContent ?? '';
    const scrubber = document.querySelector('.timeline-scrubber');
    const cameraSelect = document.querySelector('.camera-select');
    const controls = [...document.querySelectorAll('.control-button')].map((button) => button.textContent);
    const cameraOptions =
      cameraSelect instanceof HTMLSelectElement
        ? [...cameraSelect.options].map((option) => option.textContent)
        : [];
    const timelineItems = document.querySelectorAll('.timeline-item').length;
    const productText = document.querySelector('.product-panel')?.textContent ?? '';
    const centerElement = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
    const centerShowsGlobe = centerElement?.tagName === 'CANVAS' || Boolean(centerElement?.closest('.globe-viewport'));
    const pageHasNoVerticalScroll = document.documentElement.scrollHeight <= window.innerHeight + 2;
    const openDockPanels = document.querySelectorAll('.dock-panel[open]').length;
    const mobileDockStartsCollapsed = window.innerWidth > 640 || openDockPanels === 0;

    if (
      !(canvas instanceof HTMLCanvasElement) ||
      !(scrubber instanceof HTMLInputElement) ||
      !(cameraSelect instanceof HTMLSelectElement)
    ) {
      return {
        ok: false,
        reason: 'missing canvas, scrubber, or camera select',
        hud,
        title,
        coloredPixels: 0,
        scrubberValue: '',
        cameraValue: '',
        cameraOptions,
        controls,
        timelineItems,
        productText,
        centerShowsGlobe,
        pageHasNoVerticalScroll,
        openDockPanels
      };
    }

    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    const sampleCanvas = document.createElement('canvas');
    sampleCanvas.width = 64;
    sampleCanvas.height = 64;
    const sampleContext = sampleCanvas.getContext('2d');
    sampleContext?.drawImage(canvas, 0, 0, 64, 64);
    const image = sampleContext?.getImageData(0, 0, 64, 64).data;
    let coloredPixels = 0;

    if (image) {
      for (let index = 0; index < image.length; index += 4) {
        if (image[index] + image[index + 1] + image[index + 2] > 8) {
          coloredPixels += 1;
        }
      }
    }

    return {
      ok:
        Boolean(gl) &&
        canvas.width > 0 &&
        canvas.height > 0 &&
        coloredPixels > 100 &&
        hud.includes('Altitude') &&
        title.includes('CI100') &&
        controls.includes('Import') &&
        controls.includes('Export') &&
        controls.includes('Share JSON') &&
        controls.includes('GPX') &&
        controls.includes('KML') &&
        controls.includes('Journal') &&
        controls.includes('Install Pack') &&
        cameraSelect.value === 'global' &&
        cameraOptions.includes('Global View') &&
        cameraOptions.includes('Orbit cinema') &&
        cameraOptions.includes('Cockpit view') &&
        cameraOptions.includes('Left window') &&
        cameraOptions.includes('Right window') &&
        cameraOptions.includes('Tail chase') &&
        cameraOptions.includes('Top down') &&
        timelineItems >= 4 &&
        productText.includes('Plan') &&
        productText.includes('Journal') &&
        productText.includes('Time Machine') &&
        productText.includes('Auto Recording') &&
        productText.includes('0 B') &&
        centerShowsGlobe &&
        pageHasNoVerticalScroll &&
        mobileDockStartsCollapsed,
      reason: '',
      hud,
      title,
      coloredPixels,
      scrubberValue: scrubber.value,
      cameraValue: cameraSelect.value,
      cameraOptions,
      controls,
      timelineItems,
      productText,
      centerShowsGlobe,
      pageHasNoVerticalScroll,
      openDockPanels
    };
  });

  let paused = '';
  let afterScrub = {
    scrubber: '',
    point: '',
    stats: '',
    camera: '',
    coloredPixelsAfterInteraction: 0
  };

  if (check.ok) {
    await page.evaluate(() => {
      document.querySelector('.control-button')?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    paused = (await page.textContent('.control-button')) ?? '';
    await page.evaluate(() => {
      const scrubber = document.querySelector('.timeline-scrubber');
      if (scrubber instanceof HTMLInputElement) {
        scrubber.value = '700';
        scrubber.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await page.waitForTimeout(150);
    await page.selectOption('.camera-select', 'cockpit');
    await page.waitForTimeout(100);
    await page.mouse.move(viewport.width / 2, viewport.height / 2);
    await page.mouse.down();
    await page.mouse.move(viewport.width / 2 + 70, viewport.height / 2 - 30, { steps: 8 });
    await page.mouse.up();
    await page.mouse.wheel(0, -280);
    await page.selectOption('.camera-select', 'leftWindow');
    await page.selectOption('.camera-select', 'rightWindow');
    await page.selectOption('.camera-select', 'tail');
    await page.selectOption('.camera-select', 'topDown');
    await page.selectOption('.camera-select', 'global');
    await page.waitForTimeout(250);

    afterScrub = await page.evaluate(() => ({
      scrubber: document.querySelector('.timeline-scrubber')?.value ?? '',
      point: document.querySelector('.hud-point')?.textContent ?? '',
        stats: document.querySelector('.hud-stats')?.textContent ?? '',
      camera: document.querySelector('.camera-select') instanceof HTMLSelectElement
        ? document.querySelector('.camera-select')?.value ?? ''
        : '',
      coloredPixelsAfterInteraction: (() => {
        const canvas = document.querySelector('canvas');
        if (!(canvas instanceof HTMLCanvasElement)) {
          return 0;
        }
        const sampleCanvas = document.createElement('canvas');
        sampleCanvas.width = 64;
        sampleCanvas.height = 64;
        const context = sampleCanvas.getContext('2d');
        context?.drawImage(canvas, 0, 0, 64, 64);
        const image = context?.getImageData(0, 0, 64, 64).data;
        let coloredPixels = 0;
        if (image) {
          for (let index = 0; index < image.length; index += 4) {
            if (image[index] + image[index + 1] + image[index + 2] > 8) {
              coloredPixels += 1;
            }
          }
        }
        return coloredPixels;
      })()
    }));
  }

  results.push({ viewport: viewport.name, errors, blockedExternalRequests, assetRequests, check, paused, afterScrub });
  await page.close();
}

await browser.close();

const failed = results.filter(
  (result) =>
    !result.check.ok ||
    result.errors.length > 0 ||
    result.blockedExternalRequests > 0 ||
    result.assetRequests.length === 0 ||
    result.afterScrub.coloredPixelsAfterInteraction <= 100
);
console.log(JSON.stringify(results, null, 2));

if (failed.length > 0) {
  process.exitCode = 1;
}
