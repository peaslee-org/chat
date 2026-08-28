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


def test_more_than_five_skipped_names_are_truncated(tmp_path):
    # A comfortable majority of (300, 400) photos so the six differently-sized odd ones (each a
    # distinct size, so none of them can form their own majority) are all skipped, not adopted.
    imgs = tmp_path / "images"; imgs.mkdir()
    for i in range(1, 9): jpeg(imgs / f"{i:04d}.jpg", (300, 400))
    for i, name in enumerate(("a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg", "f.jpg")):
        jpeg(imgs / name, (200 + i * 10, 200 + i * 10))
    r = normalise(imgs, tmp_path / "skipped")
    assert len(r.skipped) == 6 and r.usable == 8
    assert r.warnings()[0].endswith("e.jpg, …")


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


def test_unreadable_file_is_set_aside_with_its_own_warning(tmp_path):
    imgs = tmp_path / "images"; imgs.mkdir()
    for i in range(1, 4): jpeg(imgs / f"{i:04d}.jpg", (300, 400))
    (imgs / "0004.jpg").write_bytes(b"not a jpeg")
    r = normalise(imgs, tmp_path / "skipped")
    assert r.unreadable == ["0004.jpg"] and r.skipped == [] and r.usable == 3
    assert not (imgs / "0004.jpg").exists() and (tmp_path / "skipped" / "0004.jpg").exists()
    assert r.warnings() == ["1 photo could not be read and was skipped: 0004.jpg"]


def test_unreadable_file_does_not_vote_on_orientation(tmp_path):
    imgs = tmp_path / "images"; imgs.mkdir()
    jpeg(imgs / "0001.jpg", (300, 400)); jpeg(imgs / "0002.jpg", (400, 300))
    (imgs / "0000.jpg").write_bytes(b"")
    r = normalise(imgs, tmp_path / "skipped")
    assert r.unreadable == ["0000.jpg"] and r.usable == 2 and len(r.rotated) == 1
