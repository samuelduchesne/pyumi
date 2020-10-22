# pyumi

[The beginning of] an umi project handler written in python. Create and Open UMI projects.

## ShapefileToUmi

pyumi was created firts to accelerate the creation of UMI projects from GIS datasets. pyumi builds on top of GeoPandas and rhino3dm to handle GIS geometry processing and handling. Convert any GIS dataset (shapefile, geojson, etc.) to a working UMI project. 

## Work in progress

- Holes in buildings, such as courtyards, are currently not supported. If you know how to handle holes in extrusions in the rhinod3dm.py interface of OpenNURBS, please let me know!


# Tutorial

To create an umi project from a GIS dataset, first the dataset must contain certain elements. Please keep in mind that:
- invalid geometries will be ignored
- features (rows) that have a missing `height` attribute will be ignored.
- features that are made of a MultiPolygon will be broken down into distinct Breps and will share the same attributes.

In this particular example, knowing that the height attribute column is named `Height`, we can simply create the umi project by calling the `from_gis()` constructor.

```
from pyumi.core import UmiFile
epw = "pyumi/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
umi = UmiFile.from_gis(
    "zip://pyumi/tests/oshkosh_demo.zip", "Height", epw=epw
)
```
