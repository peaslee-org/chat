import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"

import PublicToggle from "../PublicToggle.vue"

describe("PublicToggle", () => {
  it("shows state and emits the flipped value", async () => {
    const w = mount(PublicToggle, { props: { isPublic: false } })
    expect(w.text()).toContain("Make public")
    await w.find('[data-testid="public-toggle"]').trigger("click")
    expect(w.emitted("toggle")![0]).toEqual([true])
  })

  it("reads Public when on and disables while busy", () => {
    const w = mount(PublicToggle, { props: { isPublic: true, busy: true } })
    expect(w.text()).toContain("Public")
    expect(w.find("button").attributes("disabled")).toBeDefined()
  })
})
