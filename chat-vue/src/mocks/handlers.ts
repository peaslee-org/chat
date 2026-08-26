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

  // GPU controller — default to a warm, ready worker with no usage history
  http.get('*/api/v1/gpu/state', () =>
    HttpResponse.json({ worker_state: 'running', estimated_wait_seconds: 0, warm_until: null, notice: null }),
  ),
  http.post('*/api/v1/gpu/warm', () =>
    HttpResponse.json({ worker_state: 'running', estimated_wait_seconds: 0, warm_until: null, notice: null }),
  ),
  http.get('*/api/v1/gpu/usage', () =>
    HttpResponse.json({
      today_hours: 0, month_hours: 0, daily_cap_hours: 4, monthly_cap_hours: 40,
      warms_today_for_user: 0, warm_cap_per_user_per_day: 10,
      estimated_month_cost_usd: 0, hourly_rate_usd: 0,
      actual_month_to_date_usd: null, actual_fetched_at: null,
      sessions: [],
    }),
  ),

  ...[...seen.values()].flatMap(({ method, path, status, responseData }) => {
    const fn = http[method.toLowerCase() as HttpMethod]
    if (!fn) return []
    return [
      fn(path, () => HttpResponse.json(responseData as JsonBodyType, { status })),
    ]
  }),
]
