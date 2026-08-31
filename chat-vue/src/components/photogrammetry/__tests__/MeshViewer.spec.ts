import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"

// The real module registers a WebGL custom element; jsdom has no WebGL. An unregistered
// <model-viewer> is a plain HTMLElement, which is all the event plumbing needs.
// ModelViewerElement is stubbed so the module-scope decoder configuration has a target.
vi.mock("@google/model-viewer", () => ({ ModelViewerElement: class {} }))

import { ModelViewerElement } from "@google/model-viewer"
import MeshViewer from "../MeshViewer.vue"

function mountViewer(props: Partial<{ src: string; pending: boolean }> = {}) {
  return mount(MeshViewer, { props: { src: "https://s3/mesh.glb", mock: false, ...props } })
}

describe("MeshViewer meshopt decoder", () => {
  it("points model-viewer at the bundled meshopt decoder before the first viewer mounts", () => {
    // Worker GLBs use EXT_meshopt_compression (gltfpack); without a decoder location model-viewer
    // fails to load them. Importing the component module must configure it (module scope).
    expect((ModelViewerElement as unknown as { meshoptDecoderLocation?: string }).meshoptDecoderLocation)
      .toMatch(/meshopt_decoder/)
  })
})

describe("MeshViewer loading pill", () => {
  it("shows progress from <model-viewer> progress events", async () => {
    const w = mountViewer()
    const mv = w.find("model-viewer")
    expect(mv.exists()).toBe(true)
    mv.element.dispatchEvent(new CustomEvent("progress", { detail: { totalProgress: 0.42 } }))
    await w.vm.$nextTick()
    expect(w.find('[data-testid="mesh-pill"]').text()).toBe("Loading mesh… 42%")
  })

  it("hides the pill once the model has loaded", async () => {
    const w = mountViewer()
    const mv = w.find("model-viewer")
    mv.element.dispatchEvent(new CustomEvent("progress", { detail: { totalProgress: 1 } }))
    mv.element.dispatchEvent(new Event("load"))
    await w.vm.$nextTick()
    expect(w.find('[data-testid="mesh-pill"]').exists()).toBe(false)
  })

  it("shows an error pill when the model fails to load", async () => {
    const w = mountViewer()
    w.find("model-viewer").element.dispatchEvent(new Event("error"))
    await w.vm.$nextTick()
    expect(w.find('[data-testid="mesh-pill"]').text()).toBe("Couldn't load the mesh")
  })

  it("renders the shell with a 0% pill and no model while pending", () => {
    const w = mountViewer({ pending: true, src: undefined })
    expect(w.find("model-viewer").exists()).toBe(false)
    expect(w.find('[data-testid="mesh-pill"]').text()).toBe("Loading mesh… 0%")
  })

  it("tracks progress on a viewer that appears after pending resolves", async () => {
    const w = mountViewer({ pending: true, src: undefined })
    await w.setProps({ pending: false, src: "https://s3/mesh.glb" })
    const mv = w.find("model-viewer")
    expect(mv.exists()).toBe(true)
    mv.element.dispatchEvent(new CustomEvent("progress", { detail: { totalProgress: 0.42 } }))
    await w.vm.$nextTick()
    expect(w.find('[data-testid="mesh-pill"]').text()).toBe("Loading mesh… 42%")
  })

  it("goes back to loading when src changes to another mesh", async () => {
    const w = mountViewer()
    w.find("model-viewer").element.dispatchEvent(new Event("load"))
    await w.vm.$nextTick()
    expect(w.find('[data-testid="mesh-pill"]').exists()).toBe(false)
    await w.setProps({ src: "https://s3/other.glb" })
    expect(w.find('[data-testid="mesh-pill"]').text()).toBe("Loading mesh… 0%")
  })
})
