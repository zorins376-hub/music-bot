import { render } from "preact";
import { App } from "./App";

// Telegram WebApp SDK
declare global {
  interface Window {
    Telegram: {
      WebApp: {
        initData: string;
        initDataUnsafe: { user?: { id: number; first_name: string } };
        ready: () => void;
        expand: () => void;
        close: () => void;
        MainButton: {
          text: string;
          show: () => void;
          hide: () => void;
          onClick: (cb: () => void) => void;
        };
        themeParams: Record<string, string>;
      };
    };
  }
}

window.Telegram.WebApp.ready();
window.Telegram.WebApp.expand();

render(<App />, document.getElementById("app")!);
