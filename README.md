![Python Build](https://github.com/samuelduchesne/pyumi/workflows/Python%20Build/badge.svg)

# pyumi

[The beginning of] an umi project handler written in python. Create and Open UMI projects.

# Features

- Create a large scale UMI project from a GIS dataset.
- Quickly assign templates based on attribute relationship.
- Download street networks from Open Street Map and use with the walkability module.
- Download any Point of Interest (POI) from Open Street Map.
- Automatically create a site boundary based on the convex hull of the GIS dataset extent.
- Downloads EPW weather file closest to the location of the GIS dataset.
 
## GIS to UMI Workflow

pyumi was created first to accelerate the creation of UMI projects from large GIS datasets.
pyumi builds on top of GeoPandas and rhino3dm to handle GIS geometry processing and
handling. This enbales complex GIS datasets (shapefile, geojson, etc.) to be converted to an UMI project.
Template assignemnts can be done using a name mapping dictionnary or using an attribute column name.

# Tutorial

To create an umi project from a GIS dataset, first the dataset must contain certain elements. Please keep in mind that:
- invalid geometries will be ignored
- features (rows) that have a missing `height` attribute will be ignored.
- features that are made of a MultiPolygon will be broken down into distinct Breps and will share the same attributes.
- features that don't resolve with any template assignment will be put to the ``umi::Context::Shading`` layer.

## Compatibility

Because pyumi relies on the rhino3dm library, it is only compatible with python 3.7.

## Installation

pyumi uses many GIS libraries that are quite finicky. It is strongly recommended that pyumi be installed on a new conda environment:

```shell script
git clone https://github.com/samuelduchesne/pyumi.git
cd pyumi
conda create -c conda-forge -n pyumi python=3.7
conda env update -n pyumi --file environment.yml
conda activate pyumi
```

## From a GIS dataset

We can simply create the umi project by calling the `from_gis()` constructor. For this particular example (oshkosh_demo), the height
attribute column in the GIS file is named `Height`. We also need to pass a `template_map` which is simply a 
dictionary of the relationship between the GIS attribute column and a specific template name in the template library (here the `BostonTemplateLibrary.json`).

The oshkosh_demo has 3 different use_types: COMMERCIAL, RESIDENTIAL and MIXEDUSE. It is not necessary to assign each
entries with a template. For example, if we ignore the *MIXEDUSE* template, the template map is simply:
 
```python
{
    "COMMERCIAL": "B_Off_0",
    "RESIDENTIAL": "B_Res_0_WoodFrame"
}
```

When opening this project in UMI, the buildings with the MIXEDUSE attribute will not have any templates assigned to
them and be moved to the ``umi::Context::Shading``.

As for Umi projects created in Rhino, the weather file and the template library must defined. Templates can be downloaded from [ubem.io](http://ubem.io) and weather files can be downloaded from [Energy Plus](https://energyplus.net/weather).

```python
from pyumi.umi_project import UmiProject
filename = "tests/oshkosh_demo.zip"
epw = "tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
template_lib = "tests/BostonTemplateLibrary.json"
template_map = dict(COMMERCIAL="B_Off_0", RESIDENTIAL="B_Res_0_WoodFrame")
umi = UmiProject.from_gis(
    "zip://" + filename,
    height_column_name="Height",
    template_lib=template_lib,
    template_map=template_map,
    map_to_column="Use_Type",
    epw=epw
).save()
```

## MultiLevel template assigment

Let's say that the template assignment follows an additional attribute, the `Year_Built`. The template_map simply needs
to have an additional level (nested dict):
 
```python
{
    "COMMERCIAL": {1948: "B_Off_0", 1970: "B_Off_0"},
    "RESIDENTIAL": {1948:"B_Res_0_WoodFrame", 1970: "B_Res_0_WoodFrame"}
}
```

Using this multilevel map, we also pass two column names to the constructor `map_to_column=["Use_Type", "Year_Built"]`:

```python
from pyumi.umi_project import UmiProject
filename = "tests/oshkosh_demo.zip"
epw = "tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
template_lib = "tests/BostonTemplateLibrary.json"
template_map = {
    "COMMERCIAL": {1948: "B_Off_0", 1970: "B_Off_0"},
    "RESIDENTIAL": {1948:"B_Res_0_WoodFrame", 1970: "B_Res_0_WoodFrame"}
}
umi = UmiProject.from_gis(
    "zip://" + filename,
    "Height",
    template_lib=template_lib,
    template_map=template_map,
    map_to_column=["Use_Type", "Year_Built"],
    epw=epw
).save()
```

## Download OSM Street Networks

For UmiProjects created from GIS datasets (`from_gis`) it is possible to add a street
network on the Streets layer. This street network is automatically downloaded from Open
Street Map thanks to the excellent `osmnx` package.

To add a street network, simply call `.add_street_graph()` on the UmiProject object and
 `.save()`:
 
```python
# with the umi project created above
umi.add_street_graph(
    network_type="all_private",
    simplify=True,
    retain_all=False,
    truncate_by_edge=False,
    clean_periphery=True,
    custom_filter=None
).save()
```

Many options are available to fine tune the end result. For example, for the `network_type
`, users can choose from one of 'walk', 'bike', 'drive', 'drive_service', 'all', or
'all_private'. More information at
[osmnx](https://osmnx.readthedocs.io/en/stable/osmnx.html#osmnx.graph.graph_from_polygon).

## Download OSM Points of Interest (POIs)

For UmiProjects created from GIS datasets (`from_gis`) it is possible to download any
points of interest from Open Street Map. These can be points or polygons. They can be
added to a specific Layer. For example, trees are added to the Trees Layer using a
dictionary of tags. For more information on which tags are available, visit [OSM Map
Features ](https://wiki.openstreetmap.org/wiki/Map_Features)"
  
```python
# with the umi project created above
umi.add_pois(
    tags=dict(natural=["tree_row", "tree", "wood"], trees=True),
    on_file3dm_layer="umi::Context::Trees",
).save()
```

## Site Boundary

A Site boundary is automatically generated for the extent of the GIS input file. It
generates a convex hull PolylineCurve which resides on the umi::Context:Site boundary
layer.


## Opening, Saving and Exporting operations

### Open
To open an existing `.umi` file. simply call the `UmiProject.open()` constructor

```python
from pyumi.umi_project import UmiProject
umi = UmiProject.open("tests/oshkosh_demo.umi")
```

### Save
As shown above, to save an UmiProject, simply call the `.save()` method.

```python
from pyumi.umi_project import UmiProject
umi = UmiProject.open("tests/oshkosh_demo.umi")
umi.save("oshkosh_demo_copy.umi")
```

### Export (to_file) 
For compatibility with other workflows, it is possible to export to
multiple file formats.

For now, any GIS file format supported by fiona is available. To see a list:

```python
import fiona; fiona.supported_drivers
```

For example, to export to GeoJSON:

```python
from pyumi.umi_project import UmiProject
umi = UmiProject.open("tests/oshkosh_demo.umi")
umi.export("project_name.json", driver="GeoJSON")
```

In the future, other drivers will become available such as 
[URBANopt™](https://docs.urbanopt.net/).


### Analyzing Results

#### Energy Module

Results from the energy module can be analysed by calling the `energy` property
. Autocompletion helps list possible time series:

```python
from pyumi.umi_project import UmiProject
umi = UmiProject.open("tests/oshkosh_demo.umi")
umi.energy
```
Should display:
```shell script
Available Series                     Totals
---------------------------------  --------
SDL_Energy_Total_Area                     0
Hour_SDL_Cooling                     239728
Hour_SDL_Domestic_Hot_Water          421267
Hour_SDL_Equipment                   460975
Hour_SDL_Heating                     833394
Hour_SDL_Lighting                    612800
Hour_SDL_Total_Operational_Energy   2568164
Hour_SDL_Window_Radiation           2463248
```

Each series is returned as a DataFrame where each column is a building. If multiple rhino
geometries are given the same building name, then these DataFrames report the aggregated
values (sum) of each name.

For example, `umi.energy.Hour_SDL_Heating` returns:

```
name                   0        10        11  ...   61         7         8
2017-01-01 00:00:00  0.0  9.762815  8.631218  ...  0.0  6.584232  4.082195
2017-01-01 01:00:00  0.0  8.875096  7.834453  ...  0.0  5.977587  3.701388
2017-01-01 02:00:00  0.0  9.025306  7.944401  ...  0.0  6.074837  3.746451
2017-01-01 03:00:00  0.0  9.105266  7.995787  ...  0.0  6.129568  3.767022
2017-01-01 04:00:00  0.0  9.136625  8.008572  ...  0.0  6.153552  3.770450
                  ...       ...       ...  ...  ...       ...       ...
2017-12-31 19:00:00  0.0  2.739810  2.853194  ...  0.0  1.855790  1.399154
2017-12-31 20:00:00  0.0  3.070990  3.182003  ...  0.0  2.031320  1.543346
2017-12-31 21:00:00  0.0  3.780662  3.679383  ...  0.0  2.516818  1.771151
2017-12-31 22:00:00  0.0  4.094682  3.857272  ...  0.0  2.748152  1.845514
2017-12-31 23:00:00  0.0  4.957705  4.560792  ...  0.0  3.343510  2.173121
[8760 rows x 55 columns]
````

## Contributing

### Code Style
We use isort to sort imports.
We use [black](https://black.readthedocs.io/en/stable/) for code formatting.

At the root of the repository, run in this order:
1. isort: `isort .` (mind the period)
1. black: `black .` (mind the period)
1. flake8: `python -m flake8 pyumi/`

### Unit testing
At the root of the repository, run pytest: `python -m pytest`.

