import numpy as np
from clips import read_number
from PIL import Image

from frameripper.export import naming
from frameripper.export.exporter import ExportItem, ExportOptions, export_frames
from frameripper.marks import Marks
from frameripper.video.index import build_index


def test_timecode():
    assert naming.timecode(3723.4567) == "01-02-03-457"
    assert naming.display_timecode(61.5) == "00:01:01.500"


def test_expand_template():
    out = naming.expand(
        "{name}_{time}_f{frame}_{score}", name="clip", frame=42, seconds=1.5, score=87.4
    )
    assert out == "clip_00-00-01-500_f42_87"
    assert naming.expand("{frame:05d}", name="c", frame=7, seconds=0) == "00007"
    assert naming.expand("{bogus}_{frame}", name="c", frame=1, seconds=0) == "{bogus}_1"
    assert naming.expand("a/b:c", name="c", frame=1, seconds=0) == "a_b_c"
    assert naming.expand("", name="c", frame=3, seconds=0) == "c_f3"
    assert naming.expand("{frame", name="c", frame=3, seconds=0) == "{frame"


def test_unique_path(tmp_path):
    (tmp_path / "a.png").touch()
    (tmp_path / "a_1.png").touch()
    assert naming.unique_path(tmp_path, "a", "png").name == "a_2.png"


def test_export_frames(h264_clip, tmp_path):
    index = build_index(h264_clip)
    frames = [150, 3, 77]
    for fmt in ("png", "jpg", "webp", "tiff"):
        opts = ExportOptions(folder=tmp_path / fmt, fmt=fmt, template="f{frame}")
        result = export_frames(index, [ExportItem(f) for f in frames], opts)
        assert not result.errors
        assert sorted(p.name for p in result.paths) == sorted(f"f{f}.{fmt}" for f in frames)
        for f in frames:
            img = np.asarray(Image.open(tmp_path / fmt / f"f{f}.{fmt}").convert("RGB"))
            assert img.shape == (240, 320, 3)
            assert read_number(img) == f


def test_marks():
    m = Marks()
    assert m.toggle(10) is True
    m.set_suggestions([5, 10, 20])
    assert m.suggested == [5, 20]
    assert m.toggle(20) is True
    assert m.marked == [10, 20] and m.suggested == [5]
    assert m.next_after(5) == 10 and m.prev_before(10) == 5
    assert m.next_after(5, include_suggested=False) == 10
    m.accept_all()
    assert m.marked == [5, 10, 20] and m.suggested == []
    assert m.toggle(10) is False
    assert Marks.from_dict({"marked": [1, 999], "suggested": [2]}, 100).to_dict() == {
        "marked": [1],
        "suggested": [2],
    }
