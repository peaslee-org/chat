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

  describe("overlay navigation", () => {
    const three = [
      ...photos,
      { filename: "0003.jpg", url: "https://s3/full/0003.jpg", thumb_url: "https://s3/thumbs/0003.jpg" },
    ]
    const overlayImg = (w: ReturnType<typeof mount>) => w.find('[data-testid="photo-overlay"] img').attributes("src")
    const key = (k: string) => document.dispatchEvent(new KeyboardEvent("keydown", { key: k }))

    it("arrow keys move to the next and previous photo", async () => {
      const w = mount(PhotoGrid, { props: { photos: three }, attachTo: document.body })
      await w.findAll("img")[0].trigger("click")
      key("ArrowRight"); await w.vm.$nextTick()
      expect(overlayImg(w)).toBe("https://s3/full/0002.jpg")
      key("ArrowRight"); await w.vm.$nextTick()
      expect(overlayImg(w)).toBe("https://s3/full/0003.jpg")
      key("ArrowLeft"); await w.vm.$nextTick()
      expect(overlayImg(w)).toBe("https://s3/full/0002.jpg")
      w.unmount()
    })

    it("stops at the ends and disables the chevron there", async () => {
      const w = mount(PhotoGrid, { props: { photos: three }, attachTo: document.body })
      await w.findAll("img")[0].trigger("click")
      expect(w.find('[data-testid="photo-prev"]').attributes("disabled")).toBeDefined()
      key("ArrowLeft"); await w.vm.$nextTick()
      expect(overlayImg(w)).toBe("https://s3/full/0001.jpg")
      key("ArrowRight"); key("ArrowRight"); key("ArrowRight"); await w.vm.$nextTick()
      expect(overlayImg(w)).toBe("https://s3/full/0003.jpg")
      expect(w.find('[data-testid="photo-next"]').attributes("disabled")).toBeDefined()
      w.unmount()
    })

    it("captions the photo with its position", async () => {
      const w = mount(PhotoGrid, { props: { photos: three }, attachTo: document.body })
      await w.findAll("img")[1].trigger("click")
      expect(w.find('[data-testid="photo-overlay"]').text()).toContain("0002.jpg · 2 / 3")
      w.unmount()
    })

    it("clicking a chevron navigates without closing", async () => {
      const w = mount(PhotoGrid, { props: { photos: three }, attachTo: document.body })
      await w.findAll("img")[0].trigger("click")
      await w.find('[data-testid="photo-next"]').trigger("click")
      expect(w.find('[data-testid="photo-overlay"]').exists()).toBe(true)
      expect(overlayImg(w)).toBe("https://s3/full/0002.jpg")
      w.unmount()
    })
  })

  describe("thumbnail loading state", () => {
    it("counts tiles as they load, then reports the total", async () => {
      const w = mount(PhotoGrid, { props: { photos } })
      expect(w.text()).toContain("Loading photos… 0 of 2")
      expect(w.findAll('[data-testid="thumb-pending"]')).toHaveLength(2)
      await w.findAll("img")[0].trigger("load")
      expect(w.text()).toContain("Loading photos… 1 of 2")
      expect(w.findAll('[data-testid="thumb-pending"]')).toHaveLength(1)
      await w.findAll("img")[1].trigger("load")
      expect(w.text()).toContain("2 photos")
      expect(w.text()).not.toContain("Loading photos")
      expect(w.findAll('[data-testid="thumb-pending"]')).toHaveLength(0)
    })

    it("a thumbnail that fails shows a muted tile and still counts as done", async () => {
      const w = mount(PhotoGrid, { props: { photos } })
      await w.findAll("img")[0].trigger("error")
      await w.findAll("img")[1].trigger("load")
      expect(w.findAll('[data-testid="thumb-error"]')).toHaveLength(1)
      expect(w.text()).toContain("2 photos")
    })

    it("says it is preparing thumbnails while the list is still loading", () => {
      const w = mount(PhotoGrid, { props: { photos: [], loading: true } })
      expect(w.text()).toContain("Preparing thumbnails…")
    })
  })
})
