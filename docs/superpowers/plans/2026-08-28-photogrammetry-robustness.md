# Photogrammetry Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A photogrammetry job can no longer OOM-cycle: oversized meshes are decimated to a budget, completed stages are checkpointed on the instance disk and skipped on resume, a stage that crashed is failed rather than re-run, photo orientation is normalised at fetch, and every such event reaches the user as a warning in the scan view and as a toast.

**Architecture:** The worker's handler stays a linear stage table but every stage is wrapped by a `Checkpoints` object (marker files in the job's scratch dir, which moves to a host-path volume). Attempt accounting is the SQS `ApproximateReceiveCount` plus a `stage.started` marker; a `warnings` JSON column on `photogrammetry_jobs` carries user-facing notices from worker → API → Vue. The mesh budget lives in the handler as two constants and an OpenMVS `--decimate` ratio.

**Tech Stack:** Python 3.12 / pytest / SQLAlchemy 2 / Pillow / trimesh (worker); FastAPI + Alembic (chat-api); Vue 3 + Pinia + TypeScript (chat-vue); Terraform (infra module). Tests run with `uv run pytest -q` in `photogrammetry-worker/`, `gpu-worker/`, and `chat-api/` (`tests/unit`), `npm run type-check && npm run build` in `chat-vue/`.

**Spec:** `docs/superpowers/specs/2026-08-28-photogrammetry-robustness-design.md`

## Global Constraints

- `REFINE_MAX_FACES = 400_000`, `FACE_BUDGET = 500_000`, `MAX_ATTEMPTS = 5`, `REFINE_MAX_IMAGES = 100` (existing), `MIN_IMAGES = 5`, scratch sweep `max_age = 24 h`.
- `WORK_DIR` stays `/tmp/pg`; the host path is `/var/lib/photogrammetry`.
- User-facing strings (copy verbatim):
  - crash: `Reconstruction crashed during the {stage} stage (probably out of memory) — try fewer photos or one object per scan.` where `{stage}` is `sfm`/`dense`/`mesh`/`texture`/`export` (`publish` renders as `export`).
  - repeated: `Reconstruction did not finish after 5 attempts (interrupted or out of memory) — try again with fewer photos or one object per scan.`
  - decimation: `Mesh simplified from {faces:,} to about {FACE_BUDGET:,} faces to fit the viewer`
  - rotation: `{n} photo(s) were rotated to match the others (phone auto-rotate)` — use `photo` for 1, `photos` otherwise.
  - skipped: `{n} photo(s) have a different resolution and were skipped: {names}` — names comma-separated, at most 5 then `…`.
  - too few: `Only {usable} photos could be used — at least 5 are needed`
- No account identifiers, instance IDs, ARNs or cost figures in code, tests, docs or commit messages (public repo).
- Commit after every task; messages in the repo's style (`feat(worker): …`, `feat(api): …`, `feat(vue): …`, `infra: …`, `docs: …`). Do not push — Neil pushes.
- Never run `terraform fmt -recursive` from `infra/` (it follows the overlay symlinks); `terraform fmt` on the single module file only.

---

## File map

| file | responsibility |
|---|---|
| `photogrammetry-worker/pipeline/openmvs.py` (modify) | `mesh_faces()` parser; `reconstruct_mesh`/`refine_mesh` return `(ply, faces)`; `texture_mesh(decimate=)` |
| `photogrammetry-worker/pipeline/reconstruct.py` (modify) | stage object: `reconstruct_mesh`, `refine_mesh`, `texture(decimate)` |
| `photogrammetry-worker/pipeline/export.py` (modify) | scene-based GLB export |
| `photogrammetry-worker/pipeline/checkpoints.py` (create) | marker files, `crashed_stage`, `sweep_stale` |
| `photogrammetry-worker/pipeline/photos.py` (create) | EXIF transpose, rotate-to-majority, skip odd sizes |
| `photogrammetry-worker/handlers/photogrammetry.py` (modify) | stage table with resume, crash rule, receive-count backstop, budget, warnings |
| `photogrammetry-worker/main.py` (modify) | pass receive count; sweep at start |
| `photogrammetry-worker/models.py` (modify) | `warnings` column |
| `gpu-worker/gpu_worker/sqs.py` (modify) | request `ApproximateReceiveCount` |
| `chat-api/app/db/migrations/versions/o5p6q7r8s9t0_add_photogrammetry_warnings.py` (create) | column |
| `chat-api/app/models/photogrammetry.py`, `app/schemas/photogrammetry.py`, `app/services/photogrammetry_service.py` (modify) | column, field, mapping |
| `chat-vue/src/types/index.ts`, `stores/photogrammetry.ts`, `components/photogrammetry/{ScanDetailView,ScanJobCard}.vue` (modify) | type, toast diff, notices, glyph |
| `infra/modules/photogrammetry/main.tf` (modify) | host-path volume |
| `docs/TODO.md` (modify) | deploy batch entries |

---

### Task 1: OpenMVS face count and decimation

**Files:**
- Modify: `photogrammetry-worker/pipeline/openmvs.py`
- Test: `photogrammetry-worker/tests/test_openmvs.py`

**Interfaces:**
- Produces: `mesh_faces(output: str) -> int` (raises `StageError(tool, "could not read face count")`); `reconstruct_mesh(runner, dense, scene_dense, use_gpu=True) -> tuple[Path, int]`; `refine_mesh(runner, dense, scene_dense, mesh_ply, use_gpu=True) -> tuple[Path, int]`; `texture_mesh(runner, dense, scene_dense, mesh_ply, use_gpu=True, decimate: float | None = None) -> Path`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_openmvs.py` (and change `FakeRunner` so it can return output):

```python
from pipeline.openmvs import mesh_faces
from pipeline.runner import StageError
import pytest

SAVED = "19:05:16 [Mesh    ] Mesh 'scene_dense_mesh.ply' saved: 337881 vertices, 675489 faces (72ms)\n19:05:16 [App     ] \tVmPeak:\t 6302564 kB\n"


class OutputRunner(FakeRunner):
    def __init__(self, output=SAVED):
        super().__init__(); self.output = output
    def run(self, cmd, cwd, tool=None):
        super().run(cmd, cwd, tool); return self.output


def test_mesh_faces_reads_last_saved_line():
    two = "Mesh 'a.ply' saved: 10 vertices, 20 faces (1ms)\nMesh 'b.ply' saved: 30 vertices, 40 faces (1ms)\n"
    assert mesh_faces(two) == 40


def test_mesh_faces_raises_when_absent():
    with pytest.raises(StageError) as e:
        mesh_faces("no mesh here", tool="ReconstructMesh")
    assert e.value.tool == "ReconstructMesh" and "face count" in str(e.value)


def test_reconstruct_and_refine_return_face_counts(tmp_path):
    r = OutputRunner()
    ply, faces = reconstruct_mesh(r, tmp_path, tmp_path / "scene_dense.mvs")
    assert ply == tmp_path / "scene_dense_mesh.ply" and faces == 675489
    ply2, faces2 = refine_mesh(r, tmp_path, tmp_path / "scene_dense.mvs", ply)
    assert ply2 == tmp_path / "scene_dense_mesh_refine.ply" and faces2 == 675489


def test_texture_mesh_passes_decimate_only_when_given(tmp_path):
    r = FakeRunner()
    texture_mesh(r, tmp_path, tmp_path / "s.mvs", tmp_path / "m.ply")
    assert "--decimate" not in r.calls[0][0]
    texture_mesh(r, tmp_path, tmp_path / "s.mvs", tmp_path / "m.ply", decimate=0.396)
    cmd = r.calls[1][0]
    assert cmd[cmd.index("--decimate") + 1] == "0.396"
```

Also update `test_chain_produces_expected_paths`: `mesh, _ = reconstruct_mesh(...)` and `refined, _ = refine_mesh(...)` with `r = OutputRunner()`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd photogrammetry-worker && uv run pytest tests/test_openmvs.py -q`
Expected: FAIL — `ImportError: cannot import name 'mesh_faces'`.

- [ ] **Step 3: Implement**

In `pipeline/openmvs.py`:

```python
import re
from pipeline.runner import StageError

_SAVED = re.compile(r"Mesh '[^']*' saved: (\d+) vertices, (\d+) faces")


def mesh_faces(output: str, tool: str = "ReconstructMesh") -> int:
    """Face count from the last `Mesh '…' saved: V vertices, F faces` line OpenMVS prints."""
    matches = _SAVED.findall(output)
    if not matches:
        raise StageError(tool, "could not read face count")
    return int(matches[-1][1])


def reconstruct_mesh(runner, dense: Path, scene_dense: Path, use_gpu: bool = True) -> tuple[Path, int]:
    out = dense / "scene_dense_mesh.mvs"
    output = runner.run(["ReconstructMesh", str(scene_dense), "-w", str(dense), "-o", str(out), *_cuda_device(use_gpu)],
                        cwd=dense, tool="ReconstructMesh")
    return dense / "scene_dense_mesh.ply", mesh_faces(output, "ReconstructMesh")


def refine_mesh(runner, dense: Path, scene_dense: Path, mesh_ply: Path, use_gpu: bool = True) -> tuple[Path, int]:
    out = dense / "scene_dense_mesh_refine.mvs"
    output = runner.run(["RefineMesh", str(scene_dense), "-m", str(mesh_ply), "-w", str(dense), "-o", str(out),
                         *_cuda_device(use_gpu)], cwd=dense, tool="RefineMesh")
    return dense / "scene_dense_mesh_refine.ply", mesh_faces(output, "RefineMesh")


def texture_mesh(runner, dense: Path, scene_dense: Path, mesh_ply: Path, use_gpu: bool = True,
                 decimate: float | None = None) -> Path:
    out = dense / "scene_textured.mvs"
    # (keep the existing seam-leveling comment)
    cmd = ["TextureMesh", str(scene_dense), "-m", str(mesh_ply), "-w", str(dense), "-o", str(out),
           "--export-type", "obj", "--global-seam-leveling", "0", "--local-seam-leveling", "0"]
    if decimate is not None:
        cmd += ["--decimate", f"{decimate:.3f}"]   # OpenMVS decimates the input surface before texturing
    runner.run([*cmd, *_cuda_device(use_gpu)], cwd=dense, tool="TextureMesh")
    return dense / "scene_textured.obj"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_openmvs.py -q` — Expected: all PASS. (Other test files may now fail on `Reconstruction.mesh` — Task 2 fixes them.)

- [ ] **Step 5: Commit**

```bash
git add photogrammetry-worker/pipeline/openmvs.py photogrammetry-worker/tests/test_openmvs.py
git commit -m "feat(worker): OpenMVS face counts and TextureMesh --decimate"
```

---

### Task 2: Reconstruction stage object split

**Files:**
- Modify: `photogrammetry-worker/pipeline/reconstruct.py`
- Create: `photogrammetry-worker/tests/test_reconstruct.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `Reconstruction.sfm(images) -> SparseModel`; `dense(images, model) -> Path`; `reconstruct_mesh(dense) -> tuple[Path, int]`; `refine_mesh(dense, ply) -> tuple[Path, int]`; `texture(dense, ply, decimate: float | None = None) -> Path`. **`mesh()` is removed.**

- [ ] **Step 1: Write the failing test**

`tests/test_reconstruct.py`:

```python
"""Reconstruction is the stage table's view of colmap+openmvs: one method per tool group."""
from pipeline.reconstruct import Reconstruction

SAVED = "Mesh 'x.ply' saved: 3 vertices, 1 faces (0ms)\n"


class Runner:
    def __init__(self): self.cmds = []
    def run(self, cmd, cwd, tool=None):
        self.cmds.append(cmd); return SAVED


def test_mesh_stages_are_separate_calls(tmp_path):
    r = Runner()
    recon = Reconstruction(r, tmp_path, use_gpu=False)
    dense = tmp_path / "dense"
    ply, faces = recon.reconstruct_mesh(dense)
    assert ply == dense / "scene_dense_mesh.ply" and faces == 1
    refined, faces2 = recon.refine_mesh(dense, ply)
    assert refined == dense / "scene_dense_mesh_refine.ply" and faces2 == 1
    obj = recon.texture(dense, refined, decimate=0.5)
    assert obj == dense / "scene_textured.obj"
    assert [c[0] for c in r.cmds] == ["ReconstructMesh", "RefineMesh", "TextureMesh"]
    assert "--decimate" in r.cmds[2] and not hasattr(recon, "mesh")
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_reconstruct.py -q` → `AttributeError: 'Reconstruction' object has no attribute 'reconstruct_mesh'`.

- [ ] **Step 3: Implement** — replace `mesh`/`texture` in `pipeline/reconstruct.py`:

```python
    def reconstruct_mesh(self, dense: Path) -> tuple[Path, int]:
        return openmvs.reconstruct_mesh(self._r, dense, dense / "scene_dense.mvs", self._gpu)

    def refine_mesh(self, dense: Path, mesh_ply: Path) -> tuple[Path, int]:
        return openmvs.refine_mesh(self._r, dense, dense / "scene_dense.mvs", mesh_ply, self._gpu)

    def texture(self, dense: Path, mesh_ply: Path, decimate: float | None = None) -> Path:
        return openmvs.texture_mesh(self._r, dense, dense / "scene_dense.mvs", mesh_ply, self._gpu, decimate=decimate)
```

Update the module docstring to "one method per tool group; the handler decides refine and decimation".

- [ ] **Step 4: Run** — `uv run pytest tests/test_reconstruct.py tests/test_openmvs.py -q` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(worker): split Reconstruction.mesh into reconstruct/refine; texture takes decimate"` (add the new test file first).

---

### Task 3: Scene-based GLB export

**Files:**
- Modify: `photogrammetry-worker/pipeline/export.py`
- Test: `photogrammetry-worker/tests/test_export.py`

**Interfaces:** `obj_to_glb(obj: Path, out: Path) -> Path` unchanged in signature.

- [ ] **Step 1: Write the failing test** (append to `tests/test_export.py`)

```python
def write_two_material_quads(d: Path) -> Path:
    Image.new("RGB", (2, 2), (255, 0, 0)).save(d / "a.png")
    Image.new("RGB", (4, 4), (0, 0, 255)).save(d / "b.png")
    (d / "two.mtl").write_text("newmtl ma\nmap_Kd a.png\nnewmtl mb\nmap_Kd b.png\n")
    (d / "two.obj").write_text(
        "mtllib two.mtl\n"
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "v 2 0 0\nv 3 0 0\nv 3 1 0\nv 2 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
        "usemtl ma\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n"
        "usemtl mb\nf 5/1 6/2 7/3\nf 5/1 7/3 8/4\n"
    )
    return d / "two.obj"


def test_multi_material_obj_exports_one_primitive_per_material_without_repacking(tmp_path):
    """OpenMVS writes one material per atlas (two 8192² atlases on a big scan). Forcing a single
    mesh made trimesh concatenate the geometries and re-pack both textures into one image —
    the step that ran out of memory on 2026-08-28. Keep them as separate primitives."""
    obj = write_two_material_quads(tmp_path)
    scene = trimesh.load(obj_to_glb(obj, tmp_path / "mesh.glb"), force="scene")
    geoms = list(scene.geometry.values())
    assert len(geoms) == 2
    sizes = sorted(g.visual.material.baseColorTexture.size for g in geoms)
    assert sizes == [(2, 2), (4, 4)]                     # textures untouched, not merged
    lo = min(g.vertices[:, 1].min() for g in geoms)
    assert np.isclose(lo, -1.0)                          # rotation applied to every geometry
```

- [ ] **Step 2: Run** — `uv run pytest tests/test_export.py -q` → the new test FAILS (`len(geoms) == 1`, single merged texture).

- [ ] **Step 3: Implement** — in `pipeline/export.py`:

```python
def obj_to_glb(obj: Path, out: Path) -> Path:
    # One geometry per OBJ material, exported as separate glTF primitives. `force="mesh"` would
    # concatenate them and re-pack every atlas into one image — unbounded memory on large scans.
    scene = trimesh.load(obj, force="scene", process=False)
    for geometry in scene.geometry.values():
        geometry.apply_transform(CV_TO_GLTF)
    out.parent.mkdir(parents=True, exist_ok=True)
    scene.export(out, file_type="glb")
    return out
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_export.py -q` → all PASS, including the two existing single-material tests (they load with `force="mesh"`, which is fine for reading a one-primitive GLB). If `test_obj_to_glb_rotates_colmap_frame_to_gltf_y_up` fails on `face_normals`, check that `process=False` did not drop the winding — it must not; do not "fix" by removing the rotation.

- [ ] **Step 5: Commit** — `git commit -am "fix(worker): export GLB per material, no atlas re-pack"`.

---

### Task 4: Checkpoints

**Files:**
- Create: `photogrammetry-worker/pipeline/checkpoints.py`
- Create: `photogrammetry-worker/tests/test_checkpoints.py`

**Interfaces (produces):**

```python
STAGES = ("sfm", "dense", "mesh", "texture", "publish")
class Checkpoints:
    def __init__(self, work: Path) -> None
    def started(self, stage: str) -> None              # writes stage.started
    def done(self, stage: str, **data) -> None         # writes <stage>.done (JSON), removes stage.started
    def completed(self, stage: str) -> dict | None     # parsed <stage>.done or None
    def crashed_stage(self) -> str | None              # stage named in stage.started, if it has no .done
    def clear_started(self) -> None
    def first_incomplete(self) -> str                  # first stage in STAGES without .done
def sweep_stale(root: Path, max_age_seconds: int = 86_400, now: float | None = None) -> list[Path]
```

- [ ] **Step 1: Write the failing tests**

```python
"""Marker files that let a restarted job skip finished stages and refuse to repeat a crashed one."""
import json
import os
import time

from pipeline.checkpoints import STAGES, Checkpoints, sweep_stale


def test_done_records_data_and_clears_started(tmp_path):
    ck = Checkpoints(tmp_path)
    ck.started("sfm")
    assert (tmp_path / "stage.started").read_text() == "sfm"
    ck.done("sfm", sparse="/w/sparse/0", registered_images=42)
    assert ck.completed("sfm") == {"sparse": "/w/sparse/0", "registered_images": 42}
    assert not (tmp_path / "stage.started").exists() and ck.crashed_stage() is None


def test_started_without_done_is_a_crash(tmp_path):
    ck = Checkpoints(tmp_path)
    ck.done("sfm", sparse="s", registered_images=1)
    ck.started("dense")
    assert ck.crashed_stage() == "dense"
    assert ck.completed("dense") is None


def test_clear_started_is_the_interrupted_path(tmp_path):
    ck = Checkpoints(tmp_path)
    ck.started("mesh"); ck.clear_started()
    assert ck.crashed_stage() is None and not (tmp_path / "stage.started").exists()


def test_first_incomplete_walks_stage_order(tmp_path):
    ck = Checkpoints(tmp_path)
    assert ck.first_incomplete() == "sfm"
    ck.done("sfm"); ck.done("dense")
    assert ck.first_incomplete() == "mesh"
    for s in STAGES: ck.done(s)
    assert ck.first_incomplete() == "publish"   # publish.done is never written in practice; last stage wins


def test_missing_work_dir_is_fresh(tmp_path):
    ck = Checkpoints(tmp_path / "nope")
    assert ck.crashed_stage() is None and ck.completed("sfm") is None and ck.first_incomplete() == "sfm"


def test_sweep_stale_removes_old_job_dirs_only(tmp_path):
    old, new = tmp_path / "old-job", tmp_path / "new-job"
    old.mkdir(); (old / "sfm.done").write_text("{}"); new.mkdir(); (new / "x").write_text("y")
    (tmp_path / "loose-file").write_text("ignored")
    stale = time.time() - 2 * 86_400
    os.utime(old, (stale, stale)); os.utime(old / "sfm.done", (stale, stale))
    removed = sweep_stale(tmp_path, max_age_seconds=86_400)
    assert removed == [old] and not old.exists() and new.exists() and (tmp_path / "loose-file").exists()
```

- [ ] **Step 2: Run** — `uv run pytest tests/test_checkpoints.py -q` → `ModuleNotFoundError: pipeline.checkpoints`.

- [ ] **Step 3: Implement** `pipeline/checkpoints.py`:

```python
"""Stage markers in a job's scratch directory.

`<stage>.done` (JSON) means the stage finished and its outputs are on disk; `stage.started` names
the stage currently running. A `stage.started` with no matching `.done` on the next receipt means
the previous attempt died inside that stage without a handshake — the handler fails the job
instead of running it again (spec §2). Interrupted/released jobs clear `stage.started` first.
"""
import json
import shutil
import time
from pathlib import Path

STAGES = ("sfm", "dense", "mesh", "texture", "publish")
_STARTED = "stage.started"


class Checkpoints:
    def __init__(self, work: Path):
        self._work = work

    def started(self, stage: str) -> None:
        self._work.mkdir(parents=True, exist_ok=True)
        (self._work / _STARTED).write_text(stage)

    def done(self, stage: str, **data) -> None:
        self._work.mkdir(parents=True, exist_ok=True)
        (self._work / f"{stage}.done").write_text(json.dumps(data))
        self.clear_started()

    def completed(self, stage: str) -> dict | None:
        p = self._work / f"{stage}.done"
        return json.loads(p.read_text()) if p.exists() else None

    def crashed_stage(self) -> str | None:
        p = self._work / _STARTED
        if not p.exists():
            return None
        stage = p.read_text().strip()
        return None if self.completed(stage) is not None else stage

    def clear_started(self) -> None:
        (self._work / _STARTED).unlink(missing_ok=True)

    def first_incomplete(self) -> str:
        for stage in STAGES:
            if self.completed(stage) is None:
                return stage
        return STAGES[-1]


def sweep_stale(root: Path, max_age_seconds: int = 86_400, now: float | None = None) -> list[Path]:
    """Delete job directories under `root` whose newest file is older than `max_age_seconds`."""
    now = time.time() if now is None else now
    removed = []
    if not root.exists():
        return removed
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        newest = max([d.stat().st_mtime] + [f.stat().st_mtime for f in d.rglob("*")])
        if now - newest > max_age_seconds:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d)
    return removed
```

- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git add pipeline/checkpoints.py tests/test_checkpoints.py && git commit -m "feat(worker): stage checkpoints and stale-scratch sweep"`.

---

### Task 5: Photo orientation normalisation

**Files:**
- Create: `photogrammetry-worker/pipeline/photos.py`
- Create: `photogrammetry-worker/tests/test_photos.py`

**Interfaces (produces):**

```python
@dataclass(frozen=True)
class PhotoReport:
    usable: int
    rotated: list[str]     # file names rotated 90° to match the majority
    skipped: list[str]     # file names moved to work/skipped (different resolution)
    def warnings(self) -> list[str]
def normalise(images: Path, skipped_dir: Path) -> PhotoReport
```

- [ ] **Step 1: Write the failing tests**

```python
"""Photos must share one pixel size for COLMAP's single-camera model: honour EXIF orientation,
rotate the auto-rotated minority, set aside anything else."""
from PIL import Image

from pipeline.photos import PhotoReport, normalise

ORIENTATION = 0x0112


def jpeg(path, size, orientation=None, focal=None):
    im = Image.new("RGB", size, (120, 120, 120))
    exif = im.getexif()
    if orientation: exif[ORIENTATION] = orientation
    if focal: exif[0x920A] = focal                     # FocalLength, what COLMAP's prior reads
    im.save(path, quality=90, exif=exif.tobytes())


def sizes(d):
    return {p.name: Image.open(p).size for p in sorted(d.iterdir())}


def test_minority_orientation_is_rotated_to_match(tmp_path):
    imgs = tmp_path / "images"; imgs.mkdir()
    for i in range(1, 5): jpeg(imgs / f"{i:04d}.jpg", (300, 400))
    jpeg(imgs / "0005.jpg", (400, 300)); jpeg(imgs / "0006.jpg", (400, 300))
    r = normalise(imgs, tmp_path / "skipped")
    assert r == PhotoReport(usable=6, rotated=["0005.jpg", "0006.jpg"], skipped=[])
    assert set(sizes(imgs).values()) == {(300, 400)}
    assert r.warnings() == ["2 photos were rotated to match the others (phone auto-rotate)"]


def test_exif_orientation_is_baked_before_comparing(tmp_path):
    imgs = tmp_path / "images"; imgs.mkdir()
    for i in range(1, 4): jpeg(imgs / f"{i:04d}.jpg", (300, 400))
    jpeg(imgs / "0004.jpg", (400, 300), orientation=6)   # stored landscape, displays portrait
    r = normalise(imgs, tmp_path / "skipped")
    assert r.rotated == [] and r.skipped == [] and r.usable == 4
    assert Image.open(imgs / "0004.jpg").size == (300, 400)
    assert Image.open(imgs / "0004.jpg").getexif().get(ORIENTATION, 1) == 1


def test_focal_length_exif_survives_rewrite(tmp_path):
    imgs = tmp_path / "images"; imgs.mkdir()
    for i in range(1, 4): jpeg(imgs / f"{i:04d}.jpg", (300, 400), focal=4.25)
    jpeg(imgs / "0004.jpg", (400, 300), focal=4.25)
    normalise(imgs, tmp_path / "skipped")
    assert float(Image.open(imgs / "0004.jpg").getexif()[0x920A]) == 4.25


def test_other_resolutions_are_set_aside(tmp_path):
    imgs = tmp_path / "images"; imgs.mkdir()
    for i in range(1, 4): jpeg(imgs / f"{i:04d}.jpg", (300, 400))
    jpeg(imgs / "odd.jpg", (200, 200))
    r = normalise(imgs, tmp_path / "skipped")
    assert r.skipped == ["odd.jpg"] and r.usable == 3
    assert not (imgs / "odd.jpg").exists() and (tmp_path / "skipped" / "odd.jpg").exists()
    assert r.warnings() == ["1 photo has a different resolution and was skipped: odd.jpg"]


def test_untouched_photos_are_not_rewritten(tmp_path):
    imgs = tmp_path / "images"; imgs.mkdir()
    for i in range(1, 4): jpeg(imgs / f"{i:04d}.jpg", (300, 400))
    before = (imgs / "0001.jpg").read_bytes()
    normalise(imgs, tmp_path / "skipped")
    assert (imgs / "0001.jpg").read_bytes() == before


def test_png_is_handled(tmp_path):
    imgs = tmp_path / "images"; imgs.mkdir()
    for i in range(1, 4): Image.new("RGB", (300, 400)).save(imgs / f"{i}.png")
    Image.new("RGB", (400, 300)).save(imgs / "4.png")
    r = normalise(imgs, tmp_path / "skipped")
    assert r.rotated == ["4.png"] and Image.open(imgs / "4.png").size == (300, 400)
```

- [ ] **Step 2: Run** → `ModuleNotFoundError: pipeline.photos`.

- [ ] **Step 3: Implement** `pipeline/photos.py`:

```python
"""Make every photo the same pixel size before COLMAP.

COLMAP reads raw bitmaps (EXIF orientation ignored) and, with `--ImageReader.single_camera 1`,
silently drops any image whose size differs (`CAMERA_SINGLE_DIM_ERROR`). Phones auto-rotate: a
few landscape frames in a portrait set is the common case. Rotating those 90° keeps the same
camera (same focal, centred principal point) — structure-from-motion does not care about roll.
"""
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

_ORIENTATION = 0x0112


@dataclass(frozen=True)
class PhotoReport:
    usable: int
    rotated: list[str]
    skipped: list[str]

    def warnings(self) -> list[str]:
        out = []
        if self.rotated:
            n = len(self.rotated)
            out.append(f"{n} photo{'s were' if n != 1 else ' was'} rotated to match the others (phone auto-rotate)")
        if self.skipped:
            n = len(self.skipped)
            names = ", ".join(self.skipped[:5]) + ("…" if n > 5 else "")
            out.append(f"{n} photo{'s have' if n != 1 else ' has'} a different resolution and "
                       f"{'were' if n != 1 else 'was'} skipped: {names}")
        return out


def _save(im: Image.Image, path: Path, exif) -> None:
    exif[_ORIENTATION] = 1
    kwargs = {"exif": exif.tobytes()}
    if path.suffix.lower() in (".jpg", ".jpeg"):
        kwargs["quality"] = 95
    im.save(path, **kwargs)


def normalise(images: Path, skipped_dir: Path) -> PhotoReport:
    files = sorted(p for p in images.iterdir() if p.is_file())
    sizes: dict[Path, tuple[int, int]] = {}
    for p in files:
        with Image.open(p) as im:
            exif = im.getexif()
            if exif.get(_ORIENTATION, 1) != 1:
                upright = ImageOps.exif_transpose(im)
                _save(upright, p, exif)
                sizes[p] = upright.size
            else:
                sizes[p] = im.size
    if not sizes:
        return PhotoReport(0, [], [])
    majority = Counter(sizes.values()).most_common(1)[0][0]
    transposed = (majority[1], majority[0])
    rotated, skipped = [], []
    for p, size in sizes.items():
        if size == majority:
            continue
        if size == transposed:
            with Image.open(p) as im:
                exif = im.getexif()
                _save(im.transpose(Image.Transpose.ROTATE_90), p, exif)
            rotated.append(p.name)
        else:
            skipped_dir.mkdir(parents=True, exist_ok=True)
            p.rename(skipped_dir / p.name)
            skipped.append(p.name)
    return PhotoReport(usable=len(sizes) - len(skipped), rotated=rotated, skipped=skipped)
```

Note: the test warning text for one skipped photo is `1 photo has a different resolution and was skipped: odd.jpg`; the spec's `{n} photo(s) …` template is realised by the pluralisation above.

- [ ] **Step 4: Run** → PASS. If `exif_transpose` returns `None` for an image without orientation in your Pillow version, it is only called when the tag ≠ 1, so it always returns an image.
- [ ] **Step 5: Commit** — `git add pipeline/photos.py tests/test_photos.py && git commit -m "feat(worker): normalise photo orientation before COLMAP"`.

---

### Task 6: SQS shell requests the receive count

**Files:**
- Modify: `gpu-worker/gpu_worker/sqs.py:64` (`receive()`)
- Test: `gpu-worker/tests/test_sqs.py`

**Interfaces (produces):** messages passed to handlers carry `message["Attributes"]["ApproximateReceiveCount"]` (a string) when SQS returns it. Helper in `sqs.py`: `def receive_count(message: dict) -> int` → `int(message.get("Attributes", {}).get("ApproximateReceiveCount", 1))`.

- [ ] **Step 1: Write the failing tests** (append to `gpu-worker/tests/test_sqs.py`)

```python
from gpu_worker.sqs import receive_count


def test_receive_requests_receive_count_attribute():
    _, sqs, _ = run([], {})
    assert sqs.receive_message.call_args.kwargs["AttributeNames"] == ["ApproximateReceiveCount"]


def test_receive_count_defaults_to_one():
    assert receive_count({"Body": "{}"}) == 1
    assert receive_count({"Body": "{}", "Attributes": {"ApproximateReceiveCount": "3"}}) == 3
```

- [ ] **Step 2: Run** — `cd gpu-worker && uv run pytest tests/test_sqs.py -q` → ImportError.
- [ ] **Step 3: Implement** in `gpu_worker/sqs.py`:

```python
def receive_count(message: dict) -> int:
    """SQS's ApproximateReceiveCount for this message; 1 when the attribute is absent (tests, old shells)."""
    return int(message.get("Attributes", {}).get("ApproximateReceiveCount", 1))
```

and in `receive()`: `sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=20, AttributeNames=["ApproximateReceiveCount"])`.

- [ ] **Step 4: Run** — `uv run pytest -q` in `gpu-worker/` → PASS (transcription worker is unaffected; it ignores the attribute).
- [ ] **Step 5: Commit** — `git commit -am "feat(gpu-worker): expose ApproximateReceiveCount to handlers"`.

---

### Task 7: Handler — resumable stage table with the mesh budget

**Files:**
- Modify: `photogrammetry-worker/handlers/photogrammetry.py`
- Modify: `photogrammetry-worker/models.py` (add `warnings`)
- Test: `photogrammetry-worker/tests/test_handler.py`

**Interfaces:**
- Consumes: Tasks 1–5 (`Reconstruction.reconstruct_mesh/refine_mesh/texture`, `Checkpoints`, `normalise`, `PhotoReport`).
- Produces: `process_photogrammetry_job(body: dict, deps: Deps, receive_count: int = 1) -> None`; constants `REFINE_MAX_FACES`, `FACE_BUDGET`, `MAX_ATTEMPTS`; `models.PhotogrammetryJob.warnings: Mapped[Optional[list]]` (JSONB).

This task rewrites the handler once, with all behaviours; the tests below are grouped so each behaviour has its own test. Write all tests first, run (many fail), implement, run (all pass).

- [ ] **Step 1: Update the test fakes** in `tests/test_handler.py`

Replace `FakeRecon` with:

```python
class FakeRecon:
    """Records stage calls; `registered` drives the threshold; `fail_at` raises in that stage;
    `faces` is what ReconstructMesh reports (RefineMesh reports 2×)."""
    def __init__(self, work, registered=10, fail_at=None, interrupt_at=None, faces=1000):
        self.work, self.registered, self.fail_at, self.interrupt_at, self.faces = work, registered, fail_at, interrupt_at, faces
        self.calls = []

    def _step(self, name):
        self.calls.append(name)
        if name == self.interrupt_at: raise Interrupted()
        if name == self.fail_at: raise StageError("tool", f"{name} exploded")

    def sfm(self, images):
        self._step("sfm"); return SparseModel(self.work / "sparse" / "0", self.registered)
    def dense(self, images, model):
        self._step("dense"); d = self.work / "dense"; d.mkdir(parents=True, exist_ok=True); return d
    def reconstruct_mesh(self, dense):
        self._step("mesh"); return dense / "m.ply", self.faces
    def refine_mesh(self, dense, ply):
        self._step("refine"); return dense / "r.ply", self.faces * 2
    def texture(self, dense, ply, decimate=None):
        self._step(("texture", decimate))
        Image.new("RGB", (2, 2)).save(dense / "tex.png")
        (dense / "scene_textured.mtl").write_text("newmtl m\nmap_Kd tex.png\n")
        obj = dense / "scene_textured.obj"
        obj.write_text("mtllib scene_textured.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nusemtl m\nf 1/1 2/2 3/3\n")
        return obj
```

In `make()`, add `warnings=None` to the `MagicMock(...)` job, and make `FakeS3.download` write a **portrait** image `Image.new("RGB", (600, 800))` so `normalise` sees one size. Update the existing tests:

- `test_happy_path…`: `assert recons[0].calls == ["sfm", "dense", "mesh", "refine", ("texture", None)]`.
- `test_refine_skipped_over_100_images`: `assert "refine" not in recons[0].calls and ("texture", None) in recons[0].calls`.
- `test_stage_progression_is_written_before_each_stage`: `seen == ["sfm", "dense", "mesh", "mesh", "texture"]` (refine runs inside the mesh stage).

- [ ] **Step 2: Add the new tests**

```python
from pipeline.checkpoints import Checkpoints
from handlers.photogrammetry import FACE_BUDGET, MAX_ATTEMPTS, REFINE_MAX_FACES

CRASH = "Reconstruction crashed during the {} stage (probably out of memory) — try fewer photos or one object per scan."


def work_dir(deps, job):
    return deps.work_root / str(job.id)


# ── mesh budget ──────────────────────────────────────────────────────────────

def test_refine_skipped_when_reconstructed_mesh_is_large(tmp_path):
    job, _, recons, deps = make(tmp_path, recon_kwargs={"faces": REFINE_MAX_FACES + 1})
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert "refine" not in recons[0].calls and job.status == "complete"


def test_over_budget_mesh_is_decimated_with_warning(tmp_path):
    faces = 1_261_288
    job, _, recons, deps = make(tmp_path, recon_kwargs={"faces": faces})
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    (_, ratio), = [c for c in recons[0].calls if isinstance(c, tuple) and c[0] == "texture"]
    assert ratio == pytest.approx(FACE_BUDGET / faces)
    assert job.warnings == [f"Mesh simplified from {faces:,} to about {FACE_BUDGET:,} faces to fit the viewer"]


def test_budget_applies_to_refined_face_count(tmp_path):
    job, _, recons, deps = make(tmp_path, recon_kwargs={"faces": 300_000})   # refine → 600k > budget
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert "refine" in recons[0].calls
    (_, ratio), = [c for c in recons[0].calls if isinstance(c, tuple) and c[0] == "texture"]
    assert ratio == pytest.approx(FACE_BUDGET / 600_000)


# ── checkpoints / resume ─────────────────────────────────────────────────────

def test_stage_markers_written_and_scratch_removed_on_complete(tmp_path):
    job, _, recons, deps = make(tmp_path)
    seen = {}
    orig = FakeRecon._step
    FakeRecon._step = lambda self, name: (seen.__setitem__(name if isinstance(name, str) else name[0],
                                                          sorted(p.name for p in work_dir(deps, job).glob("*.done"))), orig(self, name))
    try:
        process_photogrammetry_job({"job_id": str(job.id)}, deps)
    finally:
        FakeRecon._step = orig
    assert seen["dense"] == ["sfm.done"] and seen["mesh"] == ["dense.done", "sfm.done"]
    assert seen["texture"] == ["dense.done", "mesh.done", "sfm.done"]
    assert not work_dir(deps, job).exists()


def test_resume_skips_completed_stages_and_reuses_outputs(tmp_path):
    job, _, recons, deps = make(tmp_path, status="processing")
    w = work_dir(deps, job); (w / "dense").mkdir(parents=True)
    ck = Checkpoints(w)
    ck.done("sfm", sparse=str(w / "sparse" / "0"), registered_images=10)
    ck.done("dense", dense=str(w / "dense"))
    ck.done("mesh", ply=str(w / "dense" / "m.ply"), faces=1000)
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert recons[0].calls == [("texture", None)]
    assert job.status == "complete"


def test_resume_sets_db_stage_to_first_stage_run(tmp_path):
    job, _, _, deps = make(tmp_path, status="processing")
    w = work_dir(deps, job); Checkpoints(w).done("sfm", sparse="s", registered_images=10)
    stages = []
    orig = FakeRecon._step
    FakeRecon._step = lambda self, name: (stages.append(job.stage), orig(self, name))
    try:
        process_photogrammetry_job({"job_id": str(job.id)}, deps)
    finally:
        FakeRecon._step = orig
    assert stages[0] == "dense"


def test_fetch_always_reruns_but_warnings_do_not_duplicate(tmp_path):
    job, s3, _, deps = make(tmp_path, status="processing")
    job.warnings = ["1 photo was rotated to match the others (phone auto-rotate)"]
    w = work_dir(deps, job); Checkpoints(w).done("sfm", sparse="s", registered_images=10)

    def download(key, dest):   # one landscape frame among portrait ones
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (800, 600) if key.endswith("0001.jpg") else (600, 800)).save(dest)
    s3.download = download
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.warnings == ["1 photo was rotated to match the others (phone auto-rotate)"]


# ── the no-cycling rule ──────────────────────────────────────────────────────

def test_crashed_stage_fails_without_running_anything(tmp_path):
    job, _, recons, deps = make(tmp_path, status="processing")
    w = work_dir(deps, job); ck = Checkpoints(w)
    ck.done("sfm", sparse="s", registered_images=10); ck.done("dense", dense="d"); ck.started("mesh")
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert recons == [] and job.status == "failed" and job.stage is None
    assert job.error_message == CRASH.format("mesh")
    assert not w.exists()


def test_crash_in_publish_reads_as_export(tmp_path):
    job, _, recons, deps = make(tmp_path, status="processing")
    w = work_dir(deps, job); ck = Checkpoints(w)
    for s, d in (("sfm", {"sparse": "s", "registered_images": 10}), ("dense", {"dense": "d"}),
                 ("mesh", {"ply": "p", "faces": 1}), ("texture", {"obj": "o"})):
        ck.done(s, **d)
    ck.started("publish")
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "failed" and job.error_message == CRASH.format("export")


def test_receive_count_over_max_attempts_fails(tmp_path):
    job, _, recons, deps = make(tmp_path, status="processing")
    process_photogrammetry_job({"job_id": str(job.id)}, deps, receive_count=MAX_ATTEMPTS + 1)
    assert recons == [] and job.status == "failed"
    assert job.error_message == "Reconstruction crashed repeatedly (probably out of memory) — try fewer photos or one object per scan."


def test_receive_count_at_max_attempts_still_runs(tmp_path):
    job, _, recons, deps = make(tmp_path, status="processing")
    process_photogrammetry_job({"job_id": str(job.id)}, deps, receive_count=MAX_ATTEMPTS)
    assert job.status == "complete"


def test_interrupted_clears_started_and_keeps_scratch(tmp_path):
    job, _, _, deps = make(tmp_path, recon_kwargs={"interrupt_at": "dense"})
    with pytest.raises(Interrupted):
        process_photogrammetry_job({"job_id": str(job.id)}, deps)
    w = work_dir(deps, job)
    assert job.status == "queued" and w.exists()
    assert Checkpoints(w).crashed_stage() is None and Checkpoints(w).completed("sfm") is not None


def test_stage_error_removes_scratch(tmp_path):
    job, _, _, deps = make(tmp_path, recon_kwargs={"fail_at": "dense"})
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "failed" and not work_dir(deps, job).exists()


def test_transient_s3_error_keeps_scratch_for_redelivery(tmp_path):
    job, _, _, deps = make(tmp_path, s3_cls=FailingDownloadS3)
    with pytest.raises(ClientError):
        process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "processing" and work_dir(deps, job).exists()


# ── photos + warnings ────────────────────────────────────────────────────────

def test_rotated_photos_warn_and_count_as_usable(tmp_path):
    job, s3, recons, deps = make(tmp_path, image_count=10, recon_kwargs={"registered": 6})

    def download(key, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (800, 600) if key.endswith(("0009.jpg", "0010.jpg")) else (600, 800)).save(dest)
    s3.download = download
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "complete"
    assert job.warnings[0] == "2 photos were rotated to match the others (phone auto-rotate)"


def test_skipped_photos_lower_the_registration_denominator(tmp_path):
    # 10 uploaded, 2 skipped → 8 usable → ceil(0.6*8)=5 needed; 5 registered passes
    job, s3, _, deps = make(tmp_path, image_count=10, recon_kwargs={"registered": 5})

    def download(key, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 100) if key.endswith(("0009.jpg", "0010.jpg")) else (600, 800)).save(dest)
    s3.download = download
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "complete"
    assert job.warnings == ["2 photos have a different resolution and were skipped: 0009.jpg, 0010.jpg"]


def test_too_few_usable_photos_fails(tmp_path):
    job, s3, _, deps = make(tmp_path, image_count=6)

    def download(key, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 100) if key.endswith(("0005.jpg", "0006.jpg")) else (600, 800)).save(dest)
    s3.download = download
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "failed" and job.error_message == "Only 4 photos could be used — at least 5 are needed"


def test_fresh_start_clears_old_warnings(tmp_path):
    job, _, _, deps = make(tmp_path)
    job.warnings = ["stale"]
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.warnings == []


def test_warnings_are_written_as_they_arise(tmp_path):
    faces = 900_000
    job, _, _, deps = make(tmp_path, recon_kwargs={"faces": faces})
    seen = []
    orig = FakeRecon._step
    FakeRecon._step = lambda self, name: (seen.append((name, list(job.warnings or []))), orig(self, name))
    try:
        process_photogrammetry_job({"job_id": str(job.id)}, deps)
    finally:
        FakeRecon._step = orig
    texture_entry = [w for n, w in seen if isinstance(n, tuple) and n[0] == "texture"][0]
    assert texture_entry and texture_entry[0].startswith("Mesh simplified")
```

- [ ] **Step 3: Run** — `uv run pytest tests/test_handler.py -q` → many FAIL (`AttributeError: 'FakeRecon' object has no attribute 'mesh'`, missing imports).

- [ ] **Step 4: Implement** — replace `handlers/photogrammetry.py` with:

```python
"""One photogrammetry job: fetch → sfm → dense → mesh → texture → publish.

Resumable: every stage leaves a `<stage>.done` marker in the job's scratch directory (a host-path
volume — see infra) and a restarted job skips what is already done. A stage that was *started*
and never finished means the previous attempt died inside it (OOM, kill) — the job fails at once
rather than running the same stage into the same wall (spec §2). Failure mapping otherwise as
before: StageError/JobTimeout/any Exception → row `failed`, return normally (the SQS shell acks).
Interrupted → row back to `queued`, re-raise (not acked; the SpotWatcher already released the
message). Transient S3 → row left `processing`, re-raise (redelivery re-runs fetch).
"""
import logging
import math
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from botocore.exceptions import BotoCoreError, ClientError

from gpu_worker.sqs import Interrupted
from models import PhotogrammetryJob
from pipeline.checkpoints import Checkpoints
from pipeline.export import make_preview, obj_to_glb
from pipeline.photos import normalise
from pipeline.runner import StageError

logger = logging.getLogger(__name__)

RESTARTABLE = ("queued", "processing")
REGISTRATION_MIN_FRACTION = 0.6
REFINE_MAX_IMAGES = 100
REFINE_MAX_FACES = 400_000   # RefineMesh roughly doubles faces at a ~16 GB virtual peak on 675 k
FACE_BUDGET = 500_000        # texture/export never see more than this
MAX_ATTEMPTS = 3             # SQS receives; matches the queue's maxReceiveCount
MIN_IMAGES = 5
ERROR_MAX_CHARS = 1000
_STAGE_NAMES = {"publish": "export"}


@dataclass
class Deps:
    session_factory: Callable
    s3: object
    reconstruction_factory: Callable[[Path, float], object]   # (work_dir, deadline_monotonic) -> Reconstruction
    work_root: Path
    use_gpu: bool
    job_timeout_seconds: int
    clock: Callable[[], float] = field(default=time.monotonic)


def _update(deps: Deps, job_id: uuid.UUID, **values) -> None:
    with deps.session_factory() as s:
        job = s.get(PhotogrammetryJob, job_id)
        if job is None:
            return
        for k, v in values.items():
            setattr(job, k, v)


def _crash_message(stage: str | None) -> str:
    if stage is None:
        return "Reconstruction crashed repeatedly (probably out of memory) — try fewer photos or one object per scan."
    return (f"Reconstruction crashed during the {_STAGE_NAMES.get(stage, stage)} stage (probably out of memory)"
            " — try fewer photos or one object per scan.")


class _Warnings:
    """Job warnings, written to the row on every append; a string is never added twice."""
    def __init__(self, deps: Deps, job_id: uuid.UUID, existing: list[str] | None):
        self._deps, self._job_id, self._items = deps, job_id, list(existing or [])

    def add(self, *messages: str) -> None:
        new = [m for m in messages if m not in self._items]
        if not new:
            return
        self._items.extend(new)
        _update(self._deps, self._job_id, warnings=list(self._items))


def process_photogrammetry_job(body: dict, deps: Deps, receive_count: int = 1) -> None:
    job_id = uuid.UUID(body["job_id"])
    work = deps.work_root / str(job_id)
    ck = Checkpoints(work)

    with deps.session_factory() as s:
        job = s.get(PhotogrammetryJob, job_id)
        if job is None or job.status not in RESTARTABLE:
            logger.info("Job %s skipped (status=%s)", job_id, getattr(job, "status", None))
            return
        user_id, input_prefix, image_count = job.user_id, job.input_prefix, job.image_count
        resuming = ck.first_incomplete() != "sfm"      # markers, not status: a queued (interrupted) job resumes too
        crashed = ck.crashed_stage()
        if crashed is not None or receive_count > MAX_ATTEMPTS:
            reason = _crash_message(crashed)             # None → the "repeatedly" wording
            logger.error("Job %s failed before running: %s (receive_count=%d)", job_id, reason, receive_count)
            job.status, job.stage, job.error_message = "failed", None, reason
            shutil.rmtree(work, ignore_errors=True)
            return
        first_stage = ck.first_incomplete()
        job.status, job.error_message = "processing", None
        job.stage = "texture" if first_stage == "publish" else first_stage
        if not resuming:
            job.warnings = []
        warnings = _Warnings(deps, job_id, job.warnings)

    images = work / "images"
    output_prefix = f"photogrammetry/{user_id}/{job_id}/output/"
    try:
        work.mkdir(parents=True, exist_ok=True)      # exists from here on, even if fetch raises
        # ── fetch (always) ────────────────────────────────────────────────
        # S3 "folders" are placeholder zero-byte objects with a trailing "/" — not photos.
        keys = [key for key in deps.s3.list_keys(input_prefix) if not key.endswith("/")]
        if len(keys) < image_count:
            raise StageError("fetch", f"{len(keys)} of {image_count} photos found in storage")
        for key in keys:
            deps.s3.download(key, images / key.rsplit("/", 1)[-1])
        report = normalise(images, work / "skipped")
        warnings.add(*report.warnings())
        if report.usable < MIN_IMAGES:
            raise StageError("fetch", f"Only {report.usable} photos could be used — at least {MIN_IMAGES} are needed")

        recon = deps.reconstruction_factory(work, deps.clock() + deps.job_timeout_seconds)

        # ── sfm ───────────────────────────────────────────────────────────
        done = ck.completed("sfm")
        if done is None:
            ck.started("sfm")
            model = recon.sfm(images)
            needed = math.ceil(REGISTRATION_MIN_FRACTION * report.usable)
            if model.registered_images < needed:
                raise StageError("colmap mapper",
                                 f"Only {model.registered_images} of {report.usable} photos could be matched — add overlap and try again")
            ck.done("sfm", sparse=str(model.path), registered_images=model.registered_images)
            done = ck.completed("sfm")
        from pipeline.colmap import SparseModel
        model = SparseModel(Path(done["sparse"]), done["registered_images"])

        # ── dense ─────────────────────────────────────────────────────────
        done = ck.completed("dense")
        if done is None:
            _update(deps, job_id, stage="dense"); ck.started("dense")
            dense = recon.dense(images, model)
            ck.done("dense", dense=str(dense)); done = ck.completed("dense")
        dense = Path(done["dense"])

        # ── mesh (reconstruct, optionally refine) ─────────────────────────
        done = ck.completed("mesh")
        if done is None:
            _update(deps, job_id, stage="mesh"); ck.started("mesh")
            ply, faces = recon.reconstruct_mesh(dense)
            if image_count <= REFINE_MAX_IMAGES and faces <= REFINE_MAX_FACES:
                ply, faces = recon.refine_mesh(dense, ply)
            ck.done("mesh", ply=str(ply), faces=faces); done = ck.completed("mesh")
        mesh_ply, faces = Path(done["ply"]), int(done["faces"])

        # ── texture ───────────────────────────────────────────────────────
        done = ck.completed("texture")
        if done is None:
            _update(deps, job_id, stage="texture"); ck.started("texture")
            decimate = None
            if faces > FACE_BUDGET:
                decimate = FACE_BUDGET / faces
                warnings.add(f"Mesh simplified from {faces:,} to about {FACE_BUDGET:,} faces to fit the viewer")
            obj = recon.texture(dense, mesh_ply, decimate=decimate)
            ck.done("texture", obj=str(obj)); done = ck.completed("texture")
        obj = Path(done["obj"])

        # ── publish (export + upload + complete) ──────────────────────────
        ck.started("publish")
        glb = obj_to_glb(obj, work / "mesh.glb")
        first_image = sorted(images.iterdir())[0]
        preview = make_preview(first_image, work / "preview.png")
        mesh_key, preview_key = output_prefix + "mesh.glb", output_prefix + "preview.png"
        deps.s3.upload_file(glb, mesh_key, "model/gltf-binary")
        deps.s3.upload_file(preview, preview_key, "image/png")
        _update(deps, job_id, status="complete", stage=None, mesh_s3_key=mesh_key, preview_s3_key=preview_key,
                completed_at=datetime.now(timezone.utc))
        logger.info("Job %s complete", job_id)
        shutil.rmtree(work, ignore_errors=True)
    except Interrupted:
        logger.warning("Job %s interrupted — back to queued", job_id)
        ck.clear_started()                       # stopped, not crashed: the next worker resumes
        _update(deps, job_id, status="queued", stage=None)
        raise
    except (ClientError, BotoCoreError):
        # Transient S3 (e.g. SlowDown) — leave the row `processing` and re-raise so the SQS
        # shell doesn't ack; redelivery re-runs fetch and resumes from the markers.
        logger.warning("Job %s hit a transient S3 error — leaving for redelivery", job_id, exc_info=True)
        ck.clear_started()
        raise
    except Exception as e:   # StageError, JobTimeout, anything else deterministic
        message = str(e)[:ERROR_MAX_CHARS] or e.__class__.__name__
        logger.error("Job %s failed: %s", job_id, message, exc_info=not isinstance(e, StageError))
        _update(deps, job_id, status="failed", stage=None, error_message=message)
        shutil.rmtree(work, ignore_errors=True)
```

Move the `SparseModel` import to the top with the other imports (it is shown inline above only to keep the diff readable). In `models.py` add:

```python
from sqlalchemy.dialects.postgresql import JSONB, UUID
...
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    warnings: Mapped[Optional[list]] = mapped_column(JSONB)
```

- [ ] **Step 5: Run** — `uv run pytest -q` (whole worker) → all PASS. Expect ≈ 75 tests.

- [ ] **Step 6: Commit** — `git add -A photogrammetry-worker && git commit -m "feat(worker): resumable stages, no-cycling rule, mesh budget, photo warnings"`.

---

### Task 8: Wire `main.py` (receive count, sweep)

**Files:**
- Modify: `photogrammetry-worker/main.py`
- Test: `photogrammetry-worker/tests/test_main.py`

**Interfaces:** consumes `gpu_worker.sqs.receive_count`, `pipeline.checkpoints.sweep_stale`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_main.py`)

```python
def test_handler_passes_receive_count(monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "process_photogrammetry_job", lambda body, deps, receive_count=1: seen.update(rc=receive_count))
    main.HANDLERS["photogrammetry_job"]({"job_id": "x"}, {"Attributes": {"ApproximateReceiveCount": "2"}})
    assert seen["rc"] == 2


def test_run_sweeps_stale_scratch_before_polling(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(main, "sweep_stale", lambda root, **kw: calls.append(root) or [])
    monkeypatch.setattr(main, "run_sqs_worker", lambda **kw: "idle")
    monkeypatch.setattr(main, "GpuSessionStore", lambda *a, **k: object())
    monkeypatch.setattr(main, "task_arn", lambda: "t"); monkeypatch.setattr(main, "instance_id", lambda: "i")
    with patch("main.S3Client"), patch("main.make_session_factory"):
        main.run()
    assert calls == [Path(main.settings.WORK_DIR)]
```

Add `from pathlib import Path` at the top of the test file.

- [ ] **Step 2: Run** → FAIL (`AttributeError: module 'main' has no attribute 'sweep_stale'` / receive_count not passed).

- [ ] **Step 3: Implement** in `main.py`:

```python
from gpu_worker.sqs import receive_count, run_sqs_worker
from pipeline.checkpoints import sweep_stale
...
HANDLERS = {"photogrammetry_job": lambda body, msg: process_photogrammetry_job(body, DEPS, receive_count=receive_count(msg))}


def run() -> None:
    global DEPS
    DEPS = build_deps(settings)
    removed = sweep_stale(Path(settings.WORK_DIR))
    if removed:
        logger.info("Removed %d stale scratch dir(s)", len(removed))
    logger.info("Photogrammetry worker started (…unchanged…)")
    run_sqs_worker(...unchanged...)
```

- [ ] **Step 4: Run** — `uv run pytest -q` → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(worker): pass SQS receive count; sweep stale scratch at start"`.

---

### Task 9: API — `warnings` column, field, mapping

**Files:**
- Create: `chat-api/app/db/migrations/versions/o5p6q7r8s9t0_add_photogrammetry_warnings.py`
- Modify: `chat-api/app/models/photogrammetry.py` (after `error_message`), `chat-api/app/schemas/photogrammetry.py` (`JobStatusResponse`), `chat-api/app/services/photogrammetry_service.py:192-214` (`_to_response`)
- Test: `chat-api/tests/unit/test_photogrammetry_model.py`, `tests/unit/test_photogrammetry_schemas.py`, `tests/unit/services/test_photogrammetry_service.py`

**Interfaces (produces):** `JobStatusResponse.warnings: list[str] = []`; column `photogrammetry_jobs.warnings JSONB NULL`.

- [ ] **Step 1: Write the failing tests**

In `test_photogrammetry_model.py`, add `"warnings"` to the expected column set and:

```python
def test_warnings_column_is_nullable_jsonb():
    import app.models  # noqa: F401
    from sqlalchemy.dialects.postgresql import JSONB
    col = Base.metadata.tables["photogrammetry_jobs"].columns["warnings"]
    assert isinstance(col.type, JSONB) and col.nullable
```

In `test_photogrammetry_schemas.py`:

```python
from datetime import datetime, timezone
from uuid import uuid4
from app.schemas.photogrammetry import JobStatusResponse


def test_status_response_warnings_default_to_empty_list():
    now = datetime.now(timezone.utc)
    r = JobStatusResponse(job_id=uuid4(), name="n", status="queued", image_count=5, created_at=now, updated_at=now)
    assert r.warnings == []
```

In `tests/unit/services/test_photogrammetry_service.py`: add `job.warnings = overrides.get("warnings")` to `make_job()` (after `error_message`; a bare `MagicMock` attribute would otherwise leak through as an empty iterable), then add:

```python
def test_to_response_maps_null_warnings_to_empty_list():
    service = make_service()
    assert service._to_response(make_job(status="queued")).warnings == []
    job = make_job(status="processing", warnings=["Mesh simplified"])
    assert service._to_response(job).warnings == ["Mesh simplified"]
```

- [ ] **Step 2: Run** — `cd chat-api && uv run pytest tests/unit/test_photogrammetry_model.py tests/unit/test_photogrammetry_schemas.py tests/unit/services/test_photogrammetry_service.py -q` → FAIL.

- [ ] **Step 3: Implement**

Migration file:

```python
"""add photogrammetry_jobs.warnings (worker notices shown in the scan view)

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-08-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "o5p6q7r8s9t0"
down_revision: Union[str, None] = "n4o5p6q7r8s9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("photogrammetry_jobs", sa.Column("warnings", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("photogrammetry_jobs", "warnings")
```

Model: `from sqlalchemy.dialects.postgresql import JSONB` and `warnings: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)` after `error_message`.

Schema: `warnings: List[str] = Field(default_factory=list)` after `error_message` in `JobStatusResponse`.

Service `_to_response`: `warnings=list(job.warnings or []),` after `error_message=job.error_message,`.

- [ ] **Step 4: Run** — `uv run pytest tests/unit -q` → PASS.
- [ ] **Step 5: Commit** — `git add -A chat-api && git commit -m "feat(api): photogrammetry job warnings column and field"`.

---

### Task 10: Vue — warnings in the scan view, card glyph, toasts

**Files:**
- Modify: `chat-vue/src/types/index.ts:189-204`, `chat-vue/src/stores/photogrammetry.ts` (`placeholder`, `tick`), `chat-vue/src/components/photogrammetry/ScanDetailView.vue`, `chat-vue/src/components/photogrammetry/ScanJobCard.vue`

No test runner exists for chat-vue; the gate is `npm run type-check && npm run build`.

- [ ] **Step 1: Type** — in `PhotogrammetryJob` add `warnings: string[]` after `error_message`.

- [ ] **Step 2: Run `npm run type-check`** → errors in `placeholder()` (missing `warnings`). Good — that is the failing check.

- [ ] **Step 3: Store** — `placeholder()` adds `warnings: [],`. In `tick()`, before `upsert(updated)`:

```ts
      if (updated) {
        const before = jobs.value.find(j => j.job_id === updated!.job_id)?.warnings.length ?? 0
        updated.warnings.slice(before).forEach(w => pushToast(`"${updated!.name}": ${w}`))
        upsert(updated)
```

- [ ] **Step 4: ScanDetailView** — inside `<div class="flex-1 overflow-auto p-6">`, as the first child (before the `failed` template), add:

```vue
        <ul v-if="job.warnings.length" class="mb-4 space-y-1 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <li v-for="w in job.warnings" :key="w">⚠ {{ w }}</li>
        </ul>
```

- [ ] **Step 5: ScanJobCard** — in the name row, before the `✕` span:

```vue
      <span v-if="job.warnings.length" class="shrink-0 text-xs text-amber-400" :title="job.warnings.join('\n')">⚠</span>
```

- [ ] **Step 6: Run** — `cd chat-vue && npm run type-check && npm run build` → clean. (ESLint is known-broken on a flat-config migration; not a gate.)

- [ ] **Step 7: Commit** — `git add -A chat-vue && git commit -m "feat(vue): show photogrammetry warnings on the scan, card glyph, toasts"`.

---

### Task 11: Terraform — scratch host-path volume

**Files:**
- Modify: `infra/modules/photogrammetry/main.tf` (task definition, lines ~160-195)

- [ ] **Step 1: Edit** — in `resource "aws_ecs_task_definition" "worker"` add, after `task_role_arn`:

```hcl
  # Job scratch lives on the instance, not in the container layer: a worker that is OOM-killed is
  # replaced on the same instance and resumes from its stage markers (spec 2026-08-28 §2).
  volume {
    name      = "scratch"
    host_path = "/var/lib/photogrammetry"
  }
```

and inside the container definition object, after `resourceRequirements`:

```hcl
    mountPoints = [{ sourceVolume = "scratch", containerPath = "/tmp/pg", readOnly = false }]
```

- [ ] **Step 2: Format and validate** — `terraform fmt infra/modules/photogrammetry/main.tf` (that file only) and `cd infra/environments/prod && terraform validate` (needs `terraform init` once; no credentials required for validate).

- [ ] **Step 3: Commit** — `git commit -am "infra(photogrammetry): host-path scratch volume for resumable jobs"`.

Plan/apply is Neil's, from the overlay (see Task 12). Expect the plan to register a new task-definition revision; the API's `RunTask` uses the latest ACTIVE revision, so no other change is needed.

---

### Task 12: Docs — TODO entries and the deploy batch

**Files:**
- Modify: `docs/TODO.md`

- [ ] **Step 1: Add** under the existing sections, in deploy order (spec "Deploy order"):

- *API (chat-api)*: `- [ ] Photogrammetry `warnings` column + field (migration `o5p6q7r8s9t0`). Deploy **first** — the worker writes the column.`
- *Infra (terraform)*: `- [ ] photogrammetry task-def: host-path scratch volume `/var/lib/photogrammetry` → `/tmp/pg` (new revision; overlay plan/apply, then bump the overlay task-def pin).`
- *Worker image*: `- [ ] Photogrammetry robustness (spec 2026-08-28): resumable stages, no-cycling rule, mesh budget (refine ≤ 400 k faces, decimate above 500 k), photo orientation normalisation. **Smoke = sample job + a re-run of the 51-photo set** (expect the rotation warning, no refine, complete). Then bake + pins.`
- *Worker image* (follow-ups, unchecked): `- [ ] Mixed cameras: `--ImageReader.single_camera_per_folder` with one folder per pixel size instead of skipping.`
- *Vue (chat-vue)*: `- [ ] Warnings on the scan view, ⚠ on the card, toasts for new warnings. After the API deploy.`

- [ ] **Step 2: Commit** — `git commit -am "docs: TODO — photogrammetry robustness batch by deploy surface"`.

---

## Self-review

**Spec coverage:** §1 mesh budget → Tasks 1, 2, 3, 7. §2 scratch volume → 11; markers/rules/cleanup/sweep → 4, 7, 8; receive count → 6, 8. §3 photos → 5, 7. §4 warnings DB/worker/API/Vue → 7 (worker model), 9, 10. §5 scaling record-only → no code; the inventory note is in the private cm/aws repo, outside this plan. Deploy order → 12.

**Type consistency:** `Reconstruction.reconstruct_mesh(dense) -> (Path, int)` / `refine_mesh(dense, ply)` / `texture(dense, ply, decimate=None)` are identical in Tasks 2 and 7's `FakeRecon`. `Checkpoints` method names in Task 4 match Task 7's use (`started`, `done`, `completed`, `crashed_stage`, `clear_started`, `first_incomplete`). `receive_count(message)` in Task 6 matches Task 8. `warnings` is `list[str]` in worker model (JSONB list), API schema (`List[str]`), and Vue (`string[]`).

**Known judgement calls (not placeholders):** the crash rule fires on the *first* crash (Neil: "I don't want OOM errors cycling at all"); `MAX_ATTEMPTS` equals the queue's `maxReceiveCount` so the worker always speaks before SQS dead-letters.
