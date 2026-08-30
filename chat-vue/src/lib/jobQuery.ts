import { watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import type { RouteLocationNormalizedLoaded, Router } from "vue-router"

/**
 * One-shot deep link: `/photogrammetry?job=<id>` (or `/transcribe?job=<id>`) opens that job on
 * arrival — used by the usage panel's Startups links. Returns the id and strips the param from
 * the URL so a reload or back-navigation doesn't reopen it; null when absent, empty or repeated.
 */
export function takeJobQuery(route: RouteLocationNormalizedLoaded, router: Router): string | null {
  const { job, ...rest } = route.query
  if (typeof job !== "string" || job === "") return null
  void router.replace({ query: rest })
  return job
}

/**
 * Wire `?job=` to `open` for a page that stays mounted: the Startups links on `/photogrammetry`
 * point at `/photogrammetry?job=…` — a same-route navigation that reuses the component, so
 * `onMounted` never sees it. The watch covers that; the returned `check()` is for the cold-load
 * case and is meant to be called once the page's jobs are loaded.
 */
export function useJobDeepLink(open: (id: string) => void): () => void {
  const route = useRoute()
  const router = useRouter()
  const check = (): void => {
    const id = takeJobQuery(route, router)
    if (id) open(id)
  }
  watch(() => route.query.job, check)
  return check
}
