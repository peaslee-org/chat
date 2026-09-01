import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import fs from 'node:fs'
import path from 'node:path'

const VIRTUAL_MOCK_TRAFFIC = 'virtual:mock-traffic'
const RESOLVED_VIRTUAL_MOCK_TRAFFIC = '\0' + VIRTUAL_MOCK_TRAFFIC

export default defineConfig(({ mode }) => ({
  plugins: [
    vue({ template: { compilerOptions: { isCustomElement: (tag) => tag === 'model-viewer' } } }),
    {
      // Provides `virtual:mock-traffic` — returns captured traffic.json contents,
      // or an empty array if the file doesn't exist (e.g. in CI).
      name: 'mock-traffic',
      resolveId(id) {
        if (id === VIRTUAL_MOCK_TRAFFIC) return RESOLVED_VIRTUAL_MOCK_TRAFFIC
      },
      load(id) {
        if (id !== RESOLVED_VIRTUAL_MOCK_TRAFFIC) return
        const trafficPath = path.resolve(__dirname, 'src/mocks/traffic.json')
        try {
          return `export default ${fs.readFileSync(trafficPath, 'utf-8')}`
        } catch {
          return `export default []`
        }
      },
    },
    {
      name: 'html-title',
      transformIndexHtml(html) {
        const title = mode === 'production' ? 'aiTools' : 'aiTools-dev'
        return html.replace('<title>aiTools</title>', `<title>${title}</title>`)
      },
    },
  ],
  resolve: {
    alias: [
      { find: '@', replacement: fileURLToPath(new URL('./src', import.meta.url)) },
      // The UMD meshopt decoder (classic script defining the global model-viewer expects) is only
      // behind a `require` export condition, which Vite rejects on an import — alias to the file.
      // Regex form: a string alias won't match once the `?url` query is attached (Rollup build).
      { find: /^meshopt-decoder\.cjs/, replacement: fileURLToPath(new URL('./node_modules/meshoptimizer/meshopt_decoder.cjs', import.meta.url)) },
    ],
  },
  server: {
    port: 5173,
    allowedHosts: ['dev.chat.example.com'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
}))
