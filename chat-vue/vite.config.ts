import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import fs from 'node:fs'
import path from 'node:path'

const VIRTUAL_MOCK_TRAFFIC = 'virtual:mock-traffic'
const RESOLVED_VIRTUAL_MOCK_TRAFFIC = '\0' + VIRTUAL_MOCK_TRAFFIC

export default defineConfig(({ mode }) => ({
  plugins: [
    vue(),
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
        const title = mode === 'production' ? 'Chat' : 'Chat-dev'
        return html.replace('<title>Chat</title>', `<title>${title}</title>`)
      },
    },
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
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
