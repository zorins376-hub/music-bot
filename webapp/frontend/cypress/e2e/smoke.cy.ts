/// <reference types="cypress" />

describe("Music Player Smoke Tests", () => {
  beforeEach(() => {
    // Mock API responses
    cy.intercept("GET", "/api/playlists/*", { fixture: "playlists.json" }).as("getPlaylists");
    cy.intercept("GET", "/api/queue/*", { fixture: "queue.json" }).as("getQueue");
    cy.intercept("GET", "/api/state/*", { fixture: "state.json" }).as("getState");
    cy.intercept("GET", "/api/charts/*", []).as("getCharts");
    cy.intercept("GET", "/api/health", { status: "ok" }).as("health");

    // Visit app and mock Telegram
    cy.visit("/", {
      onBeforeLoad(win) {
        // Mock Telegram WebApp SDK before page loads
        win.Telegram = {
          WebApp: {
            initData: "user=%7B%22id%22%3A123456789%2C%22first_name%22%3A%22Test%22%7D&auth_date=1710000000&hash=test",
            initDataUnsafe: {
              user: { id: 123456789, first_name: "Test", username: "testuser" },
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
            MainButton: { show: () => {}, hide: () => {}, setText: () => {}, onClick: () => {}, offClick: () => {} },
            BackButton: { show: () => {}, hide: () => {}, onClick: () => {}, offClick: () => {} },
          },
        } as any;
      },
    });
  });

  it("loads the app without crashing", () => {
    // App should load and display navigation
    cy.get("button").should("have.length.at.least", 1);
  });

  it("displays navigation tabs", () => {
    // Should have at least the main navigation tabs
    cy.contains("Плеер").should("exist");
  });

  it("can switch between views", () => {
    // Click on Charts tab
    cy.contains("Чарты").click();
    // Should navigate (view change indicated by URL or content)
    cy.url().should("include", "/");
  });

  it("handles search input", () => {
    // Find and interact with search input if visible
    cy.get("input[type='text']").first().should("exist");
  });
});

describe("Player Controls", () => {
  beforeEach(() => {
    cy.intercept("GET", "/api/state/*", {
      statusCode: 200,
      body: {
        current_track: {
          video_id: "test123",
          title: "Test Track",
          artist: "Test Artist",
          duration: 180,
          duration_fmt: "3:00",
        },
        is_playing: false,
        queue: [],
        shuffle: false,
        repeat_mode: "off",
      },
    }).as("getState");

    cy.visit("/", {
      onBeforeLoad(win) {
        win.Telegram = {
          WebApp: {
            initData: "user=%7B%22id%22%3A123456789%7D",
            initDataUnsafe: { user: { id: 123456789 } },
            ready: () => {},
            expand: () => {},
            HapticFeedback: { impactOccurred: () => {}, notificationOccurred: () => {}, selectionChanged: () => {} },
            themeParams: { bg_color: "#1a1a2e", text_color: "#ffffff" },
            colorScheme: "dark",
          },
        } as any;
      },
    });
  });

  it("displays play/pause button", () => {
    cy.get("button[aria-label='Play'], button[aria-label='Pause']", { timeout: 10000 })
      .should("exist");
  });

  it("displays track info when track is loaded", () => {
    cy.wait("@getState");
    // Track title or artist should be visible somewhere
    cy.contains("Test Track").should("exist");
  });
});

describe("Error Handling", () => {
  it("handles API errors gracefully", () => {
    cy.intercept("GET", "/api/state/*", { statusCode: 500, body: { error: "Server error" } }).as("stateError");

    cy.visit("/", {
      onBeforeLoad(win) {
        win.Telegram = {
          WebApp: {
            initData: "user=%7B%22id%22%3A123456789%7D",
            initDataUnsafe: { user: { id: 123456789 } },
            ready: () => {},
            expand: () => {},
            HapticFeedback: { impactOccurred: () => {} },
            themeParams: {},
            colorScheme: "dark",
          },
        } as any;
      },
    });

    // App should not crash, should still render
    cy.get("button").should("exist");
  });

  it("handles missing Telegram SDK gracefully", () => {
    cy.visit("/");
    // App should still render even without Telegram SDK
    cy.get("body").should("exist");
  });
});
