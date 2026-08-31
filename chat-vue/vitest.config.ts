import { defineConfig } from "vitest/config"
import vue from "@vitejs/plugin-vue"
import { fileURLToPath, URL } from "node:url"

// Mirrors vite.config.ts's vue plugin options (model-viewer is a custom element) and `@` alias.
export default defineConfig({
  plugins: [vue({ template: { compilerOptions: { isCustomElement: (tag) => tag === "model-viewer" } } })],
  resolve: {
    alias: [
      { find: "@", replacement: fileURLToPath(new URL("./src", import.meta.url)) },
      { find: /^meshopt-decoder\.cjs/, replacement: fileURLToPath(new URL("./node_modules/meshoptimizer/meshopt_decoder.cjs", import.meta.url)) },
    ],
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.spec.ts"],
  },
})
