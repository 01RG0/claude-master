import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["../tests/studio/**/*.test.ts", "src/**/*.test.ts"],
    globals: false,
  },
});
