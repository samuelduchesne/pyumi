import tempfile
import time
from sqlite3 import connect
from zipfile import ZipFile

import geopandas as gpd
from geopandas import GeoSeries
from path import Path
from rhino3dm import *
import logging as lg
from tqdm import tqdm, tqdm_notebook
import numpy as np

# Create and register a new `tqdm` instance with `pandas`
# (can use tqdm_gui, optional kwargs, etc.)
tqdm.pandas()


def geom_to_curve(feature):
    """Converts the GeoSeries to a :class:`rhino3dm.PolylineCurve`

    Args:
        feature (GeoSeries):

    Returns:
        PolylineCurve
    """
    # Todo: add interiors and planar check

    return PolylineCurve(
        Point3dList(
            [Point3d(x, y, 0) for x, y, *z in feature.geometry.exterior.coords]
        )
    )


def polylinecurve_to_brep(feature, geom_column_name, height_column_name):
    """Converts the polyline curve to a brep

    Args:
        feature (GeoSeries):
        geom_column_name (str): Name of the colum containing the polylinecurve
            geometry.
        height_column_name (str): Name of the column containing the height
            attribute.

    Returns:
        Extrusion: The Rhino Extrusion
    """
    # Create the extrusion using the height attr. For some reason,
    # value must be negative for the extrusion to go upwards.
    _ext = Extrusion.Create(
        feature[geom_column_name],
        height=-feature[height_column_name],
        cap=True,
    )

    if _ext:
        # If Extrusion did not fail, create Brep
        _brep = _ext.ToBrep(False)
    else:
        # Else return NaN and deal outside this function.
        _brep = np.NaN
    return _brep


class UmiFile:
    def __init__(self, project_name="unnamed", epw=None, template_lib=None):
        """An UmiFile pacakge containing the rhino3dm file, the project
        settings, the umi.sqlite3 database.

        Args:
            project_name (str): The name of the project
            epw (str or Path): Path of the weather file.
            template_lib (str or Path):
        """
        self.tmp = Path(tempfile.mkdtemp(dir=Path("")))

        self.name = project_name
        self.rhino3dm = None
        self.umi_sqlite3 = None
        self.template_lib = template_lib
        self.epw = epw

        with connect(self.tmp / "umi.sqlite3") as con:
            con.execute(create_nonplottable_setting)
            con.execute(create_object_name_assignement)
            con.execute(create_plottatble_setting)
            con.execute(create_series)
            con.execute(create_data_point)

    @property
    def epw(self):
        return self._epw

    @epw.setter
    def epw(self, value):
        """
        Args:
            value:
        """
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

    def __del__(self):
        self.tmp.rmtree_p()

    @classmethod
    def from_gis(
        cls,
        input_file,
        height_column_name,
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
            **kwargs (dict): keyword arguments passed to UmiFile constructor.
        """
        if to_crs is None:
            to_crs = {'init': 'epsg:3857'}
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
        gdf["rhino_geom"] = gdf.progress_apply(geom_to_curve, axis=1)
        gdf["rhino_geom"] = gdf.progress_apply(
            polylinecurve_to_brep,
            axis=1,
            args=("rhino_geom", height_column_name),
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

        # Create blank 3DM file
        threedm = File3dm()

        # Set ModelUnitSystem to Meters
        threedm.Settings.ModelUnitSystem = (
            threedm.Settings.ModelUnitSystem.Meters
        )

        # Add all Breps to Model and append UUIDs to gdf
        gdf["guid"] = gdf["rhino_geom"].apply(threedm.Objects.AddBrep)

        # create the UmiFile object
        epw = kwargs.pop("epw", "USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
        name = kwargs.pop("name", input_file.stem)
        umi = cls(project_name=name, epw=epw)

        # save 3dm file to UmiFile.tmp dir
        threedm.Write(umi.tmp / (umi.name + ".3dm"), 6)

        # save UmiFile to created package.
        umi.save()
        return umi

    def open(self):
        pass

    def save(self):
        outfile = Path(self.name) + ".umi"
        with ZipFile(outfile, "w") as zip_file:
            for file in self.tmp.files():
                # write `file` to arcname `file.basename()`
                zip_file.write(file, file.basename())

        lg.info(f"Saved to {(Path(self.name) + '.umi').abspath()}")


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
    id         INTEGER
        primary key,
    name       TEXT not null,
    module     TEXT not null,
    object_id  TEXT not null,
    units      TEXT,
    resolution TEXT,
    unique (name, module, object_id)
);"""

create_data_point = """create table data_point
(
    series_id       INTEGER not null
        references series
            on delete cascade,
    index_in_series INTEGER not null,
    value           REAL    not null,
    primary key (series_id, index_in_series)
);"""
