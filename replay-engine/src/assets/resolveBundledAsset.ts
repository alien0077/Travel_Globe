declare global {
  interface Window {
    __TRAVEL_GLOBE_ASSET_BASE__?: string;
  }
}

// WKWebView 可能保留舊版圖片的解碼／URL cache；材質版本變更時用新的
// query key，避免安裝更新後仍顯示上一版的低解析或 fallback 圖片。
const IMAGE_ASSET_CACHE_VERSION = 'cabin-camera-ground-follow-v2';

export function resolveBundledAsset(filename: string): string {
  const normalized = filename.replace(/^\.?\//, '');
  const explicitBase = window.__TRAVEL_GLOBE_ASSET_BASE__;
  if (explicitBase) {
    return withImageCacheVersion(new URL(normalized, ensureDirectoryUrl(explicitBase)));
  }

  const currentScript = document.currentScript as HTMLScriptElement | null;
  const scriptUrl =
    currentScript?.src ||
    [...document.scripts].find((script) => /(?:^|\/)index\.js(?:$|\?)/.test(script.src))?.src;

  const baseUrl = scriptUrl ? new URL('.', scriptUrl).href : new URL('.', document.baseURI || window.location.href).href;
  return withImageCacheVersion(new URL(normalized, baseUrl));
}

function withImageCacheVersion(url: URL): string {
  if (/\.(?:jpe?g|png)$/i.test(url.pathname)) {
    url.searchParams.set('v', IMAGE_ASSET_CACHE_VERSION);
  }
  return url.href;
}

function ensureDirectoryUrl(value: string): string {
  return value.endsWith('/') ? value : `${value}/`;
}
