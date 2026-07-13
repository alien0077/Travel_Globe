declare global {
  interface Window {
    __TRAVEL_GLOBE_ASSET_BASE__?: string;
  }
}

export function resolveBundledAsset(filename: string): string {
  const normalized = filename.replace(/^\.?\//, '');
  const explicitBase = window.__TRAVEL_GLOBE_ASSET_BASE__;
  if (explicitBase) {
    return new URL(normalized, ensureDirectoryUrl(explicitBase)).href;
  }

  const currentScript = document.currentScript as HTMLScriptElement | null;
  const scriptUrl =
    currentScript?.src ||
    [...document.scripts].find((script) => /(?:^|\/)index\.js(?:$|\?)/.test(script.src))?.src;

  const baseUrl = scriptUrl ? new URL('.', scriptUrl).href : new URL('.', document.baseURI || window.location.href).href;
  return new URL(normalized, baseUrl).href;
}

function ensureDirectoryUrl(value: string): string {
  return value.endsWith('/') ? value : `${value}/`;
}
