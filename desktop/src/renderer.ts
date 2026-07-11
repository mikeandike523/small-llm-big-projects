import './index.css';
import type { TabsUpdatePayload } from './preload';

declare global {
  interface Window {
    tabsAPI: {
      onUpdate: (callback: (payload: TabsUpdatePayload) => void) => void;
      switchTab: (id: string) => Promise<void>;
      closeTab: (id: string) => Promise<void>;
    };
    windowAPI: {
      minimize: () => Promise<void>;
      toggleMaximize: () => Promise<void>;
      close: () => Promise<void>;
    };
  }
}

document.getElementById('win-minimize')!.addEventListener('click', () => window.windowAPI.minimize());
document.getElementById('win-maximize')!.addEventListener('click', () => window.windowAPI.toggleMaximize());
document.getElementById('win-close')!.addEventListener('click', () => window.windowAPI.close());

const stripEl = document.getElementById('tab-strip')!;

function render(payload: TabsUpdatePayload) {
  stripEl.innerHTML = '';
  for (const tab of payload.tabs) {
    const tabEl = document.createElement('div');
    tabEl.className = 'tab' + (tab.id === payload.activeId ? ' tab-active' : '');

    const labelEl = document.createElement('span');
    labelEl.className = 'tab-label';
    labelEl.textContent = tab.label;
    labelEl.addEventListener('click', () => window.tabsAPI.switchTab(tab.id));

    const closeEl = document.createElement('span');
    closeEl.className = 'tab-close';
    closeEl.textContent = '×';
    closeEl.addEventListener('click', (event) => {
      event.stopPropagation();
      window.tabsAPI.closeTab(tab.id);
    });

    tabEl.appendChild(labelEl);
    tabEl.appendChild(closeEl);
    stripEl.appendChild(tabEl);
  }
}

window.tabsAPI.onUpdate(render);
