import { defineConfig } from "vitest/config";
export default defineConfig({ test: { include: ["worker/tests/**/*.test.ts"], fileParallelism: false, testTimeout: 30000, hookTimeout: 60000 } });
