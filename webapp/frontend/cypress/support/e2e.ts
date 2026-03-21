/// <reference types="cypress" />

// Custom commands for Telegram Mini App testing
declare global {
  namespace Cypress {
    interface Chainable {
      /**
       * Mock Telegram WebApp SDK
       */
      mockTelegramWebApp(userId?: number): Chainable<void>;
      
      /**
       * Wait for app to load
       */
      waitForAppLoad(): Chainable<void>;
    }
  }
}

// Mock Telegram WebApp SDK
Cypress.Commands.add("mockTelegramWebApp", (userId = 123456789) => {
  cy.window().then((win) => {
    win.Telegram = {
      WebApp: {
        initData: `user=${encodeURIComponent(JSON.stringify({ id: userId, first_name: "Test", username: "testuser" }))}&auth_date=1710000000&hash=test`,
        initDataUnsafe: {
          user: { id: userId, first_name: "Test", username: "testuser" },
        },
        ready: () => {},
        expand: () => {},
        close: () => {},
        HapticFeedback: {
          impactOccurred: () => {},
          notificationOccurred: () => {},
          selectionChanged: () => {},
        },
        themeParams: {
          bg_color: "#1a1a2e",
          text_color: "#ffffff",
          hint_color: "#aaaaaa",
          button_color: "#7c4dff",
          button_text_color: "#ffffff",
        },
        colorScheme: "dark",
        MainButton: {
          show: () => {},
          hide: () => {},
          setText: () => {},
          onClick: () => {},
          offClick: () => {},
        },
        BackButton: {
          show: () => {},
          hide: () => {},
          onClick: () => {},
          offClick: () => {},
        },
      },
    } as any;
  });
});

// Wait for app to load
Cypress.Commands.add("waitForAppLoad", () => {
  cy.get("[data-testid='app-container'], .luxury-tab", { timeout: 15000 }).should("exist");
});

export {};
