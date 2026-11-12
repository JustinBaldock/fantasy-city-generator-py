import json
import math

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from citygen import __version__, export
from citygen.app import MainWindow
from citygen.editing import CityEditor
from citygen.export import ImportError_, city_from_dict, city_to_dict
from citygen.model import Model

OPTIONS = [dict(size=15, seed=7, walls=True, river=True, citadel=True),
           dict(size=24, seed=5, walls=True, home_style="gnome", greens=True,
                orchards=True, fields=True, orchard_ratio=4),
           dict(size=15, seed=2, home_style="classic", walls=True, coast=True,
                temple=True, temples=3, field_ratio=3, fields=True),
           dict(size=9, seed=3, walls=False, hub=False, sea=90, coast=True)]


def through_file(model):
    """The city's data as it comes back from a JSON file."""
    return json.loads(json.dumps(city_to_dict(model)))


def same(a, b):
    """The same city, leaving out what's worked out from the rest, such as
    the ways as drawn, which come out a hair different from rounded points."""
    skip = export._DERIVED
    return {k: v for k, v in a.items() if k not in skip} == {
        k: v for k, v in b.items() if k not in skip}


def edit(model):
    """Move a building, drag a tower, add a corner, take a tower off and
    push the wall out."""
    editor = CityEditor(model)
    building = min(editor.buildings, key=lambda b: math.hypot(b.cx, b.cy))
    editor.begin_move(building)
    for i in range(1, 9):
        editor.drag_to(building, i * 0.5, i * 0.3)
    editor.end_move()
    wall = model.wall
    if wall is None:
        return editor
    tower = next(c for c in wall.towers if c in wall.shape
                 and c not in wall.gates and not editor.is_fixed_corner(c))
    editor.begin_wall_move(tower)
    for i in range(1, 6):
        editor.drag_wall_to(tower, tower.x * 0.02 * i, tower.y * 0.02 * i)
    editor.end_move()
    i = next(i for i, built in enumerate(wall.segments) if built)
    corner = editor.begin_wall_move(
        edge=(wall.shape[i], wall.shape[(i + 1) % len(wall.shape)], 0.5))
    for k in range(1, 5):
        editor.drag_wall_to(corner, corner.x * 0.03 * k, corner.y * 0.03 * k)
    editor.end_move()
    editor.toggle_tower(tower)
    north = max((b for b in editor.buildings if b.ward.patch.within_walls),
                key=lambda b: -b.cy)
    editor.begin_move(north)
    for i in range(1, 15):
        editor.drag_to(north, 0, -i)
    editor.end_move()
    return editor


@pytest.mark.parametrize("options", OPTIONS)
def test_an_untouched_city_comes_back_the_same(options):
    data = through_file(Model(**options))
    model, differences = city_from_dict(data)
    assert differences == []
    assert same(city_to_dict(model), data)


@pytest.mark.parametrize("options", OPTIONS)
def test_an_edited_city_comes_back_with_its_edits(options):
    original = Model(**options)
    edit(original)
    data = through_file(original)
    model, differences = city_from_dict(data)
    assert differences == []
    assert same(city_to_dict(model), data)
    if original.wall is not None:
        assert data["wall"]["added"]
        assert len(model.wall.shape) == len(original.wall.shape)
        assert len(model.wall.towers) == len(original.wall.towers)


def test_an_imported_city_can_be_edited_and_saved_again():
    original = Model(**OPTIONS[0])
    edit(original)
    model, _ = city_from_dict(through_file(original))
    editor = CityEditor(model)
    building = max(editor.buildings, key=lambda b: math.hypot(b.cx, b.cy))
    x, y = building.center()
    assert editor.begin_move(building)
    editor.drag_to(building, 1.0, 0.0)
    editor.end_move()
    assert building.center() != (x, y)
    again, differences = city_from_dict(through_file(model))
    assert differences == []
    assert same(city_to_dict(again), through_file(model))


def test_the_file_says_which_version_made_it(tmp_path):
    path = tmp_path / "city.json"
    export.save_json(Model(9, 3), path)
    data = json.loads(path.read_text())
    assert data["app_version"] == __version__
    _, differences, made_with = export.load_json(path)
    assert made_with == __version__ and differences == []


def test_a_file_from_before_settings_were_saved_is_refused():
    data = through_file(Model(9, 3))
    del data["settings"]
    with pytest.raises(ImportError_, match="older version"):
        city_from_dict(data)


def test_other_json_is_refused(tmp_path):
    path = tmp_path / "other.json"
    path.write_text('{"name": "not a city"}')
    with pytest.raises(ImportError_):
        export.load_json(path)
    path.write_text("not json at all")
    with pytest.raises(ImportError_):
        export.load_json(path)


def test_a_damaged_file_is_refused():
    data = through_file(Model(9, 3))
    data["wards"] = data["wards"][:-2]
    with pytest.raises(ImportError_):
        city_from_dict(data)


@pytest.fixture
def window(qapp, monkeypatch):
    shown = []
    for kind in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, kind,
                            lambda *args, kind=kind: shown.append(
                                (kind, args[2])))
    window = MainWindow()
    window.shown = shown
    window.resize(1000, 800)
    window.show()
    QApplication.processEvents()
    yield window
    window.close()


def test_the_window_opens_a_saved_city_with_its_settings(window, tmp_path):
    original = Model(**OPTIONS[2])
    edit(original)
    path = tmp_path / "town.json"
    export.save_json(original, path)

    assert window.open_json(str(path))
    assert window.shown == []
    assert window.seed_box.value() == 2
    assert window.size_box.value() == 15
    assert window.homes_box.currentData() == "classic"
    assert window.temple_count_box.currentData() == 3
    assert window.field_ratio_box.currentData() == 3
    assert window.temple_box.currentData() is True
    assert same(city_to_dict(window.model), city_to_dict(original))
    # The controls match, so building again gives the same town, unedited.
    assert window.built_state == window._control_state()


def test_the_window_warns_about_a_file_from_another_version(window, tmp_path):
    data = city_to_dict(Model(9, 3))
    data["app_version"] = "0.1.0"
    path = tmp_path / "old.json"
    path.write_text(json.dumps(data))
    assert window.open_json(str(path))
    assert len(window.shown) == 1
    kind, text = window.shown[0]
    assert kind == "information"
    assert "0.1.0" in text and __version__ in text


def test_the_window_reports_a_file_it_cant_open(window, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{}")
    seed = window.model.seed
    assert not window.open_json(str(path))
    assert window.shown and window.shown[0][0] == "warning"
    assert window.model.seed == seed


def test_a_file_from_before_roads_could_be_counted_opens_the_same(window):
    original = Model(9, 3, walls=False, hub=False, sea=90, coast=True)
    data = through_file(original)
    del data["settings"]["roads"]
    model, differences = city_from_dict(data)
    assert differences == [] and len(model.roads) == len(original.roads)


def test_a_file_from_a_newer_version_is_refused():
    data = through_file(Model(9, 3))
    data["version"] += 1
    with pytest.raises(ImportError_, match="newer"):
        city_from_dict(data)
    data = through_file(Model(9, 3))
    data["settings"]["moons"] = 2
    with pytest.raises(ImportError_):
        city_from_dict(data)
