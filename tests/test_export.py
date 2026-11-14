import pytest
import json
import xml.etree.ElementTree as ET

from citygen import export, qt_render
from citygen.layers import PALETTES, build_layers
from citygen.model import Model

SVG = "{http://www.w3.org/2000/svg}"


def walled_city():
    return Model(15, 7, walls=True, citadel=True, plaza=True)


def test_layers_are_named_and_in_drawing_order():
    names = [layer.name for layer in build_layers(walled_city(),
                                                  PALETTES["Default"])]
    assert names.index("Road edges") < names.index("Roads")
    assert names.index("Roads") < names.index("Buildings")
    assert names.index("Buildings") < names.index("City wall")
    assert "Castle wall" in names


def test_svg_is_valid_and_uses_the_palette():
    palette = PALETTES["Blueprint"]
    root = ET.fromstring(export.city_to_svg(walled_city(), palette))
    assert root.tag == SVG + "svg"
    assert root.find(SVG + "rect").get("fill") == "#455b8d"
    groups = {g.get("id") for g in root.findall(SVG + "g")}
    assert {"buildings", "city-wall", "castle-wall"} <= groups


def test_json_round_trips(tmp_path):
    model = walled_city()
    path = tmp_path / "city.json"
    export.save_json(model, path)
    data = json.loads(path.read_text())
    assert data["seed"] == 7
    assert data["version"] == 16
    assert data["wall"]["gates"]
    assert len(data["wards"]) == len(model.patches)


def test_png_is_saved(qapp, tmp_path):
    from PySide6.QtGui import QImage

    path = tmp_path / "city.png"
    qt_render.save_png(walled_city(), PALETTES["Default"], path, 800)
    image = QImage(str(path))
    assert (image.width(), image.height()) == (800, 800)


def test_every_palette_draws(qapp, tmp_path):
    model = walled_city()
    for number, palette in enumerate(PALETTES.values()):
        qt_render.save_png(model, palette, tmp_path / f"{number}.png", 200)


def test_window_builds_and_changes_cities(qapp):
    from citygen.app import MainWindow

    window = MainWindow()
    first = window.model
    window.new_map()
    assert window.model is not first

    window.seed_box.setValue(1234)
    window.size_box.setValue(24)
    window.build()
    assert (window.model.seed, window.model.size) == (1234, 24)

    window.walls_box.setCurrentIndex(1)
    assert window.model.wall is not None

    window.palette_box.setCurrentText("Night")
    assert window.view.palette_colours == PALETTES["Night"]
    window.close()


def test_kept_layers_draw_the_same_as_fresh_ones(qapp):
    from citygen import qt_render
    from citygen.model import Model

    model = Model(15, 5, walls=True, river=True, coast=True, fields=True,
                  forests=True, orchards=True)
    palette = PALETTES["Default"]
    kept = {}
    first = qt_render.prepare(model, palette, kept)
    whole = {key for key in kept if isinstance(key, str) and key != "changed"}
    assert whole <= qt_render.FIXED_LAYERS and "Forest" in kept
    again = qt_render.prepare(model, palette, kept)
    fresh = qt_render.prepare(model, palette)
    assert len(first) == len(again) == len(fresh)
    for (a, *_), (b, *_) in zip(again, fresh):
        assert a == b


def test_scale_bars_use_round_lengths():
    from citygen.layers import METRES_PER_UNIT, scale_bar, scale_label

    metres, size = scale_bar(10.0, 160)
    assert metres == 50
    assert size == pytest.approx(50 / METRES_PER_UNIT * 10)
    assert scale_bar(1.0, 300)[0] == 1000
    assert scale_label(1000) == "1 km"
    assert scale_label(200) == "200 m"


def test_the_svg_has_a_scale_bar_unless_left_out():
    model = walled_city()
    palette = PALETTES["Default"]
    assert 'id="scale-bar"' in export.city_to_svg(model, palette)
    assert 'id="scale-bar"' not in export.city_to_svg(
        model, palette, show_scale_bar=False)


def test_the_png_scale_bar_can_be_left_out(tmp_path, qapp):
    from PySide6.QtGui import QImage

    model = walled_city()
    with_bar = tmp_path / "with.png"
    without = tmp_path / "without.png"
    qt_render.save_png(model, PALETTES["Default"], with_bar, 600)
    qt_render.save_png(model, PALETTES["Default"], without, 600, False)
    assert QImage(str(with_bar)) != QImage(str(without))
