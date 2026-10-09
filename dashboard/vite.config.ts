/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API of the simulator listens on loopback by default (CAUDAL_SIM_DASHBOARD_PORT).
const API_TARGET = "http://127.0.0.1:8000";
const TEST_ENVIRONMENT = "jsdom";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: API_TARGET },
    },
  },
  test: {
    environment: TEST_ENVIRONMENT,
  },
});
