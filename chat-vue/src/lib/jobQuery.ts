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
