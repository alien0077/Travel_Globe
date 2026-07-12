import './styles.css';
import { sampleJourney } from './data/sampleJourney';
import { TravelGlobeApp } from './ui/TravelGlobeApp';

function reportReplayStatus(message: string): void {
  const bridge = (
    window as typeof window & {
      webkit?: {
        messageHandlers?: {
          replayDiagnostics?: {
            postMessage: (message: string) => void;
          };
        };
      };
    }
  ).webkit?.messageHandlers?.replayDiagnostics;
  bridge?.postMessage(message);
}

function reportRenderSnapshot(root: HTMLElement): void {
  requestAnimationFrame(() => {
    const canvas = document.querySelector<HTMLCanvasElement>('canvas');
    const shell = document.querySelector<HTMLElement>('.app-shell');
    const viewport = document.querySelector<HTMLElement>('.globe-viewport');
    const overlay = document.querySelector<HTMLElement>('.overlay');
    const shellRect = shell?.getBoundingClientRect();
    const viewportRect = viewport?.getBoundingClientRect();
    const overlayRect = overlay?.getBoundingClientRect();
    const canvasRect = canvas?.getBoundingClientRect();
    const rootStyle = window.getComputedStyle(root);
    const viewportStyle = viewport ? window.getComputedStyle(viewport) : undefined;

    reportReplayStatus(
      [
        'ready',
        `dom=${root.children.length}`,
        `txt=${root.innerText.trim().length}`,
        `root=${Math.round(root.clientWidth)}x${Math.round(root.clientHeight)}`,
        `shell=${Math.round(shellRect?.width ?? 0)}x${Math.round(shellRect?.height ?? 0)}`,
        `view=${Math.round(viewportRect?.width ?? 0)}x${Math.round(viewportRect?.height ?? 0)}`,
        `canvas=${Math.round(canvasRect?.width ?? 0)}x${Math.round(canvasRect?.height ?? 0)}/${canvas?.width ?? 0}x${canvas?.height ?? 0}`,
        `overlay=${Math.round(overlayRect?.width ?? 0)}x${Math.round(overlayRect?.height ?? 0)}`,
        `display=${rootStyle.display}/${viewportStyle?.display ?? 'none'}`,
      ].join(' ')
    );
  });
}

const root = document.querySelector<HTMLElement>('#app');

if (!root) {
  reportReplayStatus('JS error: Missing #app root element');
  throw new Error('Missing #app root element');
}

const app = new TravelGlobeApp(root, sampleJourney);
reportReplayStatus('booting');
void app
  .start()
  .then(() => reportRenderSnapshot(root))
  .catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    reportReplayStatus(`Promise rejection: ${message}`);
    throw error;
  });
