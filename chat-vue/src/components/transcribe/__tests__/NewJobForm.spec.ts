import { beforeEach, describe, expect, it, vi } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/transcribeApi", () => ({
  getSamples: vi.fn(),
  createSampleJob: vi.fn(),
  listSpeakers: vi.fn(),
}))

import * as api from "@/lib/transcribeApi"
import NewJobForm from "../NewJobForm.vue"
import AudioFileDropzone from "../AudioFileDropzone.vue"

const PREVIEW = {
  name: "Sample conversation",
  audio: { filename: "conversation", url: "https://dl/samples/conversation.wav" },
  speakers: [
    { speaker_name: "Barry", url: "https://dl/samples/speakers/barry.wav" },
    { speaker_name: "Jane", url: "https://dl/samples/speakers/jane.wav" },
  ],
}

function mountForm() {
  return mount(NewJobForm, { attachTo: document.body })
}

describe("NewJobForm — sample preview", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.getSamples).mockReset()
    vi.mocked(api.createSampleJob).mockReset()
    vi.mocked(api.listSpeakers).mockReset().mockResolvedValue({ items: [], next_cursor: null })
    // jsdom has no real object-URL support; AudioFileDropzone's nested AudioPlayer needs this
    // once a File is selected (only exercised by the round-trip test below).
    URL.createObjectURL = vi.fn(() => "blob:mock-url")
    URL.revokeObjectURL = vi.fn()
  })

  it("clicking Try the sample fetches the preview but submits nothing", async () => {
    vi.mocked(api.getSamples).mockResolvedValue(PREVIEW)
    const wrapper = mountForm()

    await wrapper.find("button[data-test=try-sample]").trigger("click")
    await flushPromises()

    expect(api.getSamples).toHaveBeenCalledOnce()
    expect(api.createSampleJob).not.toHaveBeenCalled()
  })

  it("renders players for the fetched audio and both speakers", async () => {
    vi.mocked(api.getSamples).mockResolvedValue(PREVIEW)
    const wrapper = mountForm()

    await wrapper.find("button[data-test=try-sample]").trigger("click")
    await flushPromises()

    const audioEls = wrapper.findAll("audio")
    const srcs = audioEls.map((el) => el.attributes("src"))
    expect(srcs).toContain(PREVIEW.audio.url)
    expect(srcs).toContain(PREVIEW.speakers[0].url)
    expect(srcs).toContain(PREVIEW.speakers[1].url)
    expect(wrapper.text()).toContain("Barry")
    expect(wrapper.text()).toContain("Jane")
  })

  it("Start transcription submits the sample job and emits submitted", async () => {
    vi.mocked(api.getSamples).mockResolvedValue(PREVIEW)
    vi.mocked(api.createSampleJob).mockResolvedValue({ job_id: "job-1", speaker_ids: ["s1", "s2"] })
    const wrapper = mountForm()

    await wrapper.find("button[data-test=try-sample]").trigger("click")
    await flushPromises()
    await wrapper.find("button[data-test=start-sample]").trigger("click")
    await flushPromises()

    expect(api.createSampleJob).toHaveBeenCalledOnce()
    expect(wrapper.emitted("submitted")).toBeTruthy()
  })

  it("Use my own audio instead returns to the normal form without submitting", async () => {
    vi.mocked(api.getSamples).mockResolvedValue(PREVIEW)
    const wrapper = mountForm()

    await wrapper.find("button[data-test=try-sample]").trigger("click")
    await flushPromises()
    await wrapper.find("button[data-test=use-own-audio]").trigger("click")

    expect(api.createSampleJob).not.toHaveBeenCalled()
    expect(wrapper.find("button[data-test=try-sample]").exists()).toBe(true)
    expect(wrapper.find("audio").exists()).toBe(false)
  })

  it("sample state pre-fills the normal form and disables/hides the user's own controls", async () => {
    vi.mocked(api.getSamples).mockResolvedValue(PREVIEW)
    const wrapper = mountForm()

    await wrapper.find("button[data-test=try-sample]").trigger("click")
    await flushPromises()

    // The user's own interactive controls are gone/inert while sample state is active.
    expect(wrapper.find("button[data-test=try-sample]").exists()).toBe(false)
    expect(wrapper.find("input[type=number]").exists()).toBe(false)
    expect(wrapper.find("select").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("Submit")

    // Sample's fixed values are shown in disabled controls.
    const sampleLanguage = wrapper.find("[data-test=sample-language]")
    expect(sampleLanguage.exists()).toBe(true)
    expect((sampleLanguage.element as HTMLInputElement).value).toBe("English (US)")
    expect(sampleLanguage.attributes("disabled")).toBeDefined()

    const sampleSpeakerCount = wrapper.find("[data-test=sample-speaker-count]")
    expect(sampleSpeakerCount.exists()).toBe(true)
    expect((sampleSpeakerCount.element as HTMLInputElement).value).toBe("2")
    expect(sampleSpeakerCount.attributes("disabled")).toBeDefined()

    // Start transcription button is present in place of the normal submit button.
    expect(wrapper.find("button[data-test=start-sample]").exists()).toBe(true)
    expect(wrapper.find("button[data-test=use-own-audio]").exists()).toBe(true)
  })

  it("shows an error and no players when the fetch fails", async () => {
    vi.mocked(api.getSamples).mockRejectedValue(new Error("Sample audio has not been uploaded"))
    const wrapper = mountForm()

    await wrapper.find("button[data-test=try-sample]").trigger("click")
    await flushPromises()

    expect(wrapper.find("audio").exists()).toBe(false)
    expect(wrapper.find("[data-test=sample-error]").exists()).toBe(true)
    expect(wrapper.find("button[data-test=start-sample]").attributes("disabled")).toBeDefined()
  })

  it("Use my own audio instead preserves a previously selected audio file in the dropzone", async () => {
    vi.mocked(api.getSamples).mockResolvedValue(PREVIEW)
    const wrapper = mountForm()

    const file = new File(["audio-bytes"], "my-clip.mp3", { type: "audio/mpeg" })
    const dropzone = wrapper.findComponent(AudioFileDropzone)
    ;(dropzone.vm as unknown as { setFile: (f: File) => void }).setFile(file)
    await flushPromises()
    expect(wrapper.text()).toContain("my-clip.mp3")

    await wrapper.find("button[data-test=try-sample]").trigger("click")
    await flushPromises()
    await wrapper.find("button[data-test=use-own-audio]").trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("my-clip.mp3")
  })

  it("Try the sample with an unsaved, focused speaker draft does not pop the unsaved-draft modal", async () => {
    vi.mocked(api.getSamples).mockResolvedValue(PREVIEW)
    const wrapper = mountForm()

    const draftInput = wrapper.find('input[type="text"]')
    await draftInput.setValue("Alice")
    // Simulate focus leaving the draft container, as it does in a real browser when the user
    // clicks "Try the sample" — handleDraftFocusOut's check is deferred via setTimeout(0), so
    // it runs after sampleMode is already true.
    await draftInput.trigger("focusout")
    await wrapper.find("button[data-test=try-sample]").trigger("click")
    await new Promise((resolve) => setTimeout(resolve, 0))
    await flushPromises()

    expect(document.body.textContent).not.toContain("Unsaved speaker")

    await wrapper.find("button[data-test=use-own-audio]").trigger("click")
    await flushPromises()

    expect((wrapper.find('input[type="text"]').element as HTMLInputElement).value).toBe("Alice")
  })
})
