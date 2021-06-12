"""Module to handle umi projects as python objects."""
import collections
import io
import json
import logging
import math
import os
import re
import tempfile
import time
import uuid
import zipfile
from io import StringIO, BytesIO
from json import JSONDecodeError
from sqlite3 import Connection, OperationalError, Row
from sqlite3.dbapi2 import connect
from zipfile import ZipFile, ZipInfo

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from archetypal import IDF
from energy_pandas import EnergyDataFrame, EnergySeries
from fiona import supported_drivers as fiona_drivers
from geopandas import GeoDataFrame, GeoSeries
from networkx import is_empty
from osmnx import geometries_from_polygon, project_gdf, project_graph
from pandas import date_range
from path import Path
from pyproj import CRS
from rhino3dm import Brep, File3dm, Point3d, Point3dList, PolylineCurve
from rhino3dm._rhino3dm import UnitSystem
from shapely.geometry import Point
from tabulate import tabulate
from tqdm import tqdm

from pyumi.epw import Epw
from pyumi.geom_ops import geom_to_brep, resolve_3dm_geom
from pyumi.shoeboxer import ShoeBox
from pyumi.umi_layers import UmiLayers

from energy_pandas.units import unit_registry

# create logger
PYUMI_DRIVERS = []  # Todo: Specify future output formats here.
log = logging.getLogger(__name__)

# add specific units to registry

unit_registry.define("kilogram_of_co2 = 1 * kilogram = kgCO2")


class ShoeBoxCollection(collections.UserDict):
    """A collection of :class:`ShoeBox` models with their path as a key.

    Handles getting and setting variable values.
    """

    def __getattr__(self, key):
        """Get attribute."""
        if isinstance(key, int):
            value = list(self.data.values())[key]
        else:
            try:
                value = super(ShoeBoxCollection, self).__getitem__(key)
            except KeyError:
                value = self.data[key]
        return value

    def __getitem__(self, key):
        """Get item."""
        if isinstance(key, int):
            value = list(self.data.values())[key]
        elif isinstance(key, slice):
            value = list(self.data.values()).__getitem__(key)
        else:
            value = super(ShoeBoxCollection, self).__getitem__(key)
        return value

    def __setattr__(self, key, value):
        """Set attribute."""
        if isinstance(value, dict):
            super(ShoeBoxCollection, self).__setattr__(key, value)
        elif isinstance(value, ShoeBox):
            super(ShoeBoxCollection, self).__setattr__(
                key.replace("\\", "_")
                .replace("/", "_")
                .replace("-", "_")
                .replace(".idf", ""),
                value,
            )
            super(ShoeBoxCollection, self).__setitem__(key, value)
        else:
            self.__setitem__(key, value)

    def __setitem__(self, key, value):
        """Set item."""
        if isinstance(value, ShoeBox):
            """if a ShoeBox is given, simply set it"""
            self.__setattr__(key, value)
        else:
            raise TypeError(
                "Cannot set a value of type {} in this "
                "VariableCollection".format(type(value))
            )


class UmiProject:
    """An UMI Project.

    Attributes:
        to_crs (dict): The
        gdf_world (GeoDataFrame): GeoDataFrame in original world coordinates
        gdf_3dm (GeoDataFrame): GeoDataFrame in projected coordinates and
            translated to Rhino origin (0,0,0).

    """

    DEFAULT_SHOEBOX_SETTINGS = {
        "CoreDepth": 3,
        "Envr": 1,
        "Fdist": 1,  # 1 sensor every meter seems reasonable
        "FloorToFloorHeight": 3.0,
        "PerimeterOffset": 3.0,
        "RoomWidth": 3.0,
        "WindowToWallRatioE": 0.4,
        "WindowToWallRatioN": 0.4,
        "WindowToWallRatioRoof": 0,
        "WindowToWallRatioS": 0.4,
        "WindowToWallRatioW": 0.4,
        "TemplateName": np.NaN,
        "EnergySimulatorName": "UMI Shoeboxer (default)",
        "FloorToFloorStrict": True,
    }

    def __init__(
        self,
        project_name="unnamed",
        epw=None,
        template_lib=None,
        file3dm=None,
        gdf_world=None,
        gdf_world_projected=None,
        gdf_3dm=None,
        umi_layers=None,
        to_crs=None,
        umi_sqlite=None,
        fid="fid",
        sdl_common=None,
        fast_open=False,
        shoeboxes=None,
    ):
        """Constructor."""
        self.fid = fid  # Column use as unique id gdf3dm
        self.sdl_common = sdl_common if sdl_common is not None else {}
        self.to_crs = to_crs
        self.gdf_world = gdf_world if gdf_world is not None else GeoDataFrame()
        self.gdf_world_projected = (
            gdf_world_projected if gdf_world_projected is not None else GeoDataFrame()
        )
        self.gdf_3dm = gdf_3dm if gdf_3dm is not None else GeoDataFrame()

        self.name = project_name
        self.file3dm = file3dm or File3dm()
        self.template_lib = template_lib
        self.epw = epw
        self.energy = Energy(self)
        self.shoeboxes = shoeboxes

        # Initiate Layers in 3dm file
        self.umiLayers = umi_layers or UmiLayers(self.file3dm)

        if isinstance(umi_sqlite, bytes):
            con = connect(":memory:")
            con.cursor().executescript(umi_sqlite)
            con.commit()
            con.row_factory = Row
        elif isinstance(umi_sqlite, Connection):
            con = umi_sqlite
        elif isinstance(umi_sqlite, str):
            source = connect(umi_sqlite)
            con = connect(":memory:")
            source.backup(con)
        else:
            con = connect(":memory:")
        try:
            con.execute(create_nonplottable_setting)
            con.execute(create_object_name_assignement)
            con.execute(create_plottatble_setting)
            con.execute(create_series)
            con.execute(create_data_point)
        except OperationalError:
            pass  # tables already exist

        # Set ModelUnitSystem to Meters
        self.file3dm.Settings.ModelUnitSystem = UnitSystem.Meters

        self.umi_sqlite3 = con
        if not fast_open:
            self.energy._get_series()  # Construct series

    @property
    def epw(self):
        """The weather file as an Epw object."""
        return self._epw

    @epw.setter
    def epw(self, value):
        """Set the weather file. If a string is passed, it is loaded as a Epw object."""
        if value:
            if isinstance(value, Epw):
                self._epw = value
            elif Path(value).exists() and Path(value).endswith(".epw"):
                self._epw = Epw(value)
            else:
                raise ValueError(f"Cannot set epw file {value}")
        else:
            self._epw = None

    @property
    def template_lib(self):
        """The template library."""
        return self._template_lib

    @template_lib.setter
    def template_lib(self, value):
        """Set the template library. If a file is passed, it is loaded."""
        if isinstance(value, dict):
            self._template_lib = value
        elif isinstance(value, (str or Path)):
            with open(value, "r") as f:
                self._template_lib = json.load(f)
        else:
            self._template_lib = None

    @property
    def to_crs(self):
        """The cartesian coordinate system used in the file3dm."""
        return self._to_crs

    @to_crs.setter
    def to_crs(self, value):
        """Set the CRS by checking first if it is a cartesian coordinate system."""
        if isinstance(value, CRS):
            _crs = value
        elif isinstance(value, dict):
            _crs = CRS.from_user_input(**value)
        elif isinstance(value, str):
            _crs = CRS.from_string(value)
        elif value is None:
            _crs = None
        else:
            raise ValueError(
                f"Could not parse CRS of type {type(value)}. "
                f"Provide the crs as a string or as a dictionary"
            )
        if _crs:
            if _crs.coordinate_system.name != "cartesian":
                raise ValueError(
                    f"project can only be projected to a cartesian "
                    f"system unlike the specified CRS: {_crs}"
                )
        self._to_crs = _crs

    def __del__(self):
        """Delete object."""
        self.umi_sqlite3.close()

    @classmethod
    def from_gis(
        cls,
        input_file,
        height_column_name,
        template_lib,
        template_column_name=None,
        template_map=None,
        map_to_columns=None,
        epw=None,
        fid=None,
        to_crs=None,
        **kwargs,
    ):
        """Returns an UMI project by reading a GIS file.

        Supported file types: (Shapefile, GeoJson,etc.). A height attribute
        must be passed in order to extrude the building footprints to their
        height. All buildings will have an elevation of 0 m. The input file
        is reprojected to :attr:`to_crs` (defaults to 'epsg:3857') and the
        extent is moved to the origin coordinates.

        Args:
            input_file (str or Path): Path to the GIS file. A zipped file
                can be passed by appending the path with "zip://". Any file
                type read by :meth:`geopandas.io.file._read_file` is
                compatible.
            height_column_name (str): The attribute name containing the
                height values. Missing values will be ignored.
            template_lib (path or dict): The path to the umi template library. A
                dictionary can also be passed.
            template_column_name (str): The column name containing the template names
                for each footprint in the GIS file. If None, :attr:`template_map`
                and :attr:`map_to_columns` must be provided.
            template_map (dict): A dictionary of the relationship between the GIS
                attribute column and a specific template name in the template library.
            map_to_columns (list of str): A list of column names to map templates to.
            epw (str or path, optional): The path of the epw file. Optional.
            fid (str): Optional, the column name corresponding to the id of
                each feature. If None, a serial id is created automatically.
            to_crs (dict): The output CRS to which the file will be
                projected to. Units must be meters.
            **kwargs: keyword arguments passed to UmiProject constructor.

        Returns:
            UmiProject: The UmiProject. Needs to be saved
        """
        input_file = Path(input_file)

        # First, load the file to a GeoDataFrame
        start_time = time.time()
        log.info("reading input file...")
        gdf = gpd.read_file(input_file)
        log.info(
            f"Read {gdf.memory_usage(index=True).sum() / 1000:,.1f}KB from"
            f" {input_file} in"
            f" {time.time() - start_time:,.2f} seconds"
        )
        if "project_name" not in kwargs:
            kwargs["project_name"] = input_file.stem

        return cls.from_gdf(
            gdf,
            height_column_name=height_column_name,
            template_lib=template_lib,
            template_column_name=template_column_name,
            template_map=template_map,
            map_to_columns=map_to_columns,
            epw=epw,
            fid=fid,
            to_crs=to_crs,
            **kwargs,
        )

    @classmethod
    def from_gdf(
        cls,
        gdf,
        height_column_name,
        template_lib,
        template_column_name="TemplateName",
        template_map=None,
        map_to_columns=None,
        epw=None,
        fid=None,
        to_crs=None,
        **kwargs,
    ):
        """Return an UMI project by reading a GeoDataFrame.

        A height attribute must be passed in order to extrude the building
        footprints to their height. All buildings will have an elevation of
        0 m. The GeoDataFrame must be projected and the extent is moved to
        the origin coordinates.

        Args:
            gdf (GeoDataFrame): The GeoDataFrame.
            height_column_name (str): The attribute name containing the
                height values. Missing values will be ignored.
            template_lib (path or dict): The path to the umi template library. A
                dictionary can also be passed.
            template_column_name (str): The column name containing the template names
                for each footprint in the GIS file. If None, :attr:`template_map`
                and :attr:`map_to_columns` must be provided.
            template_map (dict): A dictionary of the relationship between the GIS
                attribute column and a specific template name in the template library.
            map_to_columns (list of str): A list of column names to map templates to.
            epw (path): The path of the epw file. Optional.
            fid (str): Optional, the column name corresponding to the id of
                each feature. If None, a serial id is created automatically.
            to_crs (dict or CRS, optional): The CRS the input_file is
                projected to for a planer representation in the file3dm.
                Units of the crs must be meters.
            **kwargs: keyword arguments passed to UmiProject constructor.

        Returns:
            UmiProject: The UmiProject. Needs to be saved.
        """
        # Assign template names using map. Changes elements based on the
        # chosen column name parameter.
        def on_frame(map_to_columns, template_map):
            """Returns the DataFrame for left_join based on number of nested levels.

            The return df has the form <MultiIndex([Grouping1, Grouping2, ...]):
            "TemplateName > if dict_depth > 2, otherwise it is a normal Index.
            """

            def flatten(d, parent_key=(), level=1):
                """from: https://stackoverflow.com/a/6027615."""
                items = []
                for k, v in d.items():
                    new_key = (
                        tuple(list(parent_key) + [k]) if parent_key else tuple([k])
                    )
                    if isinstance(v, collections.MutableMapping):
                        items.extend(flatten(v, new_key, level=level - 1).items())
                    elif level <= 2:
                        items.append((new_key, v))
                    else:
                        new_key = tuple(list(new_key) + [None])
                        items.append((new_key, v))
                return dict(items)

            flat_template_map = flatten(template_map, level=_dict_depth(template_map))
            df = pd.Series(flat_template_map)
            df.index = df.index.rename(map_to_columns)
            return df.to_frame("TemplateName").astype("object")

        _index = gdf.index
        if template_column_name is None:
            if template_map and map_to_columns:
                # map templates using `template_map`. This updates the column named
                # "TemplateName" using the keys of `map_to_columns`.
                # DataFrame.join always uses other's index but we can use any column
                # in df. This method preserves the original DataFrame's index in the
                # result.

                if not isinstance(map_to_columns, (tuple, list)):
                    map_to_columns = [map_to_columns]

                # Necessary to reset_index to map the dtype of the original DataFrame.
                mapped_to = (
                    on_frame(map_to_columns, template_map)
                    .reset_index()
                    .astype(gdf[map_to_columns].dtypes.to_dict())
                    .set_index(map_to_columns)
                )

                # Instead of a join, which would fail if gdf already has some data
                # for TemplateName, we use `update`
                gdf.set_index(map_to_columns, inplace=True)
                gdf.update(mapped_to)
                gdf.reset_index(inplace=True)
            else:
                raise ValueError(
                    "If `template_column_name` is None, `template_map` and "
                    "`map_to_columns` must be provided."
                )
        else:
            # rename the user-defined template_column_name to the
            # umi one ("TemplateName")
            gdf.rename(columns={template_column_name: "TemplateName"}, inplace=True)
        gdf.index = _index  # reset the index to previous

        # Filter rows; Display invalid geometries in log
        valid_geoms = gdf.geometry.is_valid
        if (~valid_geoms).any():
            log.warning(
                f"Invalid geometries found! The following "
                f"{(~valid_geoms).sum()} entries "
                f"where ignored: {gdf.loc[~valid_geoms].index}"
            )
        else:
            log.info("No invalid geometries reported")
        gdf = gdf.loc[valid_geoms, :]  # Only valid geoms

        # Filter rows missing attribute
        valid_attrs = ~gdf[height_column_name].isna()
        if (~valid_attrs).any():
            log.warning(
                f"Some rows have a missing {height_column_name}! The "
                f"following "
                f"{(~valid_attrs).sum()} entries "
                f"where ignored: {gdf.loc[~valid_attrs].index}"
            )
        else:
            log.info(
                f"{valid_attrs.sum()} reported features with a "
                f"{height_column_name} attribute value"
            )
        gdf = gdf.loc[valid_attrs, :]

        # Set the identification of buildings. This "fid" is used as the
        # Brep `Name` attribute. If a building is made of multiple
        # polygons, then the Breps will have the same name.
        if not fid:
            fid = "fid"
            if "fid" in gdf.columns:
                pass  # This is a user-defined fid
            else:
                gdf[fid] = gdf.index.values  # This serial fid
        # Explode to singlepart
        gdf = gdf.explode()  # The index of the input geodataframe is no
        # longer unique and is replaced with a multi-index (original index
        # with additional level indicating the multiple geometries: a new
        # zero-based index for each single part geometry per multi-part
        # geometry).
        from osmnx.projection import project_gdf

        gdf_world = project_gdf(gdf, to_latlong=True)
        try:
            gdf = project_gdf(gdf, to_crs=to_crs)
        except ValueError:
            # Geometry is already projected. cannot calculate UTM zone
            pass
        finally:
            gdf_world_projected = gdf.copy()  # make a copy for reference

        # Move to center; Makes the Shoeboxer happy
        projected_world_centroid = gdf_world_projected.unary_union.centroid
        xoff, yoff = projected_world_centroid.x, projected_world_centroid.y
        gdf.geometry = gdf.translate(-xoff, -yoff)

        # Create Rhino Geometries in two steps
        tqdm.pandas(desc="Creating 3D geometries")
        file3dm = kwargs.get("file3dm", None)

        def try_make_geom(series, height_column_name):
            if file3dm:
                obj = file3dm.Objects.FindId(series[fid])
                if obj:
                    return obj.Geometry
            else:
                height = series[height_column_name]
                return geom_to_brep(series.geometry, 0, height)

        gdf["rhino_geom"] = gdf.progress_apply(
            try_make_geom, args=(height_column_name,), axis=1
        )

        # Filter out errored rhino geometries
        start_time = time.time()
        errored_brep = gdf["rhino_geom"].isna()
        if errored_brep.any():
            log.warning(
                f"Brep creation errors! The following "
                f"{errored_brep.sum()} entries "
                f"where ignored: {gdf.loc[errored_brep].index}"
            )
        else:
            log.info(
                f"{gdf.size} breps created in "
                f"{time.time() - start_time:,.2f} seconds"
            )
        gdf = gdf.loc[~errored_brep, :]

        if epw is None:
            try:
                epw = Epw.from_nrel(
                    gdf_world.unary_union.convex_hull.centroid.y,
                    gdf_world.unary_union.convex_hull.centroid.x,
                )
            except Exception as e:
                epw = None
                log.error("Unable to retrieve weather file", exc_info=e)

        # create the UmiProject object
        umi_project = cls(
            epw=epw,
            template_lib=template_lib,
            gdf_3dm=gdf,
            gdf_world=gdf_world,
            gdf_world_projected=gdf_world_projected,
            to_crs=gdf._crs,
            **kwargs,
        )

        umi_project.sdl_common.update(
            {
                "project-settings": {
                    "OriginalProjectedOrigin": (
                        projected_world_centroid.x,
                        projected_world_centroid.y,
                    )
                }
            }
        )

        # Add all Breps to Model and append UUIDs to gdf
        tqdm.pandas(desc="Adding Breps to File3dm")

        def _try_add(series):
            if file3dm:
                obj = file3dm.Objects.FindId(series[fid])
                if obj:
                    return obj.Attributes.Id
            else:
                return umi_project.file3dm.Objects.AddBrep(series["rhino_geom"])

        gdf["guid"] = gdf.progress_apply(_try_add, axis=1)
        gdf.drop(columns=["rhino_geom"], inplace=True)  # don't carry around

        def move_to_layer(series):
            """Find the rhino3dm geometry for this series' guid and moves it to the correct layer.

            Shading if the template assignment is None, Buildings for the rest.
            """
            obj3dm = umi_project.file3dm.Objects.FindId(series.guid)
            if series["TemplateName"] is None:
                obj3dm.Attributes.LayerIndex = umi_project.umiLayers[
                    "umi::Context::Shading"
                ].Index
            else:
                obj3dm.Attributes.LayerIndex = umi_project.umiLayers[
                    "umi::Buildings"
                ].Index
            obj3dm.Attributes.Name = str(series[fid])

        def set_attributes(series):
            """Set GIS attributes as UserData."""
            # First, get the object.
            obj3dm = umi_project.file3dm.Objects.FindId(series.guid)
            # Then, iterate over series and assign.
            for k, v in series.iteritems():
                # Sets v as string on key k.
                obj3dm.Attributes.SetUserString(k, str(v))

        umi_project.add_default_shoebox_settings()

        umi_project.update_umi_sqlite3()

        # Set UserData Attributes on Breps
        tqdm.pandas(desc="Setting attributes to Breps")
        umi_project.gdf_3dm.progress_apply(set_attributes, axis=1)

        # Move Breps to layers (Buildings or Shading)
        tqdm.pandas(desc="Moving Breps on layers")
        umi_project.gdf_3dm.progress_apply(move_to_layer, axis=1)

        return umi_project

    @classmethod
    def from_cityjson(
        cls,
        input_file,
        height_column_name,
        epw,
        template_lib,
        template_map,
        map_to_column,
        fid=None,
        to_crs=None,
        **kwargs,
    ):
        """Todo Complete docstring.

        Args:
            input_file (path_or_buffer): cityjson buffer or path.
            height_column_name:
            epw:
            template_lib:
            template_map:
            map_to_column:
            fid:
            to_crs:
            **kwargs:

        Todo (@jszczesniak):
            - Complete Tests in tests.test_core.TestUmiProject.test_from_cityjson
            - Document method parameters following Google style docstrings: `pyguide`_

        Returns:

        .. _pyguide:
            https://google.github.io/styleguide/pyguide.html
        """
        pass

    def update_umi_sqlite3(self):
        """Update the self.umi_sqlite3 with self.gdf_3dm.

        Returns:
            UmiProject: self
        """
        nonplot_settings = [
            "TemplateName",
            "EnergySimulatorName",
            "FloorToFloorStrict",
        ]

        # First, update plottable settings
        _df = self.gdf_3dm.loc[
            :,
            [
                attr
                for attr in self.DEFAULT_SHOEBOX_SETTINGS
                if attr not in nonplot_settings
            ]
            + ["guid"],  # guid needed in sql
        ]
        _df = (
            (_df.melt("guid", var_name="name").rename(columns={"guid": "object_id"}))
            .astype({"object_id": "str"})
            .dropna(subset=["value"])
        )
        _df.to_sql(
            "plottable_setting",
            index=True,
            index_label="key",
            con=self.umi_sqlite3,
            if_exists="replace",
            # method="multi",
        )  # write to sql, replace existing

        # Second, update non-plottable settings
        _df = self.gdf_3dm.loc[
            :,
            [attr for attr in nonplot_settings] + ["guid"],
            # guid needed in sql
        ]
        _df = (
            (_df.melt("guid", var_name="name").rename(columns={"guid": "object_id"}))
            .astype({"object_id": "str"})
            .dropna(subset=["value"])
        )
        _df.to_sql(
            "nonplottable_setting",
            index=True,
            index_label="key",
            con=self.umi_sqlite3,
            if_exists="replace",
            # method="multi",
        )  # write to sql, replace existing
        return self

    def add_default_shoebox_settings(self):
        """Adds default values to self.gdf_3dm.

        If values are already defined, only NaNs are replace.

        Returns:
            UmiProject: self
        """
        bldg_attributes = self.DEFAULT_SHOEBOX_SETTINGS
        # First add columns if they don't exist with default values
        for attr in bldg_attributes:
            if attr not in self.gdf_3dm.columns:
                self.gdf_3dm[attr] = bldg_attributes[attr]

        # Then, fill NaNs with defaults, for good measure.
        self.gdf_3dm.fillna(value=bldg_attributes, inplace=True)

        return self

    def add_site_boundary(self):
        """Add Site boundary PolylineCurve.

        Uses the exterior of the convex_hull of the unary_union of all
        footprints. This is a good approximation of a site boundary in most
        cases.

        Returns:
            UmiProject: self
        """
        boundary = PolylineCurve(
            Point3dList(
                [
                    Point3d(x, y, 0)
                    for x, y, *z in self.gdf_3dm.geometry.unary_union.convex_hull.exterior.coords
                ]
            )
        )
        guid = self.file3dm.Objects.AddCurve(boundary)
        fileObj, *_ = filter(lambda x: x.Attributes.Id == guid, self.file3dm.Objects)
        fileObj.Attributes.LayerIndex = self.umiLayers[
            "umi::Context::Site boundary"
        ].Index
        fileObj.Attributes.Name = "Convex hull boundary"

        return self

    @classmethod
    def open(cls, filename, origin_unset=None, fast_open=False):
        """Reads an UmiProject from file.

        Hint:
            Managing Projections: The UmiProject is loaded by reading the
            file "sdl-common/project.json", a geojson representation of the
            project. Sometimes, the geometries have been moved to the rhino
            origin, effectively losing their position in the real world. The
            `origin_unset` parameter (either defined as a parameter of
            :meth:`UmiProject.open` or in the
            "sdl-common/project-settings.json" is used to translate back the
            geometries.

        Examples:
            >>> from pyumi.umi_project import UmiProject
            >>> umi = UmiProject.open("tests/oshkosh_demo.umi")

        Args:
            fast_open (bool): If True, speeds up open by not reading the
                sqlite file.
            filename (str or Path): The filename to open.
            origin_unset (tuple): A tuple of (lat, lon) Used to move the
                project to a known geographic location. This can be used to
                translate rhino geometries back to meaningful cartesian
                coordinates.

        Returns:
            UmiProject: The loaded UmiProject
        """
        filename = Path(filename)
        project_name = filename  # Keep path in project name (easier for save)
        # with unziped file load in the files
        with ZipFile(filename) as umizip:
            # 1. Read the 3dm file. Needs a temp directory because cannot be
            # read in memory.
            with tempfile.TemporaryDirectory() as tempdir:
                # extract and load file3dm
                file3dm, *_ = (
                    file for file in umizip.namelist() if file.endswith(".3dm")
                )
                umizip.extract(file3dm, tempdir)
                file3dm = File3dm.Read(Path(tempdir) / file3dm)

            # 2. Parse the weather file as :class:`Epw`
            epw_file = next(
                (file for file in umizip.namelist() if ".epw" in file), None
            )
            if epw_file:
                with umizip.open(epw_file, mode="r") as f:
                    epw = Epw.from_file_string(f.read().decode())
            else:
                epw = None  # maybe there is no epw in the zip folder

            # 3. Parse the templates library.
            tmp_lib = next(
                (
                    file
                    for file in umizip.namelist()
                    if ".json" in file and "sdl-common" not in file
                ),
                None,
            )
            if tmp_lib:
                with umizip.open(tmp_lib) as f:
                    template_lib = json.load(f)
            else:
                template_lib = None  # maybe there is no template_lib in the zip folder

            # 4. make connection with umi.sqlite3
            with umizip.open("umi.sqlite3") as f:
                dump = tempfile.NamedTemporaryFile("wb", delete=False)
                dump.write(f.read())  # dump to file
                dump.close()
                try:
                    source = connect(dump.name)  # read source
                    con = connect(":memory:")  # create memory db
                    source.backup(con)  # backup (like a copy)
                except ConnectionError:
                    pass
                finally:
                    dump.close()

            # 5. Parse all the .json files in "sdl-common" folder
            sdl_common = {}  # prepare sdl_common dict
            shoeboxes = ShoeBoxCollection()

            # loop over 'sdl-common' config files (.json)
            for file in [
                file for file in umizip.infolist() if "sdl-common" in file.filename
            ]:
                if file.filename.endswith("project.json"):
                    # This is the geojson representation of the
                    # project.

                    # First, figure out the utm_crs for the weather location
                    lat, lon = epw.location.latitude, epw.location.longitude
                    utm_zone = int(math.floor((float(lon) + 180) / 6.0) + 1)
                    utm_crs = CRS.from_string(
                        f"+proj=utm +zone={utm_zone} +ellps=WGS84 "
                        f"+datum=WGS84 +units=m +no_defs"
                    )
                    # Second, load the GeoDataFrame
                    with umizip.open(file) as gdf:
                        gdf_3dm = GeoDataFrame.from_file(gdf)
                        gdf_3dm._crs = utm_crs
                elif file.filename.endswith("energy.zip"):
                    # We load the IDF models
                    with umizip.open(file) as zfiledata:
                        with ZipFile(zfiledata) as energy_zip:
                            for sample in energy_zip.infolist():
                                shoeboxes[
                                    str(Path(sample.filename).expand())
                                ] = ShoeBox(
                                    StringIO(energy_zip.open(sample).read().decode()),
                                    epw=StringIO(epw.to_file_string()),
                                    as_version="8.4",
                                )
                else:
                    with umizip.open(file) as f:
                        try:
                            sdl_common[
                                Path(file.filename.replace("\\", "/")).stem
                            ] = json.load(f)
                        except JSONDecodeError:  # todo: deal with xml
                            sdl_common[Path(file.filename.replace("\\", "/")).stem] = {}

        # Before translating the geometries, resolve the
        # origin_unset value
        try:
            # First, look in project-settings
            xoff, yoff = sdl_common["project-settings"]["OriginalProjectedOrigin"]
        except KeyError:
            # Not defined in project-settings
            if origin_unset is None:
                # then use weather file location
                lat, lon = epw.location.latitude, epw.location.longitude
                log.warning(
                    "Since no 'origin_unset' is specified in the "
                    "project-settings, the world location is set to the "
                    f"weather file location: lat {lat}, lon {lon}"
                )
            else:
                # origin_unset is defined in the constructor
                lat, lon = origin_unset  # unpack into lat lon variables
            # Create the origin_unset geometry. Point takes the lon,
            # lat (reverse!)
            origin_unset = (
                GeoSeries(
                    [shapely.geometry.Point(lon, lat)],
                    name="origin_unset",
                    crs="EPSG:4326",
                )
                .to_crs(utm_crs)
                .geometry[0]
            )
            xoff, yoff = origin_unset.x, origin_unset.y
        else:
            log.debug(f"origin-unset of {xoff}, {yoff} read from project-settings")

        # add back in the "project-settings"
        sdl_common["project-settings"]["OriginalProjectedOrigin"] = (xoff, yoff)

        gdf_world_projected = gdf_3dm.copy()
        gdf_world_projected.geometry = gdf_world_projected.translate(xoff, yoff)

        gdf_world = project_gdf(gdf_world_projected, to_latlong=True)

        umi_layers = UmiLayers(file3dm)

        return cls(
            project_name,
            epw=epw,
            template_lib=template_lib,
            file3dm=file3dm,
            gdf_world=gdf_world,
            gdf_world_projected=gdf_world_projected,
            gdf_3dm=gdf_3dm,
            umi_layers=umi_layers,
            to_crs=CRS.from_user_input(utm_crs),
            fid="id",
            sdl_common=sdl_common,
            umi_sqlite=con,
            fast_open=fast_open,
            shoeboxes=shoeboxes,
        )

    def export(self, filename, driver="GeoJSON", schema=None, index=None, **kwargs):
        """Write the ``UmiProject`` to another file format.

        The :attr:`UmiProject.gdf_3dm` is first translated back to the
        :attr:`UmiProject.world_gdf_projected.centroid` and then reprojected
        to the :attr:`UmiProject.world_gdf._crs`. By default, a GeoJSON is
        written, but any OGR data source supported by Fiona can be written.
        A dictionary of supported OGR
        providers is available via:

        >>> import fiona
        >>> fiona.supported_drivers

        Args:
            filename (str): File path or file handle to write to.
            driver (str): The OGR format driver used to write the vector
                file. Deaults to "GeoJSON".
            schema (dict): If specified, the schema dictionary is passed to
                Fiona to better control how the file is written.
            index (bool): If True, write index into one or more columns
                (for MultiIndex). Default None writes the index into one or
                more columns only if the index is named, is a MultiIndex,
                or has a non-integer data type. If False, no index is written.

        Notes:
            The extra keyword arguments ``**kwargs`` are passed to
            :meth:`fiona.open`and can be used to write to multi-layer data,
            store data within archives (zip files), etc.

            The format drivers will attempt to detect the encoding of your
            data, but may fail. In this case, the proper encoding can be
            specified explicitly by using the encoding keyword parameter,
            e.g. ``encoding='utf-8'``.

        Examples:
            >>> from pyumi.umi_project import UmiProject
            >>> UmiProject().export("project name", driver="ESRI Shapefile")
            Or
            >>> from pyumi.umi_project import UmiProject
            >>> UmiProject().export("project name", driver="GeoJSON")

        Returns:
            None
        """
        world_crs = self.gdf_world._crs  # get utm crs
        exp_gdf = self.gdf_3dm.copy()  # make a copy

        dtype_map = {self.fid: str}  # UUIDs as string
        if "guid" in exp_gdf.columns:
            # not all gdfs have a guid column; fix dtype here in this case.
            dtype_map.update({"guid": str})

        # apply type map
        exp_gdf.loc[:, list(dtype_map)] = exp_gdf.astype(dtype_map)

        # extract centroid coordinates
        xdiff, ydiff = self.gdf_world_projected.unary_union.centroid.coords[0]

        # translate gdf back to its location on earth
        exp_gdf.geometry = exp_gdf.translate(xdiff, ydiff)

        # Project the gdf to the world_crs
        from osmnx import project_gdf

        exp_gdf = project_gdf(exp_gdf, world_crs)

        # Convert to file. Uses fiona
        if driver in fiona_drivers:
            exp_gdf.to_file(
                filename=filename,
                driver=driver,
                schema=schema,
                index=index,
                **kwargs,
            )
        elif driver in PYUMI_DRIVERS:
            pass  # Todo: implement export drivers here
        else:
            raise NotImplementedError(f"The drive {driver} is not supported.")

    def save(self, filename=None):
        """Saves the UmiProject to a packaged .umi file (zipped folder).

        Args:
            filename (str or Path): Optional, the path to the destination.
                May or may not contain the extension (.umi).

        Returns:
            UmiProject: self
        """
        if filename:  # a specific filename is passed
            dst = Path(filename).dirname()  # set dir path
            self.name = Path(filename)  # update project name
            name = Path(filename).stem
        else:
            dst = Path(self.name).dirname()
            name = Path(self.name).stem

        # export needed class attributes to outfile
        outfile = (dst / name + ".umi").expand()
        with ZipFile(outfile, "w", zipfile.ZIP_DEFLATED) as zip_archive:

            # 1. Save the file3dm object to the archive.
            if self.file3dm is not None:
                self.file3dm.Write(name + ".3dm", 6)  # save to file
                zip_archive.write(name + ".3dm", (name + ".3dm"))
                os.remove(name + ".3dm")  # delete the file

            # 2. Save the epw object to the archive
            if self.epw:
                epw_archive = ZipInfo(str(self.epw.name))
                zip_archive.writestr(epw_archive, self.epw.as_str())

            # 3. Save the template-library to the archive
            if self.template_lib:
                lib_archive = ZipInfo("template-library.json")
                zip_archive.writestr(
                    lib_archive, json.dumps(self.template_lib, indent=3)
                )  # Todo: Eventually use archetypal here

            # 4. Save all the sdl-common objects to the archive
            for k, v in self.sdl_common.items():
                k_archive = ZipInfo(f"sdl-common/{k}" + ".json")
                zip_archive.writestr(k_archive, json.dumps(v, indent=3))

            # 5. Save GeoDataFrame to archive
            if not self.gdf_3dm.empty:
                _json = self.gdf_3dm.to_json(cls=ComplexEncoder)
                response = json.loads(_json)
                gdf_3dm_archive = ZipInfo("sdl-common/project.json")
                zip_archive.writestr(gdf_3dm_archive, json.dumps(response))

            # 6. Commit sqlite3 db changes and copy to archive
            self.umi_sqlite3.commit()  # commit db changes
            db_archive = ZipInfo("umi.sqlite3")
            dest = connect("umi-archive.sqlite3")
            self.umi_sqlite3.backup(dest)
            dest.close()
            zip_archive.write("umi-archive.sqlite3", db_archive.filename)
            os.remove("umi-archive.sqlite3")

            # 7. Save the Energy+ files
            if self.shoeboxes is not None:
                zip_buffer = io.BytesIO()
                with ZipFile(zip_buffer, "a", zipfile.ZIP_STORED) as f:
                    idf: IDF
                    for k, idf in self.shoeboxes.items():
                        idfname = ZipInfo(k)
                        f.writestr(idfname, idf.idfstr())
                energy_zip = ZipInfo("sdl-common/energy.zip")
                zip_archive.writestr(energy_zip, zip_buffer.getvalue())

        log.info(f"Saved to {outfile.abspath()}")

        return self

    def add_street_graph(
        self,
        polygon=None,
        network_type="all_private",
        simplify=True,
        retain_all=False,
        truncate_by_edge=False,
        clean_periphery=True,
        custom_filter=None,
        on_file3dm_layer=None,
    ):
        """Download a spatial street graph from OpenStreetMap's APIs.

        Transforms the graph to PolylineCurves to the self.file3dm document.
        Uses :ref:`osmnx` to retrieve the street graph. The same parameters
        as :met:`osmnx.graph.graph_from_polygon` are available.

        Args:
            polygon (Polygon or MultiPolygon, optional): If none, the extent
                of the project GIS dataset is used (convex hull). If not
                None, polygon is the shape to get network data within.
                coordinates should be in units of latitude-longitude degrees.
            network_type (string): what type of street network to get if
                custom_filter is None. One of 'walk', 'bike', 'drive',
                'drive_service', 'all', or 'all_private'.
            simplify (bool): if True, simplify the graph topology with the
                simplify_graph function
            retain_all (bool): if True, return the entire graph even if it
                is not connected. otherwise, retain only the largest weakly
                connected component.
            truncate_by_edge (bool): if True, retain nodes outside boundary
                polygon if at least one of node's neighbors is within the
                polygon
            clean_periphery (bool): if True, buffer 500m to get a graph
                larger than requested, then simplify, then truncate it to
                requested spatial boundaries
            custom_filter (string): a custom network filter to be used
                instead of the network_type presets, e.g.,
                '["power"~"line"]' or '["highway"~"motorway|trunk"]'. Also
                pass in a network_type that is in
                settings.bidirectional_network_types if you want graph to be
                fully bi-directional.
            on_file3dm_layer (str, or Layer): specify on which file3dm layer
                the pois will be put. Defaults to umi::Context.

        Examples:
            >>> # Given an UmiProject umi,
            >>> umi.add_street_graph(
            >>>     network_type="all_private",
            >>>     retain_all=True,
            >>>     clean_periphery=False,
            >>> ).save()

            Do not forget to save!

        Returns:
            UmiProject: self
        """
        import osmnx as ox

        # Configure osmnx
        ox.config(log_console=False, use_cache=True, log_name=log.name)

        if polygon is None:
            # Create the boundary polygon. Here we use the convex_hull
            # polygon : shapely.geometry.Polygon or
            # shapely.geometry.MultiPolygon the shape to get network data
            # within. coordinates should be in units of latitude-longitude
            # degrees.
            polygon = self.gdf_world.unary_union.convex_hull

        # Retrieve the street graph from OSM
        self.street_graph = ox.graph_from_polygon(
            polygon,
            network_type,
            simplify,
            retain_all,
            truncate_by_edge,
            clean_periphery,
            custom_filter,
        )
        if is_empty(self.street_graph):
            log.warning("No street graph found for location. Check your projection")
            return self
        # Project to UmiProject crs
        street_graph = project_graph(self.street_graph, self.to_crs)

        # Convert graph to edges with geom info (GeoDataFrame)
        gdf_nodes, gdf_edges = ox.graph_to_gdfs(street_graph, nodes=True, edges=True)

        # Move to 3dm origin
        gdf_edges.geometry = gdf_edges.translate(
            -self.gdf_world_projected.unary_union.centroid.x,
            -self.gdf_world_projected.unary_union.centroid.y,
        )
        # Move to 3dm origin
        gdf_nodes.geometry = gdf_nodes.translate(
            -self.gdf_world_projected.unary_union.centroid.x,
            -self.gdf_world_projected.unary_union.centroid.y,
        )
        # Parse geometries
        if not on_file3dm_layer:
            on_file3dm_layer = self.umiLayers["umi::Context::Streets"]
        if isinstance(on_file3dm_layer, str):
            on_file3dm_layer = self.umiLayers[on_file3dm_layer]

        tqdm.pandas(desc="Adding street nodes to file3dm")
        guids = gdf_nodes.progress_apply(
            resolve_3dm_geom,
            args=(self.file3dm, on_file3dm_layer, "osmid"),
            axis=1,
        )

        tqdm.pandas(desc="Adding street edges to file3dm")
        guids = gdf_edges.progress_apply(
            resolve_3dm_geom,
            args=(self.file3dm, on_file3dm_layer, "osmid"),
            axis=1,
        )

        # todo: Add generated guids somewhere for reference

        return self

    def add_pois(self, polygon=None, tags=None, on_file3dm_layer=None):
        """Add points of interests (POIs) from OpenStreetMap.

        Args:
            polygon (Polygon or Multipolygon): geographic boundaries to
                fetch geometries within. Units should be in degrees.
            tags (dict): Dict of tags used for finding POIs from the selected
                area. Results returned are the union, not intersection of each
                individual tag. Each result matches at least one tag given.
                The dict keys should be OSM tags, (e.g., amenity, landuse,
                highway, etc) and the dict values should be either True to
                retrieve all items with the given tag, or a string to get a
                single tag-value combination, or a list of strings to get
                multiple values for the given tag. For example, tags = {
                ‘amenity’:True, ‘landuse’:[‘retail’,’commercial’],
                ‘highway’:’bus_stop’} would return all amenities,
                landuse=retail, landuse=commercial, and highway=bus_stop.
            on_file3dm_layer (str, or Layer): specify on which file3dm layer
                the pois will be put. Defaults to umi::Context.

        Examples:
            >>> # Given an UmiProject umi,
            >>> umi.add_pois(
            >>>     tags=dict(
            >>>        natural=["tree_row", "tree", "wood"],
            >>>        trees=True
            >>>     ),
            >>>     on_file3dm_layer="umi::Context::Trees",
            >>> ).save()

        Returns:
            UmiProject: self
        """
        import osmnx as ox

        # Configure osmnx
        ox.config(log_console=False, use_cache=True, log_name=log.name)

        if polygon is None:
            # Create the boundary polygon. Here we use the convex_hull
            # polygon : shapely.geometry.Polygon or
            # shapely.geometry.MultiPolygon the shape to get network data
            # within. coordinates should be in units of latitude-longitude
            # degrees.
            polygon = self.gdf_world.unary_union.convex_hull

        # Retrieve the pois from OSM
        gdf = geometries_from_polygon(polygon, tags=tags)
        if gdf.empty:
            log.warning("No pois found for location. Check your tags")
            return self
        # Project to UmiProject crs
        gdf = ox.project_gdf(gdf, self.to_crs)

        # Move to 3dm origin
        gdf.geometry = gdf.translate(
            -self.gdf_world_projected.unary_union.centroid.x,
            -self.gdf_world_projected.unary_union.centroid.y,
        )
        # Parse geometries
        if not on_file3dm_layer:
            on_file3dm_layer = self.umiLayers.add_layer("umi::Context::POIs")
        if isinstance(on_file3dm_layer, str):
            on_file3dm_layer = self.umiLayers[on_file3dm_layer]

        tqdm.pandas(desc="Adding POIs to file3dm")
        guids = gdf.progress_apply(
            resolve_3dm_geom,
            args=(self.file3dm, on_file3dm_layer, "osmid"),
            axis=1,
        )

        # todo: Add generated guids somewhere for reference

        return self


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


def _dict_depth(dic, level=1):
    """Find depth of a dictionary."""
    if not isinstance(dic, dict) or not dic:
        return level
    return max(_dict_depth(dic[key], level + 1) for key in dic)


class ComplexEncoder(json.JSONEncoder):
    """A json encoder extension."""

    def default(self, obj):
        """Function that gets called for objects that can't otherwise be serialized."""
        if isinstance(obj, uuid.UUID):
            return str(obj)
        elif isinstance(obj, Brep):
            return None
        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)


class Energy:
    """A class to handle reporting energy results from the Energy Module."""

    _umi_project: UmiProject

    def __init__(self, umi_project):
        """Construct :class:`UmiProject` object."""
        self._umi_project = umi_project

    def __repr__(self):
        """Repr."""
        series = [key for key in self.__dict__.keys() if not key.startswith("_")]
        totals = [(key, f"{getattr(self, key).sum().sum():.0f}") for key in series]
        tab = tabulate(totals, ("Available Series", "Totals"))
        return tab

    def __getitem__(self, item):
        """Get item."""
        return self.__dict__[item]

    def _results(self):
        if self._df is None:
            con = self._umi_project.umi_sqlite3
            self._df = pd.read_sql(sql="select * from series", con=con)
        return self._df

    def _get_series(self):
        """Retrieve energy results and save them to the db."""
        # First get the distinct set of (name, units, resolution).
        series_names = self._umi_project.umi_sqlite3.execute(
            """select distinct name, units, resolution from series"""
        )

        # Then for each, retrieve DataFrame and create class attribute.
        for name, units, resolution, *_ in series_names:
            _name = re.sub(r"[^a-zA-Z0-9\n\.]", "_", name)  # valid name
            series_name = "_".join([resolution, _name]) if resolution else _name

            # Skip cases where units are defined but not the resolution, e.g.:
            # ('SDL/Domestic Hot Water', 'kWh', None) because this is an UMI bug.
            if units and not resolution:
                continue

            # sql query: takes in a couple columns from the 'series' and
            # joins in the data_point which contains the values and the
            # object_name_assignment which contains the building names.
            ts = pd.read_sql(
                """select object_id, 
                index_in_series, ona.name, value from series 
                join data_point dp on series.id = dp.series_id 
                join object_name_assignment ona on series.object_id = ona.id 
                where series.name is ? and series.resolution is ? and 
                series.units is ?""",
                con=self._umi_project.umi_sqlite3,
                params=(name, resolution, units),
            )
            # Dataframe is pivoted so that index_in_series is the index,
            # name is the column and value is the values. Since object_id is
            # therefore aggregated (sum) under names (could have more than
            # one object_id for the same 'name'
            ts = ts.pivot_table(
                index=["index_in_series"],
                columns=["name"],
                values=["value"],
                aggfunc=sum,
            )
            ts = ts.droplevel(0, axis=1)  # Drop the top level of
            # column axis because it does not offer any info.

            # create DatetimeIndex if time series
            if ts.index.size >= 12:
                # anything below would not be a time series
                ts.index = date_range(
                    start="2017-01-01",
                    periods=ts.index.size,
                    freq=resolution[0],  # take first letter of resolution
                )

                # Todo: Change start date based on fist day of week set in
                #  Weather file
            if isinstance(ts, pd.Series):
                es = EnergySeries(ts, units=units)
            elif isinstance(ts, pd.DataFrame):
                es = EnergyDataFrame(ts, units=units)
            else:
                raise ValueError()
            setattr(self, series_name, es)
