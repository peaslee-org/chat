import { http, HttpResponse, type JsonBodyType } from 'msw'
import type { TrafficEntry } from '@/lib/trafficRecorder'
import capturedTraffic from 'virtual:mock-traffic'

type HttpMethod = 'get' | 'post' | 'put' | 'patch' | 'delete' | 'head' | 'options'

// Deduplicate: last captured entry wins for each method+path combo
const seen = new Map<string, TrafficEntry>()
for (const entry of capturedTraffic as TrafficEntry[]) {
  seen.set(`${entry.method}:${entry.path}`, entry)
}

export const handlers = [
  // Intercept presigned S3 PUTs (audio uploads) so they don't reach real S3 with expired credentials
  http.put('https://*.s3.amazonaws.com/*', () => new HttpResponse(null, { status: 200 })),

  ...[...seen.values()].flatMap(({ method, path, status, responseData }) => {
    const fn = http[method.toLowerCase() as HttpMethod]
    if (!fn) return []
    return [
      fn(path, () => HttpResponse.json(responseData as JsonBodyType, { status })),
    ]
  }),
]
