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
    const geoNotice = document.querySelector('.geo-notice')?.textContent ?? '';
    const title = document.querySelector('.hud-title')?.textContent ?? '';
    const scrubber = document.querySelector('.timeline-scrubber');
    const viewButtons = [...document.querySelectorAll('.view-mode-button')];
    const activeViewButton = document.querySelector('.view-mode-button.is-active');
    const controls = [...document.querySelectorAll('.control-button')].map((button) => button.textContent);
    const cameraOptions = viewButtons.map((button) => button.getAttribute('aria-label') ?? '');
    const timelineItems = document.querySelectorAll('.timeline-item').length;
    const productText = document.querySelector('.product-panel')?.textContent ?? '';
    const preloadText = document.querySelector('.preload-panel')?.textContent ?? '';
    const preloadFlightNumber = document.querySelector('.preload-field:nth-child(1) input') instanceof HTMLInputElement
      ? document.querySelector('.preload-field:nth-child(1) input')?.value ?? ''
      : '';
    const previewText = document.querySelector('.record-preview')?.textContent ?? '';
    const filterText = document.querySelector('.record-filters')?.textContent ?? '';
    const centerElement = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
    const centerShowsGlobe = centerElement?.tagName === 'CANVAS' || Boolean(centerElement?.closest('.globe-viewport'));
    const pageHasNoVerticalScroll = document.documentElement.scrollHeight <= window.innerHeight + 2;
    const openDockPanels = document.querySelectorAll('.dock-panel[open]').length;
    const recordPreviewVisible = Boolean(document.querySelector('.record-preview')) && filterText.includes('All');

    if (
      !(canvas instanceof HTMLCanvasElement) ||
      !(scrubber instanceof HTMLInputElement) ||
      viewButtons.length === 0
    ) {
      return {
        ok: false,
        reason: 'missing canvas, scrubber, or view rail',
        hud,
        geoNotice,
        title,
        coloredPixels: 0,
        scrubberValue: '',
        cameraValue: '',
        cameraOptions,
        controls,
        timelineItems,
        productText,
        preloadText,
        previewText,
        filterText,
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
        hud.includes('剩餘距離') &&
        hud.includes('預計抵達') &&
        hud.includes('飛行高度') &&
        hud.includes('對氣速度') &&
        geoNotice.includes('附近景點') &&
        geoNotice.includes('在你的') &&
        title.includes('CI100') &&
        controls.includes('Import') &&
        controls.includes('Export') &&
        controls.includes('Share') &&
        controls.includes('使用手冊') &&
        controls.includes('GPX') &&
        controls.includes('KML') &&
        controls.includes('Journal') &&
        controls.includes('Pack') &&
        activeViewButton instanceof HTMLButtonElement &&
        activeViewButton.dataset.mode === 'flightPreview' &&
        cameraOptions.includes('追機視角') &&
        cameraOptions.includes('完整航線') &&
        cameraOptions.includes('中段飛行') &&
        cameraOptions.includes('俯視航線') &&
        cameraOptions.includes('塔台視角') &&
        cameraOptions.includes('飛行員視角') &&
        timelineItems >= 4 &&
        productText.includes('Plan') &&
        productText.includes('Journal') &&
        productText.includes('Trips') &&
        productText.includes('Countries') &&
        (preloadText.includes('預載進入') || preloadText.includes('套用航線')) &&
        (preloadText.includes('CI100') || preloadFlightNumber === 'CI100') &&
        productText.includes('East Asia') &&
        filterText.includes('All') &&
        recordPreviewVisible &&
        previewText.includes('新增事件') &&
        previewText.includes('修改紀錄') &&
        previewText.includes('隱藏紀錄') &&
        previewText.includes('編輯航線摘要') &&
        productText.includes('0 B') &&
        (window.innerWidth <= 640 || centerShowsGlobe) &&
        (window.innerWidth <= 640 || pageHasNoVerticalScroll),
      reason: '',
      hud,
      geoNotice,
      title,
      coloredPixels,
      scrubberValue: scrubber.value,
      cameraValue: activeViewButton instanceof HTMLButtonElement ? activeViewButton.dataset.mode ?? '' : '',
      cameraOptions,
      controls,
      timelineItems,
      productText,
      preloadText,
      previewText,
      filterText,
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
    pilotHudVisible: false,
    pilotHudText: '',
    coloredPixelsAfterInteraction: 0
  };
  let afterPreload = {
    route: '',
    status: '',
    timelineItems: 0
  };

  if (check.ok) {
    await page.evaluate(() => {
      const systemDrawer = document.querySelector('.system-drawer');
      if (systemDrawer instanceof HTMLDetailsElement) {
        systemDrawer.open = true;
      }
      const preloadShell = document.querySelector('.preload-panel-shell');
      if (preloadShell instanceof HTMLDetailsElement) {
        preloadShell.open = true;
      }
    });
    await page.fill('.preload-field:nth-child(1) input', 'CI100');
    await page.fill('.preload-field:nth-child(4) input', '2026-07-11');
    await page.fill('.preload-field:nth-child(5) input', '09:30');
    await page.click('.preload-submit');
    await page.waitForTimeout(500);
    afterPreload = await page.evaluate(() => ({
      route: document.querySelector('.hud-route')?.textContent ?? '',
      status: document.querySelector('.preload-status')?.textContent ?? '',
      timelineItems: document.querySelectorAll('.timeline-item').length
    }));

    await page.evaluate(() => {
      document.querySelector('.controls .control-button')?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    paused = (await page.textContent('.controls .control-button')) ?? '';
    await page.evaluate(() => {
      const scrubber = document.querySelector('.timeline-scrubber');
      if (scrubber instanceof HTMLInputElement) {
        scrubber.value = '700';
        scrubber.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await page.waitForTimeout(150);
    await clickViewMode(page, 'commandCenter');
    await page.waitForTimeout(100);
    await clickViewMode(page, 'midFlight');
    await clickViewMode(page, 'overhead');
    await clickViewMode(page, 'totalRoute');
    await clickViewMode(page, 'pilotView');
    await page.waitForTimeout(100);
    const pilotHudCheck = await page.evaluate(() => {
      const pilotHud = document.querySelector('.pilot-hud');
      return {
        visible: pilotHud instanceof HTMLElement && window.getComputedStyle(pilotHud).display !== 'none',
        text: pilotHud?.textContent ?? ''
      };
    });
    await clickViewMode(page, 'flightPreview');
    await page.waitForTimeout(250);

    afterScrub = await page.evaluate((pilotHudCheck) => ({
      scrubber: document.querySelector('.timeline-scrubber')?.value ?? '',
      point: document.querySelector('.hud-point')?.textContent ?? '',
      stats: document.querySelector('.hud-stats')?.textContent ?? '',
      camera: document.querySelector('.view-mode-button.is-active') instanceof HTMLButtonElement
        ? document.querySelector('.view-mode-button.is-active')?.getAttribute('data-mode') ?? ''
        : '',
      pilotHudVisible: pilotHudCheck.visible,
      pilotHudText: pilotHudCheck.text,
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
    }), pilotHudCheck);

    await page.goto(new URL('./readme.html', url).href, { waitUntil: 'networkidle' });
    const manualCheck = await page.evaluate(() => ({
      title: document.title,
      heading: document.querySelector('strong')?.textContent ?? '',
      hasBackLink: Boolean(document.querySelector('a[href="./index.html"]')),
      hasExports: document.body.textContent?.includes('GPX') && document.body.textContent?.includes('KML')
    }));
    if (
      !manualCheck.title.includes('使用手冊') ||
      !manualCheck.heading.includes('Travel Globe') ||
      !manualCheck.hasBackLink ||
      !manualCheck.hasExports
    ) {
      errors.push(`manual page check failed: ${JSON.stringify(manualCheck)}`);
    }
  }

  results.push({ viewport: viewport.name, errors, blockedExternalRequests, assetRequests, check, paused, afterScrub, afterPreload });
  await page.close();
}

await browser.close();

const failed = results.filter(
  (result) =>
    !result.check.ok ||
    result.errors.length > 0 ||
    result.blockedExternalRequests > 0 ||
    result.assetRequests.length === 0 ||
    !result.afterPreload.route.includes('CI100 | TPE -> NRT') ||
    !result.afterPreload.status.includes('CI100 已由離線班表解析為 TPE -> NRT') ||
    result.afterPreload.timelineItems < 4 ||
    !result.afterScrub.pilotHudVisible ||
    !result.afterScrub.pilotHudText.includes('Airspeed') ||
    !result.afterScrub.pilotHudText.includes('Altitude') ||
    result.afterScrub.coloredPixelsAfterInteraction <= 100
);
console.log(JSON.stringify(results, null, 2));

if (failed.length > 0) {
  process.exitCode = 1;
}

async function clickViewMode(page, mode) {
  await page.evaluate((nextMode) => {
    const button = document.querySelector(`.view-mode-button[data-mode="${nextMode}"]`);
    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  }, mode);
}
