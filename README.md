# Fantasy City Generator (Python)

[![Tests](https://github.com/JustinBaldock/fantasy-city-generator-py/actions/workflows/tests.yml/badge.svg)](https://github.com/JustinBaldock/fantasy-city-generator-py/actions/workflows/tests.yml)

A desktop app that generates maps of medieval fantasy towns and cities, written in Python with PySide6.

Pick a size and press Return, and you get a new walled town or sprawling city, with streets, wards, homes on their own plots, a castle, temples, greens, farmland, forests, and a coast or river if you want one. Every map comes from a seed, so the same seed and settings always give the same map. You can then move buildings and reshape the walls by hand, and export the result. It runs on your own computer with no web browser and no account.

This is an unofficial Python port of [TownGeneratorOS](https://github.com/watabou/TownGeneratorOS), the Haxe source code that [Watabou](https://github.com/watabou) released for the [Medieval Fantasy City Generator](https://watabou.itch.io/medieval-fantasy-city-generator). All credit for the generator's design and algorithms goes to Watabou. Please don't send them bug reports for this port.

## Contents

- [Running it](#running-it)
- [Making a map](#making-a-map)
- [What's on the map](#whats-on-the-map)
- [Editing a map](#editing-a-map)
- [Exporting and importing](#exporting-and-importing)
- [How it differs from the website](#how-it-differs-from-the-website)
- [Fantasy Location Generator](#fantasy-location-generator)
- [For developers](#for-developers)
- [Licence](#licence)

## Running it

You need Python 3.10 or newer. On a Mac, double-click `Fantasy City Generator.command` in Finder. The first run sets everything up. On any system you can also do it by hand.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m citygen
```

The same folder has a second app for single remote places, the [Fantasy Location Generator](#fantasy-location-generator). Double-click `Fantasy Location Generator.command`, or run `.venv/bin/python -m sitegen`.

## Making a map

The controls are down the right of the window, in boxes for the map, the town, the countryside and the style, with the editing and export buttons kept in view below them. Drag the edge between the map and the controls to make the controls wider. If the window is too short for them all, the controls scroll.

### Map size and seed

- Press Return, or New map, for a new map at the same size.
- Press a size button for a new map of that kind of settlement, or set the number of wards directly, from 1 to 40.
- To get a map back, type its seed and press Return.

| Size | Wards |
| --- | --- |
| Hamlet | 1 or 2 |
| Village | 3 to 5 |
| Small Town | 6 to 9 |
| Large Town | 10 to 14 |
| Small City | 15 to 23 |
| Large City | 24 to 39 |
| Metropolis | 40 |

A hamlet is a farm or two. Its one or two wards hold a few houses, with farmsteads, fields and orchards round them, and it is laid out on as much land as a small town so there is countryside to farm. Hamlets have no plaza, since it would take their only ward, and a hamlet's castle is more of a manor, with its gate opening onto the houses.

### Town and countryside options

Changing any option rebuilds the same seed, so you can see what each one does to the same town. Most can be Random, Yes or No, and Random leaves the choice to the seed.

| Town | What it does |
| --- | --- |
| Homes | Burgage plots, gnome homes or classic houses |
| Walls | A city wall with towers and gates |
| Castle | A walled castle, joined to the city wall when there is one |
| Plaza | An open market square at the centre, from 3 wards up |
| Temple | Temples, with the number beside it setting how many, from 1 to 10 |
| Greens | Parks with trees round their edges |
| Roads | Whether every gate has a road out of town, or only two |

| Countryside | What it does |
| --- | --- |
| Wheat fields | Farmland, with the ratio beside it setting how much |
| Orchards | Orchards, with the ratio beside it setting their share of the farmland |
| Forests | Woods on the higher ground around town |
| River | A river through town, with bridges |
| Coast | The sea along one side of town |
| Sea to | The compass bearing of the coast, with 0 for north and 90 for east |

The number and ratios beside Temple, Wheat fields and Orchards are greyed out when they can't apply, such as with Temple set to No.

### Viewing

- Scroll to zoom, drag to pan, and double-click to reset the view.
- Hover over a ward to see what kind it is.
- Style changes the colours without changing the map.
- A scale bar sits in the bottom left corner. View > Scale bar turns it off, on the map and in exports.

## What's on the map

### Homes

Every house stands on its own plot of land, drawn as a property with a border round it. Homes come in three styles, chosen with Homes. Changing it keeps the same streets, walls and water.

**Burgage plots** are the medieval town plot, and the default. The house stands at the front, on the street, or on a lane if the plot doesn't reach a street, with a long garden behind for growing food and keeping animals. A plot too cramped for a garden has a cottage that nearly fills it, and bigger gardens have a few trees in them. Administration and Military buildings stand in the middle of their plots.

**Gnome homes** are hexagons with square rooms built onto some of their straight sides, and a line shows where each room joins the hexagon. Each home has its own plot, and a plot too long for one home is split in two with a lane between. Not everything is a home. Shops, workshops, warehouses and stores are plain squares and rectangles mixed in among them, about half the plots in a Merchant ward and fewer in the others. Administration and Military wards are all rectangles, and each farm gets a home with a barn beside it when the land has space.

**Classic houses** fill their plots edge to edge, with no gardens or borders, as on the original generator. A classic map is the same as this port gave before plots were added.

Castles, temples, markets and farms have no plot border in any style.

### Roads and streets

- Each road carries on through its gate as the main street to the centre of town.
- The other gaps between wards in town have streets, drawn as single lines. Streets stop at the edge of a road and never cross one.
- A street runs just inside the city wall wherever there's room between the wall and the buildings, such as inside a bulge made by pushing the wall out.
- Roads and streets meet bridges end on, so traffic can cross. A road over the river runs straight across its bridge, streets from a bridge start at its ends, and a bridge end with no way at it gets a short street to the nearest road or street on that bank. Ways otherwise stop at the water's edge.

Roads and streets react to buildings you move. Move a building onto one and it bends smoothly round it, cutting across gardens if it needs to, and it straightens again when the building moves off or the move is undone. Where houses stand close on both sides, as they do along most streets in town, there's no room to bend, and the moved building stands over the way instead. Buildings that haven't been moved never bend a way.

### Walls, castles and temples

The city wall has towers at its corners and gates where the main streets leave town. A castle has its own wall, joined to the city wall where they meet.

The number beside Temple sets how many temples the town has, from 1 to 10. With Temple on Random the seed decides whether there are any, and there are either none or that many. Temples avoid the wards beside another temple where there's room, and a small town gets as many as it has wards for.

### Water

A coast puts the sea along one side of town, with piers along the waterfront. A river runs between the wards rather than through them, since water follows the edges between wards. Where it runs through town it has bridges.

### Countryside

**Wheat fields** are the furrowed farm plots around town, each two to three times the size of an orchard. The ratio beside Wheat fields sets how many there are for each ward of the town, from 4:1 for a farming town to 1:4 for one with very little. Fields take the land nearest the city first, and low ground before hills. The farmland a map usually shows is enough for 1:1 or fewer. A farming town at 4:1, 3:1 or 2:1 takes more, so its map grows to show all of its fields, with forest filling the extra ground.

**Orchards** are farm plots with their trees in neat rows, each with a faint hedge round it. The ratio beside Orchards sets their share of the farmland, 1:10, 1:8 or 1:4, orchard to wheat field by area. They go nearest the farmhouses first, and where an orchard takes the place of a wheat field, the field's land makes two or three orchards. The fields are big, so a map lands near the ratio rather than on it. With Orchards off the farmland is all wheat fields, and with Wheat fields off the orchards take the plots beside farmhouses and the higher farmland near town instead. Turning orchards on or off leaves the other fields where they were.

**Forests** grow on the higher ground around town and keep off the fields, orchards, roads and water. Farms dot the land beyond the town.

### Greens

Greens are open parkland with trees spaced round the inside of their edges, leaving a few gaps.

### Scale

The original generator gives no real size, so this app uses 4 metres for each map unit. At that scale a main street is 8 metres across and a burgage plot about 28 by 48 metres. The scale bar picks a round length, such as 50 metres or 200 metres, to suit the zoom.

## Editing a map

Turn on Edit buildings, or press `E`, to change a map by hand.

### Moving and locking buildings

- Click a building to select it, and drag it to move it. Dragging open ground still pans.
- A building moves with its whole plot, and clicking anywhere on the plot selects it. A green's trees and a gnome home's rooms move with it too.
- Buildings in the way get pushed aside, and can push others in turn.
- To lock a building, right-click it, or select it and press `L` or Lock building. Locked buildings show in red. They can't be moved or pushed, so they stop anything that runs into them. Locking again unlocks, and Unlock all clears every lock.
- The sea and rivers stop buildings, and a dragged building slides along them.
- City walls give way. A building that reaches a wall bends that stretch into a smooth curve, with its towers and gates. The further it goes the wider the wall swells, so a long drag makes a rounded bulge, and the land it takes in stays empty. Roads are carried along outside the wall and stay joined to their gates, and buildings beyond the wall are moved out of its way. Walls that run along water stay put, a bulge won't enter water, a locked building holds a wall back so the curve tapers off beside it, and a castle wall can't be pushed through the city wall.

### Reshaping walls

- Every wall corner you can move has a handle, filled for a tower. Drag a corner, tower or gate to move it, and the wall, the wards beside it and any road from a gate go with it. Buildings in the way are pushed aside.
- Drag a stretch of wall to put a new corner there and pull it out or in.
- Right-click a wall corner to put a tower on it or take one off. Gates don't take towers.
- Corners where a wall meets the water stay put, and a wall can't be dragged into water or across another wall. Buildings pushed by a moving wall stop at the other walls instead of going through them, so a wall dragged into a crowded part of town stops when the buildings can't move.

### Undo and keeping your changes

Undo move, or `Cmd`+`Z`, takes back one change at a time, including any walls a drag moved. Exports show your changes. To keep an edited map and carry on with it later, export it as JSON and import it again. The app asks first before a new map would replace one you've edited.

## Exporting and importing

The File menu exports the map three ways.

- **PNG** at any size from 500 to 16,000 pixels square, with the scale bar unless it's turned off.
- **SVG** with each kind of feature in its own named group, ready to edit in a vector program, and the scale bar unless it's turned off.
- **JSON** with the wards, buildings, plots, walls, gates, towers, streets, roads, fields, orchards and trees as coordinates, including the roads and streets as drawn. It also records the settings the map was made with and the version of the app that made it. This is this app's own format, not the JSON format of Watabou's site.

Import JSON, or `Cmd`+`O`, opens a JSON export again so you can carry on editing it. The app makes the town again from its saved settings, puts back every building you moved, every wall corner you moved or added and every tower you added or took off, and sets the controls to match.

A JSON file records which version of the app made it, and the version shows in the window's title. If you open a file made with a different version, the app says so. The town is made again from its settings, and a newer version may lay it out differently, so moved buildings and walls may not all land where they were. The app also says if any part of the town didn't come back exactly as it was saved. Files exported before version 1.0.0 didn't record their settings and can't be opened.

## How it differs from the website

This port is based on the source code Watabou published, which stopped being updated years ago. The website has moved on since then.

Coasts, rivers, bridges, piers, farm fields, orchards, forests, rounded greens and their trees, temple landmarks and counts, plots, burgage plots, gnome homes, drawn streets, the Roads option, curved road drawing and the scale bar aren't in the published source. They are this project's own work, modelled on what the website's maps show where the site has them, and no code was taken from the website. They won't match it exactly.

Editing buildings and walls, hamlets and villages of fewer than 6 wards, and all the options, are also additions in this port. The published source chose its features only from the seed, and could only show the map on screen.

The website's building shadows, district names, grid and compass aren't in this app.

The same seed won't give the same map here as on the website. The site's generator has changed since this code was published, and the port also differs from the original in small ways, such as the order roads are searched in.

## Fantasy Location Generator

A separate app for one place out in the country: a remote farm, a toll house on a turnpike road, or a roadhouse inn at a crossroads. It draws with the city generator's own styles, so its buildings, roads, fields, orchards, woods and water look just like those round a town. Every piece can then be moved, turned, resized and reshaped, alone or several at once.

```bash
.venv/bin/python -m sitegen
```

### Making a location

Choose a Kind and press Return, or New location, for a new one. The same seed always gives the same location.

| Kind | What it has |
| --- | --- |
| Farm | A farmyard by the road with a farmhouse, shed, barn, byre and well, an orchard behind it, a paddock with a pond, and wheat fields, meadows, hedges and woods all round |
| Toll house | A toll house and its garden beside the road, with a toll gate across the road. Usually the road crosses a river on a bridge there, and otherwise a track joins it |
| Roadhouse | An inn at a crossroads or a junction, round a yard with its stables, coach house and well, a garden with trees next door, sometimes a brewhouse, and a paddock across the road |

Homes sets whether the main house is a plain building or a gnome home. Each location is laid out on a grid of fields whose corners wander, then turned to a random heading. A location is about 400 metres across.

### Editing

Everything on the map is a piece you can change. Hover over one to see what it is.

- **Select** a piece by clicking it. Shift-click (or Ctrl-click, or Cmd-click on a Mac) adds a piece to the selection or takes it off. Drag across open ground to select everything inside the box. Ctrl+A selects everything, and Esc selects nothing.
- **Move** the selection by dragging it, or nudge it with the arrow keys, ten times as far with Shift.
- **Turn** the selection by dragging the round handle above it. Holding Shift snaps to 15 degrees. The [ and ] keys, and the Turn buttons, turn it 15 degrees at a time, and Shift+[ and Shift+] turn it by one degree. Several pieces turn together round their middle.
- **Resize** a single piece by dragging the square handles on its box. The side across from the handle stays put. A tree or well's handles change its size.
- **Reshape** an area such as a field, yard, wood or building with Reshape, R, or by double-clicking it. Its corners then show, ready to drag. Double-click an edge to add a corner, and right-click a corner to remove it. Roads, tracks, rivers, hedges, walls, bridges and gates always show their points, so you can drag their bends straight away, add a bend by double-clicking the line, and remove one with a right click.
- **Add** a piece with the Add buttons. It appears in the middle of the view, selected, ready to move.
- **Delete** the selection with Delete or Backspace, or the Delete button.
- **Pan** by dragging with the right or middle mouse button, or with Space held down. Scroll to zoom, and double-click open ground to reset the view.

A wheat field's furrows run along its longest edge, and an orchard's trees stand in rows, so both follow the field as you turn or reshape it. A wood fills itself with trees the same way.

### Saving and exporting

Save keeps the location in a JSON file, every piece exactly where you left it, and Open brings it back to carry on editing. The file records the version of the app that saved it. PNG and SVG export the map with the scale bar, in any of the city generator's styles. The app asks before a new location replaces changes you haven't saved.

## For developers

### How it's organised

| File | What it does |
| --- | --- |
| `citygen/rng.py` | The seeded random numbers |
| `citygen/geometry.py` | Points, polygons and convex hulls |
| `citygen/voronoi.py` | The regions that become wards |
| `citygen/cutter.py` | Dividing polygons |
| `citygen/patch.py` | A patch of land, and the outline around a group |
| `citygen/walls.py` | City and castle walls |
| `citygen/topology.py` | The street network and path finding |
| `citygen/wards.py` | The ward types and how they lay out buildings |
| `citygen/water.py` | Coasts, rivers, bridges and piers |
| `citygen/plots.py` | Plots with a building on each, burgage plots, garden trees and the trees round greens |
| `citygen/gnomes.py` | Gnome homes, and the rectangles and barns among them |
| `citygen/countryside.py` | Wheat fields, orchards and forests |
| `citygen/model.py` | Building a whole city |
| `citygen/streets.py` | The roads and streets as drawn, bent round moved buildings and joined to bridges |
| `citygen/layers.py` | What a map draws, as plain data, the colour styles and the scale bar |
| `citygen/export.py` | JSON and SVG, and importing JSON |
| `citygen/qt_render.py` | Drawing with Qt, and PNG |
| `citygen/editing.py` | Moving and locking buildings, and reshaping walls |
| `citygen/app.py` | The desktop app |
| `sitegen/site.py` | A location and its pieces, each with an outline in its own frame and a position and angle |
| `sitegen/generate.py` | Laying out farms, toll houses and roadhouses |
| `sitegen/drawing.py` | A location's pieces as the city's layers |
| `sitegen/editing.py` | Picking, moving, turning, resizing and reshaping pieces |
| `sitegen/files.py` | Saving and opening locations, and SVG and PNG |
| `sitegen/app.py` | The location generator's window |

`rng.py`, `geometry.py`, `voronoi.py`, `cutter.py`, `patch.py`, `walls.py`, `topology.py`, `wards.py` and `model.py` follow the original's structure, with small additions for the new features. The other modules are this port's own. Where the original's behaviour looks like a mistake but shapes the maps, the port keeps it and says so in a comment. `Polygon.distance` is the main example.

### Design notes

- Everything except `qt_render.py` and `app.py` is free of Qt, so the city, its layers and the SVG and JSON exports can be built and tested without a window.
- The features added in this port draw their own random numbers, seeded from the map's seed, rather than taking from the original's sequence. Turning one on or off leaves the rest of the map alone, and Classic homes still give the original's layout.
- Roads and streets are worked out from the buildings each time the map is drawn, so they follow every edit and undo without being saved anywhere.
- Importing makes a town again from its settings and then moves its walls, roads and buildings to match the file, rather than rebuilding it from the coordinates alone. This keeps the town fully editable. `citygen/__init__.py` holds the app's version, which goes in every export. Bump it when a change could make the same settings give a different town.
- The location generator reuses the city's drawing, export, countryside and gnome home code rather than copying it. A location is a flat list of pieces. Each keeps its shape in its own frame, so moving or turning one never changes its shape, and furrows, orchard rows and wood trees are worked out from each piece when it's drawn.
- The window keeps the drawn map with a spare edge round it, so hovering and small pans don't redraw it, and big layers are drawn in small tiles, which Qt fills much faster.

### Tests

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

GitHub runs the tests on every push and pull request, on Linux with Python 3.10, 3.12 and 3.13, and on macOS and Windows with Python 3.12. The badge at the top of this page shows whether the latest run passed, and the Actions tab on GitHub has the details.

## Licence

The code is licensed under the GNU General Public License v3.0, the same licence as the original. See [LICENSE](LICENSE).

Watabou's page says the maps from the website can be used however you like, including in commercial RPG adventures, and that attribution is appreciated but not required. The GPL covers this program's code, and doesn't normally extend to what the program produces.
