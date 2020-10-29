![Python Build](https://github.com/samuelduchesne/pyumi/workflows/Python%20Build/badge.svg)

# pyumi

[The beginning of] an umi project handler written in python. Create and Open UMI projects.

# Features

- Create a large scale UMI project from a GIS dataset
- Quickly assign templates based on attribute relationship.
- Automatically download street networks from Open Street Map for the walkability module.
- Automatically create a site boundary based on the convex hull of the GIS dataset
 extent.
 
## ShapefileToUmi

pyumi was created first to accelerate the creation of UMI projects from GIS datasets.
pyumi builds on top of GeoPandas and rhino3dm to handle GIS geometry processing and
handling. Convert any GIS dataset (shapefile, geojson, etc.) to a working UMI project.

## Work in progress

- Holes in buildings, such as courtyards, are currently not supported. If you know how to
handle holes in extrusions in the rhino3dm.py interface of OpenNURBS, please let me know!

# Tutorial

To create an umi project from a GIS dataset, first the dataset must contain certain elements. Please keep in mind that:
- invalid geometries will be ignored
- features (rows) that have a missing `height` attribute will be ignored.
- features that are made of a MultiPolygon will be broken down into distinct Breps and will share the same attributes.

We can simply create the umi project by calling the `from_gis()` constructor. For this particular example, the height
attribute column in the GIS file is named `Height`. We also need to pass a `template_map` which is simply a 
dictionary of the relationship between the GIS attribute column and a specific template name in the template library.

The oshkosh_demo has 3 different use_types: COMMERCIAL, RESIDENTIAL and MIXEDUSE. It is not necessary to assign each
entries with a template. For example, if we ignore the *MIXEDUSE* template, the template map is simply:
 
```python
{
    "COMMERCIAL": "B_Off_0",
    "RESIDENTIAL": "B_Res_0_WoodFrame"
}
```

When opening this project in UMI, the buildings with the MIXEDUSE attribute will not have any templates assigned to
them.

```python

from pyumi.umi_project import UmiProject
filename = "pyumi/tests/oshkosh_demo.zip"
epw = "pyumi/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
template_lib = "pyumi/tests/BostonTemplateLibrary.json"
template_map = dict(COMMERCIAL="B_Off_0", RESIDENTIAL="B_Res_0_WoodFrame")
umi = UmiProject.from_gis(
    "zip://" + filename,
    "Height",  # height attr column name
    epw=epw,
    template_lib=template_lib,
    template_map=template_map,
    map_to_column="Use_Type",
)
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
filename = "pyumi/tests/oshkosh_demo.zip"
epw = "pyumi/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
template_lib = "pyumi/tests/BostonTemplateLibrary.json"
template_map = dict(COMMERCIAL="B_Off_0", RESIDENTIAL="B_Res_0_WoodFrame")
umi = UmiProject.from_gis(
    "zip://" + filename,
    "Height",  # height attr column name
    epw=epw,
    template_lib=template_lib,
    template_map=template_map,
    map_to_column=["Use_Type", "Year_Built"],
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
umi = UmiProject.open("pyumi/tests/oshkosh_demo.umi")
```

### Save
As shown above, to save an UmiProject, simply call the `.save()` method.

```python
from pyumi.umi_project import UmiProject
umi = UmiProject.open("pyumi/tests/oshkosh_demo.umi")
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
umi = UmiProject.open("pyumi/tests/oshkosh_demo.umi")
umi.export("project_name.json", driver="GeoJSON")
```

In the future, other drivers will become available such as 
[URBANopt™](https://docs.urbanopt.net/).