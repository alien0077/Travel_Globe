import { chromium } from 'playwright';

const url = process.env.TRAVEL_GLOBE_PREVIEW_URL ?? 'http://127.0.0.1:4173/';

const browser = await chromium.launch({ headless: true });
const results = [];

for (const viewport of [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 }
]) {
  const page = await browser.newPage({ viewport });
  const errors = [];

  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') {
      errors.push(message.text());
    }
  });

  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForSelector('canvas');
  await page.waitForTimeout(700);

  const check = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    const hud = document.querySelector('.hud-stats')?.textContent ?? '';
    const title = document.querySelector('.hud-title')?.textContent ?? '';
    const scrubber = document.querySelector('.timeline-scrubber');
    const controls = [...document.querySelectorAll('.control-button')].map((button) => button.textContent);
    const timelineItems = document.querySelectorAll('.timeline-item').length;

    if (!(canvas instanceof HTMLCanvasElement) || !(scrubber instanceof HTMLInputElement)) {
      return {
        ok: false,
        reason: 'missing canvas or scrubber',
        hud,
        title,
        coloredPixels: 0,
        scrubberValue: '',
        controls,
        timelineItems
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
        hud.includes('ALT') &&
        title.includes('Taipei') &&
        controls.includes('Import') &&
        controls.includes('Export') &&
        controls.includes('Share JSON') &&
        timelineItems >= 4,
      reason: '',
      hud,
      title,
      coloredPixels,
      scrubberValue: scrubber.value,
      controls,
      timelineItems
    };
  });

  await page.click('.control-button');
  const paused = await page.textContent('.control-button');
  await page.fill('.timeline-scrubber', '700');
  await page.dispatchEvent('.timeline-scrubber', 'input');
  await page.waitForTimeout(150);

  const afterScrub = await page.evaluate(() => ({
    scrubber: document.querySelector('.timeline-scrubber')?.value,
    point: document.querySelector('.hud-point')?.textContent,
    stats: document.querySelector('.hud-stats')?.textContent
  }));

  results.push({ viewport: viewport.name, errors, check, paused, afterScrub });
  await page.close();
}

await browser.close();

const failed = results.filter((result) => !result.check.ok || result.errors.length > 0);
console.log(JSON.stringify(results, null, 2));

if (failed.length > 0) {
  process.exitCode = 1;
}
