// src/main.ts — Claude Master Studio Application Entrypoint

import "./styles.css";
import { store } from "./state/store.js";
import { Topbar } from "./components/Topbar.js";
import { OfflineBanner } from "./components/OfflineBanner.js";
import { Navigation } from "./components/Navigation.js";
import { CommandPalette } from "./components/CommandPalette.js";
import { ToastManager } from "./components/ToastManager.js";
import { BrainWebSocket } from "./graph/index.js";
import type { BrainEvent } from "./types/events.js";

// Screens
import { SetupWizardScreen } from "./screens/SetupWizardScreen.js";
import { HomeScreen } from "./screens/HomeScreen.js";
import { ProvidersScreen } from "./screens/ProvidersScreen.js";
import { ModelsScreen } from "./screens/ModelsScreen.js";
import { RoutingScreen } from "./screens/RoutingScreen.js";
import { DrexScreen } from "./screens/DrexScreen.js";
import { PrivacyScreen } from "./screens/PrivacyScreen.js";
import { BudgetsScreen } from "./screens/BudgetsScreen.js";
import { BrainScreen } from "./screens/BrainScreen.js";
import { ClaudeCodeScreen } from "./screens/ClaudeCodeScreen.js";
import { SettingsScreen } from "./screens/SettingsScreen.js";
import { LiveRequestsScreen } from "./screens/LiveRequestsScreen.js";
import { SessionsScreen } from "./screens/SessionsScreen.js";
import { AlertsScreen } from "./screens/AlertsScreen.js";
import { DoctorScreen } from "./screens/DoctorScreen.js";
import { LogsScreen } from "./screens/LogsScreen.js";
import { DetectionScreen } from "./screens/DetectionScreen.js";
import { ReportsScreen } from "./screens/ReportsScreen.js";
import { TestCenterScreen } from "./screens/TestCenterScreen.js";
import { VersionUpdateScreen } from "./screens/VersionUpdateScreen.js";

function mount(): void {
  const app = document.getElementById("app");
  if (!app) throw new Error("#app missing");

  // Initialize store and fetch dynamic schemas
  store.initData();
  (window as any).__STORE__ = store;

  // Initialize global overlays
  new CommandPalette();
  new ToastManager();

  app.innerHTML = `
    <div class="app-layout">
      <div id="topbar-container"></div>
      <div id="offline-banner-container"></div>
      <div class="app-body">
        <aside id="nav-container"></aside>
        <main class="main-content" id="screen-container" role="main"></main>
      </div>
    </div>
  `;

  const topbar = new Topbar();
  document.getElementById("topbar-container")!.appendChild(topbar.getElement());

  const offlineBanner = new OfflineBanner();
  document.getElementById("offline-banner-container")!.appendChild(offlineBanner.getElement());

  const navigation = new Navigation();
  document.getElementById("nav-container")!.appendChild(navigation.getElement());

  const screenContainer = document.getElementById("screen-container")!;

  let currentScreenInstance: any = null;
  let activeScreenId = "";

  const renderActiveScreen = () => {
    const screenId = store.getState().currentScreen;
    if (screenId === activeScreenId && currentScreenInstance) {
      currentScreenInstance.render();
      return;
    }

    activeScreenId = screenId;
    screenContainer.innerHTML = "";

    switch (screenId) {
      case "setup":
        currentScreenInstance = new SetupWizardScreen(screenContainer);
        break;
      case "home":
        currentScreenInstance = new HomeScreen(screenContainer);
        break;
      case "providers":
        currentScreenInstance = new ProvidersScreen(screenContainer);
        break;
      case "models":
        currentScreenInstance = new ModelsScreen(screenContainer);
        break;
      case "routing":
        currentScreenInstance = new RoutingScreen(screenContainer);
        break;
      case "drex":
        currentScreenInstance = new DrexScreen(screenContainer);
        break;
      case "privacy":
        currentScreenInstance = new PrivacyScreen(screenContainer);
        break;
      case "budgets":
        currentScreenInstance = new BudgetsScreen(screenContainer);
        break;
      case "brain":
        currentScreenInstance = new BrainScreen(screenContainer);
        break;
      case "claude_code":
        currentScreenInstance = new ClaudeCodeScreen(screenContainer);
        break;
      case "settings":
        currentScreenInstance = new SettingsScreen(screenContainer);
        break;
      case "live_requests":
        currentScreenInstance = new LiveRequestsScreen(screenContainer);
        break;
      case "sessions":
        currentScreenInstance = new SessionsScreen(screenContainer);
        break;
      case "alerts":
        currentScreenInstance = new AlertsScreen(screenContainer);
        break;
      case "doctor":
        currentScreenInstance = new DoctorScreen(screenContainer);
        break;
      case "logs":
        currentScreenInstance = new LogsScreen(screenContainer);
        break;
      case "detection":
        currentScreenInstance = new DetectionScreen(screenContainer);
        break;
      case "reports":
        currentScreenInstance = new ReportsScreen(screenContainer);
        break;
      case "test_center":
        currentScreenInstance = new TestCenterScreen(screenContainer);
        break;
      case "version_update":
        currentScreenInstance = new VersionUpdateScreen(screenContainer);
        break;
      default:
        currentScreenInstance = new HomeScreen(screenContainer);
        break;
    }

    currentScreenInstance.render();
  };

  // Subscribe to screen changes and re-render
  store.subscribe((state) => {
    if (state.currentScreen !== activeScreenId) {
      renderActiveScreen();
    }
  });

  renderActiveScreen();

  // Connect to Brain Daemon WebSocket for live events
  const wsUrl = (import.meta as ImportMeta & { env?: { VITE_WS_URL?: string } }).env?.VITE_WS_URL || "ws://localhost:7700/ws";
  const ws = new BrainWebSocket({ url: wsUrl });

  ws.onEvent((ev: BrainEvent) => {
    if (ev.event === "gateway_health") {
      // Update requests or alert if any
    }
  });

  try {
    ws.connect();
  } catch {
    // Daemon offline is handled smoothly by store
  }

  window.addEventListener("beforeunload", () => {
    ws.close();
  });
}

mount();
