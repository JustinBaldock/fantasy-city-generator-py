# Fantasy City Generator (Python)

A desktop app that generates maps of medieval fantasy towns and cities, written in Python with PySide6.

Pick a size and press Return, and you get a new walled town or sprawling city, with streets, wards, a castle, temples, greens, farm fields, forests, and a coast or river if you want one. Every map comes from a seed, so the same seed and settings always give the same map. It runs on your own computer with no web browser and no account.

This is an unofficial Python port of [TownGeneratorOS](https://github.com/watabou/TownGeneratorOS), the Haxe source code that [Watabou](https://github.com/watabou) released for the [Medieval Fantasy City Generator](https://watabou.itch.io/medieval-fantasy-city-generator). All credit for the generator's design and algorithms goes to Watabou. Please don't send them bug reports for this port.

## Running it

You need Python 3.10 or newer. On a Mac, double-click `Fantasy City Generator.command` in Finder. The first run sets everything up. On any system you can also do it by hand.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m citygen
```

## Using it

- Press Return, or New map, for a new map at the same size.
- Press a size button for a new map of that kind of settlement, or set the number of wards directly, from 6 to 40.
- To get a map back, type its seed and press Return.
- Walls, Castle, Plaza, Temple, Greens, Coast, River, Fields and Forests can each be Random, Yes or No. Changing one rebuilds the same seed.
- Sea to sets the compass bearing of the coast, with 0 for north and 90 for east.
- Roads sets whether every gate has a road, or only two roads lead out of town.
- Homes switches between burgage plots and gnome homes. See below. Changing it keeps the same streets, walls and water.
- Style changes the colours without changing the map.
- Scroll to zoom, drag to pan, and double-click to reset the view.
- Hover over a ward to see what kind it is.

## Plots and burgage plots

Every house stands on its own plot of land, drawn as a property with a border round it.

Homes are burgage plots unless you choose gnome homes. A burgage plot is the medieval town plot, with the house at the front on the street, or on a lane if the plot doesn't reach a street, and a long garden behind for growing food and keeping animals. A plot too cramped for a garden has a cottage that nearly fills it. Administration and Military buildings stand in the middle of their plots, and castles, temples, markets and farms have no plot border.

## Gnome homes

Set Homes to Gnome for a town of gnomes. A gnome home is a hexagon with square rooms built onto some of its straight sides, and a line on the map shows where each room joins the hexagon. Each home has its own plot, and a plot too long for one home is split in two with a lane between.

Not everything is a home. Shops, workshops, warehouses and stores are plain squares and rectangles, mixed in among the homes. About half the plots in a Merchant ward are, and fewer in the others. Administration and Military wards are all rectangles, and each farm gets a home with a barn beside it when the land has space. Castles, temples and markets stay as they are.

Moving, locking and exporting all work the same way. A pushed home moves whole, with its rooms.

## Moving and locking buildings

Turn on Edit buildings, or press `E`, to change a map by hand.

- Click a building to select it, and drag it to move it. Dragging open ground still pans.
- Buildings in the way get pushed aside, and can push others in turn.
- A building moves with its whole plot, and clicking anywhere on the plot selects it.
- To lock a building, right-click it, or select it and press `L` or Lock building. Locked buildings show in red. They can't be moved or pushed, so they stop anything that runs into them. Locking again unlocks.
- City walls give way. A building that reaches a wall bends that stretch into a smooth curve, with its towers and gates. The further it goes the wider the wall swells, so a long drag makes a rounded bulge, and the land it takes in stays empty. Roads are carried along outside the wall and stay joined to their gates, and buildings beyond the wall are moved out of its way.
- The sea and rivers stop buildings, and a dragged building slides along them. Walls that run along water stay put and a bulge won't enter water. A locked building holds a wall back, so the curve tapers off beside it, and a castle wall can't be pushed through the city wall.
- Undo move, or `Cmd`+`Z`, takes back one drag at a time, including any walls it moved. Unlock all clears every lock.

Exports show the moved buildings. Moves aren't saved anywhere else, so export a map to keep it. The app asks first before a change would replace a map you've edited.

## Exporting

- **PNG** at any size from 500 to 16,000 pixels square.
- **SVG** with each kind of feature in its own named group, ready to edit in a vector program.
- **JSON** with the wards, buildings, plots, walls, gates, towers, streets and roads as coordinates. This is this app's own format, not the JSON format of Watabou's site.

## How it differs from the website

This port is based on the source code Watabou published, which stopped being updated years ago. The website has moved on since then.

Coasts, rivers, bridges, piers, farm fields, forests, rounded greens, temple landmarks, plots, burgage plots, gnome homes, the Roads option and curved road drawing aren't in the published source. They are this project's own work, modelled on what the website's maps show, and no code was taken from the website. They won't match it exactly. Water follows the edges between wards, for example, so a river can't cut through the middle of one.

The website's building shadows, district names, grid, compass and scale bar aren't in this app.

The same seed won't give the same map here as on the website. The site's generator has changed since this code was published, and the port also differs from the original in small ways, such as the order roads are searched in.

The Walls, Castle and Plaza options and the exports are also additions in this port. The published source chose those features only from the seed, and could only show the map on screen.

## How it's organised

| File | What it does |
| --- | --- |
| `citygen/rng.py` | The seeded random numbers |
| `citygen/geometry.py` | Points and polygons |
| `citygen/voronoi.py` | The regions that become wards |
| `citygen/cutter.py` | Dividing polygons |
| `citygen/water.py` | Coasts, rivers, bridges and piers |
| `citygen/countryside.py` | Farm fields and forests |
| `citygen/patch.py` | A patch of land, and the outline around a group |
| `citygen/walls.py` | City and castle walls |
| `citygen/topology.py` | The street network and path finding |
| `citygen/wards.py` | The ward types and how they lay out buildings |
| `citygen/model.py` | Building a whole city |
| `citygen/layers.py` | What a map draws, as plain data, and the colour styles |
| `citygen/export.py` | JSON and SVG |
| `citygen/qt_render.py` | Drawing with Qt, and PNG |
| `citygen/editing.py` | Moving and locking buildings |
| `citygen/app.py` | The desktop app |

Everything except `water.py`, `countryside.py` and `editing.py` follows the original's structure, with small additions for the new features. Where the original's behaviour looks like a mistake but shapes the maps, the port keeps it and says so in a comment. `Polygon.distance` is the main example.

To run the tests:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

## Licence

The code is licensed under the GNU General Public License v3.0, the same licence as the original. See [LICENSE](LICENSE).

Watabou's page says the maps from the website can be used however you like, including in commercial RPG adventures, and that attribution is appreciated but not required. The GPL covers this program's code, and doesn't normally extend to what the program produces.
