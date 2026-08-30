# Photogrammetry sample assets

Served by `LocalPhotogrammetryService` (`USE_MOCK_PHOTOGRAMMETRY=true`) and by `POST /jobs/sample`.

- `images/NNNN.jpg` — a real phone photo set, downscaled to 640 px, **all EXIF stripped**.
- `mesh.glb`, `preview.png` — a procedural placeholder. It is **not** reconstructed from the photos;
  the API marks every mock result `mock: true` and the UI says so.

Regenerate with `scripts/dev/make-photogrammetry-sample.py` (see its docstring).

**Where the set lives.** Locally the mock seeds these 22 photos into the dev-upload sink under
`samples/photogrammetry/images/` on the first `GET /samples`. In production the same set was
uploaded by hand to the audio bucket at `PHOTOGRAMMETRY_SAMPLE_PREFIX` + `images/`
(`samples/photogrammetry/images/0001.jpg …`). Thumbnails are generated on demand into the
**sibling** `samples/photogrammetry/thumbs/` — never write anything inside `images/`; the sample
job and the listing take every direct child of that prefix as an input photo.
