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
    assert data["version"] == 3
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
