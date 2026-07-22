import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import zlib from 'node:zlib';
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
  console.error(`[verify-preview] ${viewport.name}: opening page`);
  const page = await browser.newPage({ viewport, acceptDownloads: true });
  page.setDefaultTimeout(10_000);
  page.setDefaultNavigationTimeout(20_000);
  const errors = [];
  const assetRequests = [];
  let blockedExternalRequests = 0;

  page.on('pageerror', (error) => errors.push(error.message));
  page.on('download', (download) => {
    void download.cancel().catch(() => undefined);
  });
  page.on('console', (message) => {
    if (message.type() === 'error') {
      errors.push(message.text());
    }
  });
  await page.route('**/*', (route) => {
    const requestUrl = new URL(route.request().url());
    if (allowedHosts.has(requestUrl.hostname)) {
      if (
        requestUrl.pathname.includes('blue-marble-land-ocean-ice-2048') ||
        requestUrl.pathname.includes('earth-lights-2048') ||
        requestUrl.pathname.includes('earth-clouds-1024') ||
        requestUrl.pathname.includes('earth-specular-2048')
      ) {
        assetRequests.push(requestUrl.pathname);
      }
      void route.continue();
      return;
    }
    blockedExternalRequests += 1;
    void route.abort();
  });

  await page.goto(url, { waitUntil: 'networkidle' });
  console.error(`[verify-preview] ${viewport.name}: page loaded`);
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
    const preloadFlightNumber = document.querySelector('.preload-field:nth-child(2) input') instanceof HTMLInputElement
      ? document.querySelector('.preload-field:nth-child(2) input')?.value ?? ''
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
        previewText.includes('載入最新') &&
        previewText.includes('隱藏紀錄') &&
        previewText.includes('編輯航線摘要') &&
        previewText.includes('本機歷史旅程') &&
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
  let mobileRegression = null;

  if (check.ok) {
    await page.evaluate(() => {
      const systemSummary = document.querySelector('.system-drawer > .panel-summary');
      if (systemSummary instanceof HTMLButtonElement) {
        systemSummary.click();
      }
      const preloadShell = document.querySelector('.preload-panel-shell');
      if (preloadShell instanceof HTMLDetailsElement) {
        preloadShell.open = true;
      }
    });
    await page.fill('.preload-field:nth-child(2) input', 'CI100');
    await page.fill('.preload-field:nth-child(5) input', '2026-07-11');
    await page.fill('.preload-field:nth-child(6) input', '09:30');
    await page.evaluate(() => {
      const submit = document.querySelector('.preload-submit');
      if (submit instanceof HTMLButtonElement) {
        submit.click();
      }
    });
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

    if (viewport.name === 'mobile') {
      console.error('[verify-preview] mobile: running FD234 regression');
      mobileRegression = await withTimeout(
        verifyMobileFd234Regression(page),
        180_000,
        'FD234 regression timed out after 180s'
      );
      console.error(`[verify-preview] mobile: FD234 regression ${mobileRegression.ok ? 'ok' : 'failed'}`);
    }
  }

  results.push({ viewport: viewport.name, errors, blockedExternalRequests, assetRequests, check, paused, afterScrub, afterPreload, mobileRegression });
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
    result.afterScrub.coloredPixelsAfterInteraction <= 100 ||
    (result.mobileRegression !== null && !result.mobileRegression.ok)
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

async function verifyMobileFd234Regression(page) {
  const screenshotPath = path.join(screenshotDir, 'mobile-fd234-regression.png');
  const daylightScreenshotPath = path.join(screenshotDir, 'mobile-fd234-takeoff-daylight.png');
  const preloadScreenshotPath = path.join(screenshotDir, 'mobile-preload-regression.png');
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForSelector('.hud-title', { state: 'visible' });
  await page.waitForTimeout(900);

  const report = {
    ok: false,
    hitTargets: [],
    actionStatuses: [],
    preloadVisible: {},
    drawerMetrics: {},
    cardMetrics: {},
    takeoffFocus: {},
    approachFocus: {},
    arrivalFocus: {},
    brightness: {},
    daylightBrightness: {},
    nightRegression: {},
    screenshotPath,
    daylightScreenshotPath,
    approachScreenshotPath: path.join(screenshotDir, 'mobile-fd234-approach-airport.png'),
    arrivalScreenshotPath: path.join(screenshotDir, 'mobile-fd234-arrival-airport.png'),
    nightScreenshotPath: path.join(screenshotDir, 'mobile-fd234-night-regression.png'),
    travelAtlasScreenshotPath: path.join(screenshotDir, 'mobile-travel-atlas-expanded.png'),
    timelineScreenshotPath: path.join(screenshotDir, 'mobile-travel-record-expanded.png'),
    preloadScreenshotPath,
    failure: ''
  };

  try {
    console.error('[verify-preview] mobile: FD234 step drawer toggle');
    await dispatchClick(page, '.system-drawer > .panel-summary');
    await page.waitForTimeout(250);
    assert((await page.locator('.system-drawer.is-open').count()) === 1, 'system drawer did not open');
    await dispatchClick(page, '.system-drawer > .panel-summary');
    await page.waitForTimeout(250);
    assert((await page.locator('.system-drawer.is-open').count()) === 0, 'system drawer did not close from summary button');
    await dispatchClick(page, '.system-drawer > .panel-summary');
    await page.waitForTimeout(250);

    assert((await page.locator('.preload-panel-shell[open]').count()) === 1, 'preload/API key panel should be open by default on mobile drawer');
    console.error('[verify-preview] mobile: FD234 step preload visibility');
    for (const label of ['aviationstack API key（保存在本機）', '航班號', '起飛', '抵達', '日期', '時間', '機型', '套用航線']) {
      report.preloadVisible[label] = await page.getByText(label, { exact: true }).first().isVisible().catch(() => false);
      assert(report.preloadVisible[label], `preload field not visible: ${label}`);
    }
    await page.screenshot({ path: preloadScreenshotPath, fullPage: false });

    report.drawerMetrics = await page.evaluate(() => {
      const drawer = document.querySelector('.system-drawer')?.getBoundingClientRect();
      const preload = document.querySelector('.preload-panel-shell')?.getBoundingClientRect();
      const controls = document.querySelector('.controls')?.getBoundingClientRect();
      const actionGrid = document.querySelector('.action-grid');
      return {
        drawerBottom: drawer?.bottom,
        preloadBottom: preload?.bottom,
        controlsTop: controls?.top,
        actionGridHidden: actionGrid ? getComputedStyle(actionGrid).display === 'none' : false
      };
    });
    assert(report.drawerMetrics.actionGridHidden, 'action grid should hide while preload is open on mobile');
    assert(report.drawerMetrics.preloadBottom <= report.drawerMetrics.drawerBottom + 1, `preload panel overflowed drawer: ${JSON.stringify(report.drawerMetrics)}`);
    assert(report.drawerMetrics.drawerBottom < report.drawerMetrics.controlsTop, `drawer overlaps controls: ${JSON.stringify(report.drawerMetrics)}`);

    await setDetailsOpen(page, '.preload-panel-shell', false);
    await page.waitForTimeout(200);

    console.error('[verify-preview] mobile: FD234 step action hit targets');
    const labels = ['Import', 'Export', 'Share', '使用手冊', 'GPX', 'KML', 'Journal', 'Pack'];
    report.hitTargets = await page.evaluate((buttonLabels) => buttonLabels.map((label) => {
      const nodes = [...document.querySelectorAll('.action-grid button, .action-grid a')];
      const node = nodes.find((candidate) => candidate.textContent?.trim() === label);
      if (!node) {
        return { label, found: false };
      }
      const rect = node.getBoundingClientRect();
      const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return {
        label,
        found: true,
        width: rect.width,
        height: rect.height,
        topText: top?.textContent?.trim() ?? ''
      };
    }), labels);

    for (const target of report.hitTargets) {
      assert(target.found, `${target.label} button missing`);
      assert(target.width >= 90 && target.height >= 34, `${target.label} button too small: ${JSON.stringify(target)}`);
      assert(
        target.topText === target.label || target.topText.includes(target.label),
        `${target.label} center is blocked: ${JSON.stringify(target)}`
      );
    }

    console.error('[verify-preview] mobile: FD234 step action buttons');
    for (const [label, expectedText] of [
      ['Export', '.travelglobe 已下載到瀏覽器下載資料夾'],
      ['Share', '.share-safe.json 已下載到瀏覽器下載資料夾'],
      ['GPX', '.gpx 已下載到瀏覽器下載資料夾'],
      ['KML', '.kml 已下載到瀏覽器下載資料夾'],
      ['Journal', '.journal.md 已下載到瀏覽器下載資料夾']
    ]) {
      await dispatchActionButtonClick(page, label);
      await page.waitForTimeout(150);
      const status = await page.locator('.capability').innerText();
      report.actionStatuses.push({ label, status });
      assert(status.includes(expectedText), `${label} action did not update status`);
    }

    console.error('[verify-preview] mobile: FD234 step pack and panels');
    await dispatchActionButtonClick(page, 'Pack');
    await page.waitForTimeout(250);
    assert((await page.locator('.capability').innerText()).includes('Core Global Atlas'), 'Pack button did not update capability text');
    await setDetailsOpen(page, '.product-panel-shell', true);
    await page.waitForTimeout(200);
    report.cardMetrics.travelAtlas = await scrollPanelToBottom(page, '.product-panel');
    report.cardMetrics.travelAtlasGesture = await dragInsidePanelWithoutClosing(page, '.product-panel', '.product-panel-shell');
    await page.screenshot({ path: report.travelAtlasScreenshotPath, fullPage: false });
    assert(report.cardMetrics.travelAtlas.visible, `Travel Atlas panel is not visible: ${JSON.stringify(report.cardMetrics.travelAtlas)}`);
    assert(report.cardMetrics.travelAtlas.height >= 360, `Travel Atlas panel is still too small: ${JSON.stringify(report.cardMetrics.travelAtlas)}`);
    assert(report.cardMetrics.travelAtlas.bottom <= report.cardMetrics.travelAtlas.drawerBottom + 1, `Travel Atlas panel is clipped outside drawer: ${JSON.stringify(report.cardMetrics.travelAtlas)}`);
    assert(report.cardMetrics.travelAtlas.reachedBottom, `Travel Atlas panel cannot scroll to its bottom: ${JSON.stringify(report.cardMetrics.travelAtlas)}`);
    assert(report.cardMetrics.travelAtlasGesture.open, `Travel Atlas collapsed during content drag/long press: ${JSON.stringify(report.cardMetrics.travelAtlasGesture)}`);
    await dispatchTextClick(page, '標記離線');
    await page.waitForTimeout(180);
    assert((await page.locator('.capability').innerText()).includes('已標記為可離線使用'), 'Travel Atlas offline marker button did not update status');
    await setDetailsOpen(page, '.product-panel-shell', false);
    await page.waitForTimeout(150);
    await setDetailsOpen(page, '.timeline-panel', true);
    await page.waitForTimeout(200);
    report.cardMetrics.timeline = await scrollPanelToBottom(page, '.timeline-panel');
    report.cardMetrics.recordPreview = await scrollPanelToBottom(page, '.record-preview');
    report.cardMetrics.recordHistoryText = await page.locator('.record-history-section').innerText().catch(() => '');
    report.cardMetrics.timelineGesture = await dragInsidePanelWithoutClosing(page, '.timeline-panel', '.timeline-panel');
    await page.screenshot({ path: report.timelineScreenshotPath, fullPage: false });
    assert(report.cardMetrics.timeline.visible, `Travel record panel is not visible: ${JSON.stringify(report.cardMetrics.timeline)}`);
    assert(report.cardMetrics.timeline.height >= 360, `Travel record panel is still too small: ${JSON.stringify(report.cardMetrics.timeline)}`);
    assert(report.cardMetrics.recordPreview.visible, `Travel record editor preview is not visible: ${JSON.stringify(report.cardMetrics.recordPreview)}`);
    assert(report.cardMetrics.recordHistoryText.includes('本機歷史旅程'), `Travel record history controls are missing: ${JSON.stringify(report.cardMetrics.recordHistoryText)}`);
    assert(report.cardMetrics.timeline.bottom <= report.cardMetrics.timeline.drawerBottom + 1, `Travel record panel is clipped outside drawer: ${JSON.stringify(report.cardMetrics.timeline)}`);
    assert(report.cardMetrics.timeline.reachedBottom, `Travel record panel cannot scroll to its bottom: ${JSON.stringify(report.cardMetrics.timeline)}`);
    assert(report.cardMetrics.timelineGesture.open, `Travel record collapsed during content drag/long press: ${JSON.stringify(report.cardMetrics.timelineGesture)}`);
    await dispatchTextClick(page, '載入最新');
    await page.waitForTimeout(180);
    assert((await page.locator('.capability').innerText()).includes('瀏覽器模式沒有 iOS SQLite'), 'Travel record load latest button did not update status');

    await dispatchClick(page, '.system-drawer > .panel-summary');
    await page.waitForTimeout(250);
    assert((await page.locator('.system-drawer.is-open').count()) === 0, 'system drawer did not close while preload card was open');
    await dispatchClick(page, '.system-drawer > .panel-summary');
    await page.waitForTimeout(250);
    assert((await page.locator('.system-drawer.is-open').count()) === 1, 'system drawer did not reopen after preload close check');
    await setDetailsOpen(page, '.preload-panel-shell', true);
    await page.waitForTimeout(200);

    console.error('[verify-preview] mobile: FD234 step apply FD234');
    await page.locator('.preload-field:nth-child(2) input').fill('FD234');
    await page.waitForTimeout(250);
    await page.evaluate(() => {
      const submit = document.querySelector('.preload-submit');
      if (submit instanceof HTMLButtonElement) {
        submit.click();
      }
    });
    await page.waitForTimeout(1200);
    assert((await page.locator('.hud-title').innerText()).includes('FD234'), 'FD234 was not applied');
    await clickViewMode(page, 'flightPreview');
    await page.evaluate(() => {
      const scrubber = document.querySelector('.timeline-scrubber');
      if (scrubber instanceof HTMLInputElement) {
        scrubber.value = '1';
        scrubber.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await page.waitForTimeout(900);
    await page.screenshot({ path: daylightScreenshotPath, fullPage: false });
    report.takeoffFocus = await page.evaluate(() => ({
      airportFocus: Number(document.querySelector('.globe-viewport')?.dataset.airportFocus ?? '0'),
      nearGroundFocus: Number(document.querySelector('.globe-viewport')?.dataset.nearGroundFocus ?? '0'),
      airportMarkerScale: Number(document.querySelector('.globe-viewport')?.dataset.airportMarkerScale ?? '1'),
      airportMarkerPlacement: document.querySelector('.globe-viewport')?.dataset.airportMarkerPlacement ?? '',
      cityLightPlacement: document.querySelector('.globe-viewport')?.dataset.cityLightPlacement ?? '',
      hudStats: document.querySelector('.hud-stats')?.textContent ?? '',
      labels: [...document.querySelectorAll('.globe-place-label:not(.is-hidden)')].map((label) => label.textContent?.trim() ?? '')
    }));
    assert(report.takeoffFocus.airportFocus >= 0.82, `FD234 takeoff did not focus the airport: ${JSON.stringify(report.takeoffFocus)}`);
    assert(report.takeoffFocus.nearGroundFocus >= 0.8, `FD234 takeoff did not use near-ground zoom: ${JSON.stringify(report.takeoffFocus)}`);
    assert(report.takeoffFocus.airportMarkerScale <= 0.42, `FD234 takeoff airport marker remains too large: ${JSON.stringify(report.takeoffFocus)}`);
    assert(report.takeoffFocus.airportMarkerPlacement === 'surface-plane', `FD234 takeoff airport marker is not surface-locked: ${JSON.stringify(report.takeoffFocus)}`);
    assert(report.takeoffFocus.cityLightPlacement === 'surface-plane', `FD234 takeoff city lights are not surface-locked: ${JSON.stringify(report.takeoffFocus)}`);
    assert(report.takeoffFocus.labels.some((label) => label.includes('KHH') || label.includes('Kaohsiung')), `FD234 takeoff airport label is not visible: ${JSON.stringify(report.takeoffFocus)}`);

    const daylightViewportSize = page.viewportSize() ?? { width: 390, height: 844 };
    report.daylightBrightness = readPngBrightness(daylightScreenshotPath, {
      x: 0,
      y: 250,
      width: daylightViewportSize.width,
      height: Math.min(360, daylightViewportSize.height - 470)
    });
    assert(report.daylightBrightness.average >= 110, `FD234 daytime takeoff scene still too dark: ${JSON.stringify(report.daylightBrightness)}`);
    assert(report.daylightBrightness.bright >= 120000, `FD234 daytime takeoff scene lacks visible daylight pixels: ${JSON.stringify(report.daylightBrightness)}`);

    console.error('[verify-preview] mobile: FD234 step approach');
    await clickViewMode(page, 'overhead');
    console.error('[verify-preview] mobile: FD234 step night regression');
    await page.evaluate(() => {
      const scrubber = document.querySelector('.timeline-scrubber');
      if (scrubber instanceof HTMLInputElement) {
        scrubber.value = '996';
        scrubber.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await page.waitForTimeout(900);
    await page.screenshot({ path: report.approachScreenshotPath, fullPage: false });
    report.approachFocus = await page.evaluate(() => ({
      airportFocus: Number(document.querySelector('.globe-viewport')?.dataset.airportFocus ?? '0'),
      nearGroundFocus: Number(document.querySelector('.globe-viewport')?.dataset.nearGroundFocus ?? '0'),
      airportMarkerScale: Number(document.querySelector('.globe-viewport')?.dataset.airportMarkerScale ?? '1'),
      airportMarkerPlacement: document.querySelector('.globe-viewport')?.dataset.airportMarkerPlacement ?? '',
      cityLightPlacement: document.querySelector('.globe-viewport')?.dataset.cityLightPlacement ?? '',
      hudStats: document.querySelector('.hud-stats')?.textContent ?? '',
      labels: [...document.querySelectorAll('.globe-place-label:not(.is-hidden)')].map((label) => label.textContent?.trim() ?? '')
    }));
    assert(report.approachFocus.airportFocus >= 0.82, `FD234 approach did not focus the airport: ${JSON.stringify(report.approachFocus)}`);
    assert(report.approachFocus.nearGroundFocus >= 0.8, `FD234 low approach did not enter near-ground zoom: ${JSON.stringify(report.approachFocus)}`);
    assert(report.approachFocus.airportMarkerScale <= 0.42, `FD234 airport marker remains too large on approach: ${JSON.stringify(report.approachFocus)}`);
    assert(report.approachFocus.airportMarkerPlacement === 'surface-plane', `FD234 approach airport marker is not surface-locked: ${JSON.stringify(report.approachFocus)}`);
    assert(report.approachFocus.cityLightPlacement === 'surface-plane', `FD234 approach city lights are not surface-locked: ${JSON.stringify(report.approachFocus)}`);
    assert(report.approachFocus.labels.some((label) => label.includes('NRT') || label.includes('Narita')), `FD234 approach airport label is not visible: ${JSON.stringify(report.approachFocus)}`);

    await page.evaluate(() => {
      const scrubber = document.querySelector('.timeline-scrubber');
      if (scrubber instanceof HTMLInputElement) {
        scrubber.value = '1000';
        scrubber.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await page.waitForTimeout(900);
    await page.screenshot({ path: report.arrivalScreenshotPath, fullPage: false });
    report.arrivalFocus = await page.evaluate(() => ({
      airportFocus: Number(document.querySelector('.globe-viewport')?.dataset.airportFocus ?? '0'),
      dayFactor: Number(document.querySelector('.globe-viewport')?.dataset.dayFactor ?? '0'),
      hudPoint: document.querySelector('.hud-point')?.textContent ?? '',
      hudStats: document.querySelector('.hud-stats')?.textContent ?? '',
      activeMode: document.querySelector('.view-mode-button.is-active') instanceof HTMLButtonElement
        ? document.querySelector('.view-mode-button.is-active')?.getAttribute('data-mode') ?? ''
        : '',
      labels: [...document.querySelectorAll('.globe-place-label:not(.is-hidden)')].map((label) => label.textContent?.trim() ?? '')
    }));
    assert(report.arrivalFocus.activeMode === 'overhead', `FD234 arrival check did not stay overhead: ${JSON.stringify(report.arrivalFocus)}`);
    assert(report.arrivalFocus.airportFocus >= 0.82, `FD234 arrival did not zoom/focus the airport: ${JSON.stringify(report.arrivalFocus)}`);
    assert(report.arrivalFocus.hudStats.includes('0 km'), `FD234 arrival did not reach airport endpoint: ${JSON.stringify(report.arrivalFocus)}`);
    assert(report.arrivalFocus.labels.some((label) => label.includes('NRT') || label.includes('Narita')), `FD234 arrival airport label is not visible: ${JSON.stringify(report.arrivalFocus)}`);

    await page.evaluate(() => {
      const timeInput = document.querySelector('.preload-field:nth-child(6) input');
      if (timeInput instanceof HTMLInputElement) {
        timeInput.value = '22:15';
        timeInput.dispatchEvent(new Event('input', { bubbles: true }));
        timeInput.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
    await page.evaluate(() => {
      const submit = document.querySelector('.preload-submit');
      if (submit instanceof HTMLButtonElement) {
        submit.click();
      }
    });
    await page.waitForTimeout(1200);
    await clickViewMode(page, 'overhead');
    await page.evaluate(() => {
      const scrubber = document.querySelector('.timeline-scrubber');
      if (scrubber instanceof HTMLInputElement) {
        scrubber.value = '760';
        scrubber.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await page.waitForTimeout(900);
    await page.screenshot({ path: report.nightScreenshotPath, fullPage: false });
    const nightViewportSize = page.viewportSize() ?? { width: 390, height: 844 };
    report.nightRegression = {
      ...readPngBrightness(report.nightScreenshotPath, {
        x: 0,
        y: 220,
        width: nightViewportSize.width,
        height: Math.min(440, nightViewportSize.height - 430)
      }),
      ...readPngColorStats(report.nightScreenshotPath, {
        x: 0,
        y: 220,
        width: nightViewportSize.width,
        height: Math.min(440, nightViewportSize.height - 430)
      }),
      dayFactor: await page.evaluate(() => Number(document.querySelector('.globe-viewport')?.dataset.dayFactor ?? '1')),
      localSolarHour: await page.evaluate(() => Number(document.querySelector('.globe-viewport')?.dataset.localSolarHour ?? '0'))
    };
    assert(report.nightRegression.dayFactor <= 0.35, `FD234 night scene is still using daylight: ${JSON.stringify(report.nightRegression)}`);
    assert(report.nightRegression.average <= 105, `FD234 night scene is too bright: ${JSON.stringify(report.nightRegression)}`);
    assert(report.nightRegression.orangePixels >= 55, `FD234 night city lights are not orange enough: ${JSON.stringify(report.nightRegression)}`);

    await page.evaluate(() => {
      const timeInput = document.querySelector('.preload-field:nth-child(6) input');
      if (timeInput instanceof HTMLInputElement) {
        timeInput.value = '09:30';
        timeInput.dispatchEvent(new Event('input', { bubbles: true }));
        timeInput.dispatchEvent(new Event('change', { bubbles: true }));
      }
      const submit = document.querySelector('.preload-submit');
      if (submit instanceof HTMLButtonElement) {
        submit.click();
      }
    });
    await page.waitForTimeout(1200);

    console.error('[verify-preview] mobile: FD234 step tower brightness');
    await clickViewMode(page, 'commandCenter');
    await page.evaluate(() => {
      const scrubber = document.querySelector('.timeline-scrubber');
      if (scrubber instanceof HTMLInputElement) {
        scrubber.value = '400';
        scrubber.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await page.waitForTimeout(900);
    await page.screenshot({ path: screenshotPath, fullPage: false });

    const viewportSize = page.viewportSize() ?? { width: 390, height: 844 };
    report.brightness = readPngBrightness(screenshotPath, {
      x: 0,
      y: 120,
      width: viewportSize.width,
      height: Math.min(520, viewportSize.height - 260)
    });
    assert(report.brightness.average >= 110, `FD234 tower scene still too dark: ${JSON.stringify(report.brightness)}`);
    assert(report.brightness.bright >= 180000, `FD234 tower scene lacks visible bright pixels: ${JSON.stringify(report.brightness)}`);

    if ((await page.locator('.system-drawer.is-open').count()) > 0) {
      await dispatchClick(page, '.system-drawer > .panel-summary');
      await page.waitForTimeout(250);
      assert((await page.locator('.system-drawer.is-open').count()) === 0, 'system drawer did not close after FD234/preload state');
    }
    report.ok = true;
  } catch (error) {
    report.failure = error instanceof Error ? error.message : String(error);
  }

  return report;
}

async function withTimeout(promise, timeoutMs, failure) {
  let timer;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve({ ok: false, failure }), timeoutMs);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function actionButton(page, label) {
  return page.locator('.action-grid button, .action-grid a').filter({ hasText: label }).first();
}

async function dispatchClick(page, selector) {
  const clicked = await page.evaluate((targetSelector) => {
    const target = document.querySelector(targetSelector);
    if (!(target instanceof HTMLElement)) {
      return false;
    }
    target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    return true;
  }, selector);
  assert(clicked, `click target missing: ${selector}`);
}

async function dispatchTextClick(page, text) {
  const clicked = await page.evaluate((targetText) => {
    const candidates = [...document.querySelectorAll('button, summary, a, [role="button"]')];
    const target = candidates.find((candidate) => candidate.textContent?.trim() === targetText);
    if (!(target instanceof HTMLElement)) {
      return false;
    }
    target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    return true;
  }, text);
  assert(clicked, `text click target missing: ${text}`);
}

async function setDetailsOpen(page, selector, open) {
  const updated = await page.evaluate(({ targetSelector, nextOpen }) => {
    const target = document.querySelector(targetSelector);
    if (!(target instanceof HTMLDetailsElement)) {
      return false;
    }
    target.open = nextOpen;
    target.dispatchEvent(new Event('toggle', { bubbles: true }));
    return true;
  }, { targetSelector: selector, nextOpen: open });
  assert(updated, `details target missing: ${selector}`);
}

async function dispatchActionButtonClick(page, label) {
  const clicked = await page.evaluate((targetLabel) => {
    const nodes = [...document.querySelectorAll('.action-grid button, .action-grid a')];
    const target = nodes.find((candidate) => candidate.textContent?.trim() === targetLabel);
    if (!(target instanceof HTMLElement)) {
      return false;
    }
    target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    return true;
  }, label);
  assert(clicked, `action button missing: ${label}`);
}

async function scrollPanelToBottom(page, selector) {
  return page.evaluate((panelSelector) => {
    const panel = document.querySelector(panelSelector);
    const drawer = document.querySelector('.system-drawer')?.getBoundingClientRect();
    const controls = document.querySelector('.controls')?.getBoundingClientRect();
    if (!(panel instanceof HTMLElement) || !drawer || !controls) {
      return { visible: false, reachedBottom: false };
    }
    panel.scrollTop = panel.scrollHeight;
    const rect = panel.getBoundingClientRect();
    const reachedBottom = Math.ceil(panel.scrollTop + panel.clientHeight) >= panel.scrollHeight;
    return {
      visible: rect.width > 0 && rect.height > 0,
      top: Math.round(rect.top),
      bottom: Math.round(rect.bottom),
      height: Math.round(rect.height),
      scrollHeight: panel.scrollHeight,
      clientHeight: panel.clientHeight,
      scrollTop: panel.scrollTop,
      reachedBottom,
      drawerBottom: Math.round(drawer.bottom),
      controlsTop: Math.round(controls.top)
    };
  }, selector);
}

async function dragInsidePanelWithoutClosing(page, panelSelector, shellSelector) {
  const panel = page.locator(panelSelector).first();
  const box = await panel.boundingBox();
  assert(box, `panel box missing for ${panelSelector}`);
  const startX = box.x + box.width / 2;
  const startY = box.y + Math.min(box.height - 8, Math.max(18, box.height * 0.68));
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.waitForTimeout(820);
  await page.mouse.move(startX, Math.max(box.y + 12, startY - 58), { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(180);
  return {
    open: (await page.locator(`${shellSelector}[open]`).count()) === 1,
    panelSelector,
    shellSelector
  };
}

function decodePng(filePath) {
  const bytes = fs.readFileSync(filePath);
  assert(bytes.subarray(0, 8).toString('hex') === '89504e470d0a1a0a', 'screenshot is not a PNG');
  let offset = 8;
  let width = 0;
  let height = 0;
  let colorType = 0;
  const idat = [];

  while (offset < bytes.length) {
    const length = bytes.readUInt32BE(offset);
    const type = bytes.subarray(offset + 4, offset + 8).toString('ascii');
    const data = bytes.subarray(offset + 8, offset + 8 + length);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      const bitDepth = data.readUInt8(8);
      colorType = data.readUInt8(9);
      assert(bitDepth === 8, `unsupported PNG bit depth ${bitDepth}`);
      assert(colorType === 2 || colorType === 6, `unsupported PNG color type ${colorType}`);
    } else if (type === 'IDAT') {
      idat.push(data);
    } else if (type === 'IEND') {
      break;
    }
    offset += 12 + length;
  }

  const channels = colorType === 6 ? 4 : 3;
  const rowBytes = width * channels;
  const inflated = zlib.inflateSync(Buffer.concat(idat));
  const pixels = Buffer.alloc(width * height * channels);
  let inputOffset = 0;
  let outputOffset = 0;
  let previousRow = Buffer.alloc(rowBytes);

  for (let row = 0; row < height; row += 1) {
    const filter = inflated[inputOffset];
    inputOffset += 1;
    const raw = inflated.subarray(inputOffset, inputOffset + rowBytes);
    inputOffset += rowBytes;
    const recon = Buffer.alloc(rowBytes);
    for (let index = 0; index < rowBytes; index += 1) {
      const left = index >= channels ? recon[index - channels] : 0;
      const up = previousRow[index] ?? 0;
      const upLeft = index >= channels ? previousRow[index - channels] ?? 0 : 0;
      recon[index] = (raw[index] + pngFilterValue(filter, left, up, upLeft)) & 255;
    }
    recon.copy(pixels, outputOffset);
    outputOffset += rowBytes;
    previousRow = recon;
  }

  return { width, height, channels, pixels };
}

function readPngBrightness(filePath, crop) {
  const { width, height, channels, pixels } = decodePng(filePath);
  const xStart = Math.max(0, Math.floor(crop.x));
  const yStart = Math.max(0, Math.floor(crop.y));
  const xEnd = Math.min(width, xStart + Math.floor(crop.width));
  const yEnd = Math.min(height, yStart + Math.floor(crop.height));
  let sum = 0;
  let bright = 0;
  let count = 0;

  for (let y = yStart; y < yEnd; y += 1) {
    for (let x = xStart; x < xEnd; x += 1) {
      const index = (y * width + x) * channels;
      const value = (pixels[index] + pixels[index + 1] + pixels[index + 2]) / 3;
      sum += value;
      if (value > 18) {
        bright += 1;
      }
      count += 1;
    }
  }

  return {
    average: Math.round(sum / Math.max(1, count)),
    bright,
    samplePixels: count
  };
}

function readPngColorStats(filePath, crop) {
  const { width, height, channels, pixels } = decodePng(filePath);
  const xStart = Math.max(0, Math.floor(crop.x));
  const yStart = Math.max(0, Math.floor(crop.y));
  const xEnd = Math.min(width, xStart + Math.floor(crop.width));
  const yEnd = Math.min(height, yStart + Math.floor(crop.height));
  let orangePixels = 0;
  let coolWhitePixels = 0;

  for (let y = yStart; y < yEnd; y += 1) {
    for (let x = xStart; x < xEnd; x += 1) {
      const index = (y * width + x) * channels;
      const red = pixels[index];
      const green = pixels[index + 1];
      const blue = pixels[index + 2];
      if (red >= 78 && green >= 38 && blue <= 72 && red > green * 1.12 && green > blue * 1.18) {
        orangePixels += 1;
      }
      if (red >= 150 && green >= 150 && blue >= 145 && Math.abs(red - green) < 34 && Math.abs(green - blue) < 44) {
        coolWhitePixels += 1;
      }
    }
  }

  return { orangePixels, coolWhitePixels };
}

function pngFilterValue(filter, left, up, upLeft) {
  if (filter === 0) {
    return 0;
  }
  if (filter === 1) {
    return left;
  }
  if (filter === 2) {
    return up;
  }
  if (filter === 3) {
    return Math.floor((left + up) / 2);
  }
  if (filter === 4) {
    return paethPredictor(left, up, upLeft);
  }
  throw new Error(`unsupported PNG filter ${filter}`);
}

function paethPredictor(left, up, upLeft) {
  const estimate = left + up - upLeft;
  const leftDistance = Math.abs(estimate - left);
  const upDistance = Math.abs(estimate - up);
  const upLeftDistance = Math.abs(estimate - upLeft);
  if (leftDistance <= upDistance && leftDistance <= upLeftDistance) {
    return left;
  }
  if (upDistance <= upLeftDistance) {
    return up;
  }
  return upLeft;
}
