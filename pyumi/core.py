import enum
import logging as lg
import tempfile
import time
import uuid
from sqlite3 import connect
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd
from geopandas import GeoSeries
from path import Path
from rhino3dm import *
from tqdm import tqdm, tqdm_notebook

# Create and register a new `tqdm` instance with `pandas`
# (can use tqdm_gui, optional kwargs, etc.)
tqdm.pandas()


def geom_to_curve(feature):
    """Converts the GeoSeries to a :class:`_file3dm.PolylineCurve`

    Args:
        feature (GeoSeries):

    Returns:
        PolylineCurve
    """
    # Todo: add interiors and planar check

    return PolylineCurve(
        Point3dList([Point3d(x, y, 0) for x, y, *z in feature.geometry.exterior.coords])
    )


def geom_to_brep(feature, height_column_name):
    """Converts the Shapely :class:`shapely.geometry.base.BaseGeometry` to
    a :class:`_file3dm.Brep`.

    Args:
        feature (GeoSeries): A GeoSeries containing a `geometry` column.
        height_column_name (str): Name of the column containing the height
            attribute.

    Returns:

    """
    # Converts the GeoSeries to a :class:`_file3dm.PolylineCurve`

    # if has interiors
    if len(feature.geometry.interiors) > 0:
        # Todo: Implement logic to create holes in Brep
        # For now, forces `_noholes_brep`
        return _withhole_brep(feature, height_column_name)
    else:
        # only one exterior footprint to deal with
        return _noholed_brep(feature, height_column_name)


def _withhole_brep(feature, height_column_name):
    return _noholed_brep(feature, height_column_name)


def _noholed_brep(feature, height_column_name):
    """Assumes the Geometry has no holes (geopandas.base.GeoPandasBase.interiors)

    Args:
        feature (GeoSeries):
        height_column_name (str): Name of the column containing the height
            attribute.

    Returns:
        Brep: The Brep object
    """
    _rhinoCurve: Curve = PolylineCurve(
        Point3dList([Point3d(x, y, 0) for x, y, *z in feature.geometry.exterior.coords])
    )
    # Create the extrusion using the height attr. For some reason,
    # value must be negative for the extrusion to go upwards.
    _ext = Extrusion.Create(
        _rhinoCurve, height=-feature[height_column_name], cap=True,  # negative value
    )
    if _ext:
        # If Extrusion did not fail, create Brep
        _brep = _ext.ToBrep(False)
    else:
        # Else return NaN and deal outside this function.
        _brep = np.NaN
    return _brep


class UmiProject:
    def __init__(self, project_name="unnamed", epw=None, template_lib=None):
        """An UmiProject pacakge containing the _file3dm file, the project
        settings, the umi.sqlite3 database.

        Args:
            project_name (str): The name of the project
            epw (str or Path): Path of the weather file.
            template_lib (str or Path):
        """
        self.tmp = Path(tempfile.mkdtemp(dir=Path("")))

        self.name = project_name
        self.file3dm = File3dm()
        self.template_lib = template_lib
        self.epw = epw

        # Initiate Layers in 3dm file
        self.umiLayers = UmiLayers(self.file3dm)

        with connect(self.tmp / "umi.sqlite3") as con:
            con.execute(create_nonplottable_setting)
            con.execute(create_object_name_assignement)
            con.execute(create_plottatble_setting)
            con.execute(create_series)
            con.execute(create_data_point)

        self.umi_sqlite3 = con

    @property
    def epw(self):
        return self._epw

    @epw.setter
    def epw(self, value):
        """
        Args:
            value:
        """
        if value:
            set_epw = Path(value).expand()
            if set_epw.exists() and set_epw.endswith(".epw"):
                # try remove if already there
                (self.tmp / set_epw.basename()).remove_p()
                # copy to self.tmp
                tmp_epw = set_epw.copy(self.tmp)
                # set attr value
                self._epw = tmp_epw
        else:
            self._epw = None

    @property
    def template_lib(self):
        return self._template_lib

    @template_lib.setter
    def template_lib(self, value):
        if value:
            set_lib = Path(value).expand()
            if set_lib.exists() and set_lib.endswith(".json"):
                # try remove if already there
                (self.tmp / set_lib.basename()).remove_p()
                # copy to self.tmp
                tmp_lib = set_lib.copy(self.tmp)
                # set attr value
                self._template_lib = tmp_lib
        else:
            self._template_lib = None

    def __del__(self):
        self.umi_sqlite3.close()
        self.tmp.rmtree_p()

    @classmethod
    def from_gis(
        cls,
        input_file,
        height_column_name,
        epw,
        template_lib,
        template_map,
        map_to_column,
        to_crs=None,
        **kwargs,
    ):
        """Returns an UMI project by reading a GIS file (Shapefile, GeoJson,
        etc.). A height attribute must be passed in order to extrude the
        building footprints to their height. All buildings will have an
        elevation of 0 m. The input file is reprojected to :attr:`to_crs`
        (defaults to 'epsg:3857') and the extent is moved to the origin
        coordinates.

        Args:
            input_file (str or Path): Path to the GIS file. A zipped file
                can be passed by appending the path with "zip:/". Any file
                type read by :meth:`geopandas.io.file._read_file` is
                compatible.
            height_column_name (str): The attribute name containing the
                height values. Missing values will be ignored.
            to_crs (dict): The output CRS to which the file will be projected
                to. Units must be meters.
            **kwargs: keyword arguments passed to UmiProject constructor.
        """
        if to_crs is None:
            to_crs = {"init": "epsg:3857"}
        input_file = Path(input_file)

        # First, load the file to a GeoDataFrame
        start_time = time.time()
        lg.info("reading input file...")
        gdf = gpd.read_file(input_file).to_crs(to_crs)
        lg.info(
            f"Read {gdf.memory_usage(index=True).sum() / 1000:,.1f}KB from"
            f" {input_file} in"
            f" {time.time()-start_time:,.2f} seconds"
        )

        # Filter rows; Display invalid geometries in log
        valid_geoms = gdf.geometry.is_valid
        if (~valid_geoms).any():
            lg.warning(
                f"Invalid geometries found! The following "
                f"{(~valid_geoms).sum()} entries "
                f"where ignored: {gdf.loc[~valid_geoms].index}"
            )
        else:
            lg.info("No invalid geometries reported")
        gdf = gdf.loc[valid_geoms, :]  # Only valid geoms

        # Filter rows missing attribute
        valid_attrs = ~gdf[height_column_name].isna()
        gdf = gdf.loc[valid_attrs, :]

        # Move to center; Makes the Shoeboxer happy
        centroid = gdf.cascaded_union.convex_hull.centroid
        xoff, yoff = centroid.x, centroid.y
        gdf.geometry = gdf.translate(-xoff, -yoff)

        # Explode to singlepart
        gdf = gdf.explode()  # The index of the input geodataframe is no
        # longer unique and is replaced with a multi-index (original index
        # with additional level indicating the multiple geometries: a new
        # zero-based index for each single part geometry per multi-part
        # geometry).

        # Create Rhino Geometries in two steps
        gdf["rhino_geom"] = gdf.progress_apply(
            geom_to_brep, args=(height_column_name,), axis=1
        )

        # Filter out errored rhino geometries
        errored_brep = gdf["rhino_geom"].isna()
        if errored_brep.any():
            lg.warning(
                f"Brep creation errors! The following "
                f"{errored_brep.sum()} entries "
                f"where ignored: {gdf.loc[errored_brep].index}"
            )
        else:
            lg.info(f"{gdf.size} breps created")
        gdf = gdf.loc[~errored_brep, :]

        # create the UmiProject object
        name = kwargs.pop("name", input_file.stem)
        umi_file = cls(project_name=name, epw=epw, template_lib=template_lib)

        # Create blank 3DM file
        threedm = umi_file.file3dm

        # Set ModelUnitSystem to Meters
        threedm.Settings.ModelUnitSystem = threedm.Settings.ModelUnitSystem.Meters

        # Add all Breps to Model and append UUIDs to gdf
        gdf["guid"] = gdf["rhino_geom"].progress_apply(threedm.Objects.AddBrep)

        for obj in threedm.Objects:
            obj.Attributes.LayerIndex = umi_file.umiLayers.Buildings.Index
            obj.Attributes.Name = str(
                gdf.loc[gdf.guid == obj.Attributes.Id].index.values[0]
            )

        bldg_attributes = {
            "CoreDepth": 1,
            "Envr": 0.01,
            "Fdist": 3,
            "FloorToFloorHeight": 3,
            "PerimeterOffset": 3,
            "RoomWidth": 0.4,
            "WindowToWallRatioE": 0.4,
            "WindowToWallRatioN": 0.4,
            "WindowToWallRatioRoof": 0,
            "WindowToWallRatioS": 0.4,
            "WindowToWallRatioW": 0.4,
            "TemplateName": None,
            "EnergySimulatorName": "UMI Shoeboxer (default)",
            "FloorToFloorStrict": 0,
        }
        gdf[list(bldg_attributes.keys())] = gdf.apply(
            lambda x: pd.Series(bldg_attributes), axis=1
        )

        # Assign template names using map. Changes elements based on the
        # chosen column name parameter.
        def on_frame(map_to_column, template_map):
            """Returns the DataFrame for left_join based on number of nested levels"""
            depth = dict_depth(template_map)
            if depth == 2:
                return (
                    pd.Series(template_map)
                    .rename_axis(map_to_column)
                    .rename("TemplateName")
                    .to_frame()
                )
            elif depth == 3:
                return (
                    pd.DataFrame(template_map)
                    .stack()
                    .swaplevel()
                    .rename_axis(map_to_column)
                    .rename("TemplateName")
                    .to_frame()
                )
            elif depth == 4:
                return (
                    pd.DataFrame(template_map)
                    .stack()
                    .swaplevel()
                    .apply(pd.Series)
                    .stack()
                    .rename_axis(map_to_column)
                    .rename("TemplateName")
                    .to_frame()
                )
            else:
                raise NotImplementedError("5 levels or more are not yet supported")

        _index = gdf.index
        gdf = (
            gdf.set_index(map_to_column)
            .drop(columns=["TemplateName"])
            .join(on_frame(map_to_column, template_map), on=map_to_column)
        )
        gdf.index = _index

        for idx, series in gdf.iterrows():
            for attr in [
                "CoreDepth",
                "Envr",
                "Fdist",
                "FloorToFloorHeight",
                "PerimeterOffset",
                "RoomWidth",
                "WindowToWallRatioE",
                "WindowToWallRatioN",
                "WindowToWallRatioRoof",
                "WindowToWallRatioS",
                "WindowToWallRatioW",
            ]:
                nonplottable_settings = (
                    "unused",
                    str(series["guid"]),
                    attr,
                    str(series[attr]),
                )
                umi_file.umi_sqlite3.execute(
                    "INSERT INTO plottable_setting (key, object_id, name, value) "
                    "VALUES (?, ?, ?, ?)",
                    nonplottable_settings,
                )
        for idx, series in gdf.iterrows():
            for attr in [
                "TemplateName",
                "EnergySimulatorName",
                "FloorToFloorStrict",
            ]:
                plottatble_settings = (
                    "unsused",
                    str(series["guid"]),
                    attr,
                    str(series[attr]),
                )
                umi_file.umi_sqlite3.execute(
                    "INSERT INTO nonplottable_setting (key, object_id, name, value) "
                    "VALUES (?, ?, ?, ?)",
                    plottatble_settings,
                )

        # Add Site boundary PolylineCurve. Uses the exterior of the
        # convex_hull of the unary_union of all footprints. This is a good
        # approximation of a site boundary in most cases.
        boundary = PolylineCurve(
            Point3dList(
                [
                    Point3d(x, y, 0)
                    for x, y, *z in gdf.geometry.unary_union.convex_hull.exterior.coords
                ]
            )
        )
        guid = umi_file.file3dm.Objects.AddCurve(boundary)
        fileObj, *_ = filter(
            lambda x: x.Attributes.Id == guid, umi_file.file3dm.Objects
        )
        fileObj.Attributes.LayerIndex = umi_file.umiLayers["Site boundary"].Index
        fileObj.Attributes.Name = "Convex hull boundary"

        return umi_file

    def open(self):
        """Todo: implement Open method"""
        pass

    def save(self):
        # save 3dm file to UmiProject.tmp dir
        self.file3dm.Write(self.tmp / (self.name + ".3dm"), 6)
        self.umi_sqlite3.commit()
        outfile = Path(self.name) + ".umi"
        with ZipFile(outfile, "w") as zip_file:
            for file in self.tmp.files():
                # write `file` to arcname `file.basename()`
                zip_file.write(file, file.basename())

        lg.info(f"Saved to {(Path(self.name) + '.umi').abspath()}")


class UmiLayers:
    """Handles creation of :class:`rhino3dm.Layer` for umi projects"""

    _umiLayers = {
        "umi": {
            "Buildings": {},
            "Context": {
                "Site boundary": {},
                "Streets": {},
                "Parks": {},
                "Boundary objects": {},
                "Shading": {},
                "Trees": {},
            },
        }
    }

    @classmethod
    def __getitem__(cls, x):
        return getattr(cls, x)

    def __init__(self, file3dm):
        """

        Args:
            file3dm (File3dm):
        """
        self._file3dm = file3dm

        def iter_layers(d, _pid):
            for k, v in d.items():
                _layer = Layer()  # Create Layer
                _layer.Name = k  # Set Layer Name
                _layer.ParentLayerId = _pid  # Set parent Id
                self._file3dm.Layers.Add(_layer)  # Add Layer
                _layer, *_ = filter(lambda x: x.Name == k, self._file3dm.Layers)

                # Sets Layer as class attr
                setattr(UmiLayers, _layer.Name, _layer)

                # Iter
                if isinstance(v, (dict,)):
                    if bool(v):
                        _pid = _layer.Id
                    iter_layers(v, _pid)

        iter_layers(
            UmiLayers._umiLayers, uuid.UUID("00000000-0000-0000-0000-000000000000")
        )


create_nonplottable_setting = """create table nonplottable_setting
(
    key       TEXT not null,
    object_id TEXT not null,
    name      TEXT not null,
    value     TEXT not null,
    primary key (key, object_id, name)
);"""

create_object_name_assignement = """create table object_name_assignment
(
    id   TEXT
        primary key,
    name TEXT not null
);"""

create_plottatble_setting = """create table plottable_setting
(
    key       TEXT not null,
    object_id TEXT not null,
    name      TEXT not null,
    value     REAL not null,
    primary key (key, object_id, name)
);"""

create_series = """create table series
(
    id         INTEGER primary key,
    name       TEXT not null,
    module     TEXT not null,
    object_id  TEXT not null,
    units      TEXT,
    resolution TEXT,
    unique (name, module, object_id)
);"""

create_data_point = """create table data_point
(
    series_id       INTEGER not null references series on delete cascade,
    index_in_series INTEGER not null,
    value           REAL    not null, 
    primary key (series_id, index_in_series)
);"""


from collections import Sequence
from itertools import chain, count


# Python3 Program to find depth of a dictionary
def dict_depth(dic, level=1):
    if not isinstance(dic, dict) or not dic:
        return level
    return max(dict_depth(dic[key], level + 1) for key in dic)
