import './styles.css';
import { sampleJourney } from './data/sampleJourney';
import { TravelGlobeApp } from './ui/TravelGlobeApp';

const root = document.querySelector<HTMLElement>('#app');

if (!root) {
  throw new Error('Missing #app root element');
}

const app = new TravelGlobeApp(root, sampleJourney);
void app.start();
