# Photogrammetry sample assets

Served by `LocalPhotogrammetryService` (`USE_MOCK_PHOTOGRAMMETRY=true`) and by `POST /jobs/sample`.

- `images/NNNN.jpg` — a real phone photo set, downscaled to 640 px, **all EXIF stripped**.
- `mesh.glb`, `preview.png` — a procedural placeholder. It is **not** reconstructed from the photos;
  the API marks every mock result `mock: true` and the UI says so.

Regenerate with `scripts/dev/make-photogrammetry-sample.py` (see its docstring).
