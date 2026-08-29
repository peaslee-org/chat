import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import PhotoGrid from "../PhotoGrid.vue"

const photos = [
  { filename: "0001.jpg", url: "https://s3/full/0001.jpg", thumb_url: "https://s3/thumbs/0001.jpg" },
  { filename: "0002.jpg", url: "https://s3/full/0002.jpg", thumb_url: "https://s3/thumbs/0002.jpg" },
]

describe("PhotoGrid", () => {
  it("renders one lazy thumbnail per photo, named by filename", () => {
    const w = mount(PhotoGrid, { props: { photos } })
    const imgs = w.findAll("img")
    expect(imgs).toHaveLength(2)
    expect(imgs[0].attributes("src")).toBe("https://s3/thumbs/0001.jpg")
    expect(imgs[0].attributes("loading")).toBe("lazy")
    expect(imgs[0].attributes("alt")).toBe("0001.jpg")
    expect(imgs[0].attributes("title")).toBe("0001.jpg")
  })

  it("clicking a thumbnail emits open and shows the full-size image in an overlay", async () => {
    const w = mount(PhotoGrid, { props: { photos }, attachTo: document.body })
    await w.findAll("img")[1].trigger("click")
    expect(w.emitted("open")?.[0]).toEqual([photos[1]])
    const overlay = w.find('[data-testid="photo-overlay"]')
    expect(overlay.exists()).toBe(true)
    expect(overlay.find("img").attributes("src")).toBe("https://s3/full/0002.jpg")
    expect(overlay.text()).toContain("0002.jpg")
    w.unmount()
  })

  it("Escape closes the overlay", async () => {
    const w = mount(PhotoGrid, { props: { photos }, attachTo: document.body })
    await w.findAll("img")[0].trigger("click")
    expect(w.find('[data-testid="photo-overlay"]').exists()).toBe(true)
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }))
    await w.vm.$nextTick()
    expect(w.find('[data-testid="photo-overlay"]').exists()).toBe(false)
    w.unmount()
  })

  it("clicking the backdrop closes the overlay", async () => {
    const w = mount(PhotoGrid, { props: { photos }, attachTo: document.body })
    await w.findAll("img")[0].trigger("click")
    await w.find('[data-testid="photo-overlay"]').trigger("click")
    expect(w.find('[data-testid="photo-overlay"]').exists()).toBe(false)
    w.unmount()
  })

  it("shows skeleton squares while loading and an error message on failure", () => {
    const loading = mount(PhotoGrid, { props: { photos: [], loading: true } })
    expect(loading.findAll('[data-testid="skeleton"]').length).toBeGreaterThan(0)
    const failed = mount(PhotoGrid, { props: { photos: [], error: "Could not load photos" } })
    expect(failed.text()).toContain("Could not load photos")
  })
})
