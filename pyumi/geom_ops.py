"""Module to hangle various geometry operations."""
import logging

import numpy as np
import shapely
from rhino3dm import (
    Brep,
    Extrusion,
    Line,
    ObjectAttributes,
    Plane,
    Point3d,
    Point3dList,
    PolylineCurve,
)
from rhino3dm._rhino3dm import ObjectColorSource

log = logging.getLogger(__name__)


def extract_poly_coords(geom):
    """Extract geometry coordinates into a tuple (exterior, list of interiors)."""
    if geom.type == "Polygon":
        exterior_coords = geom.exterior.coords[:]
        interior_coords = []
        for interior in geom.interiors:
            interior_coords.append(interior.coords[:])
    elif geom.type == "MultiPolygon":
        exterior_coords = []
        interior_coords = []
        for part in geom:
            epc = extract_poly_coords(part)  # Recursive call
            exterior_coords.extend(epc[0])
            interior_coords.extend(epc[1])
    else:
        raise ValueError("Unhandled geometry type: " + repr(geom.type))
    return exterior_coords, interior_coords


def geom_to_brep(geom, from_elevation=0, to_elevation=0):
    """Convert a Shapely :class:`shapely.geometry.base.BaseGeometry` to a
    :class:`_file3dm.Brep`.

    Args:
        geom (shapely.geometry.base.BaseGeometry): An input Shapely Geometry object
            to extrude.
        from_elevation (float): The starting elevation (meters) of the extrusion.
            Defaults to 0 m (XY Plane).
        to_elevation (float): The ending elevation (meters) of the extrusion.
            Defaults to 0 m (XY Plane).

    Returns:
        Brep: An Extrusion or a PlanarSurface (as Breps).

        The returned object is an Extrusion if :attr:`to_elevation` is != 0,
        otherwise it is a PlanarSurface.
    """
    # If height is zero, then create face.
    if to_elevation <= 1e-12:
        return geom_to_face_with_hole(geom)
    # Converts the GeoSeries to a :class:`_file3dm.PolylineCurve`
    exterior, interiors = extract_poly_coords(geom)
    geom = shapely.geometry.Polygon(exterior, interiors)

    outerProfile = PolylineCurve(
        Point3dList([Point3d(x, y, 0) for x, y, *z in geom.exterior.coords])
    )
    innerProfiles = []
    for interior in geom.interiors:
        innerProfiles.append(
            PolylineCurve(
                Point3dList([Point3d(x, y, 0) for x, y, *z in interior.coords[::1]])
            )
        )

    if outerProfile is None or to_elevation <= 1e-12:
        return np.NaN

    plane = Plane.WorldXY()
    if not plane:
        return np.NaN

    path = Line(Point3d(0, 0, 0), Point3d(0, 0, to_elevation))
    if not path.IsValid or path.Length <= 1e-12:
        return np.NaN

    up = plane.YAxis
    curve = outerProfile.Duplicate()
    curve.ChangeDimension(2)

    extrusion = Extrusion()  # Initialize the Extrusion
    extrusion.SetOuterProfile(curve, True)  # Sets the outer profile

    # Sets the inner profiles, if they exist
    for profile in innerProfiles:
        curve = profile.Duplicate()
        curve.ChangeDimension(2)
        extrusion.AddInnerProfile(curve)

    # Set Path and Up
    extrusion.SetPathAndUp(path.From, path.To, up)

    # Transform extrusion to Brep
    brep = extrusion.ToBrep(False)

    return brep


def geom_to_face_with_hole(geom):
    """Convert a Polygon or Multipolygon to a Brep.

    The returned geometry is a trimmed plane, trimmed by the exterior
    ring of the input geometry (geom).

    Args:
        geom (shapely.geometry.Polygon or shapely.geometry.MultiPolygon: The
            geometry.

    Returns:
        Brep: The Brep object.

    Hint:
        Because of the limitations of the current version of rhino3dm.py,
        holes in a geometry will be ignored.

    See Also:
        :ref:`pyumi.umi_project.geom_to_brep`
    """
    # Define the vertices
    exterior, interiors = extract_poly_coords(geom)

    coords = [Point3d(x, y, 0) for x, y, *z in exterior]

    # Cannot create hole for now
    # for interior in interiors:
    #     coords += [Point3d(layer_name, y, 0) for layer_name, y, *z in interior]

    exterior_crv = PolylineCurve(Point3dList(coords[1:]))
    brep = Brep.CreateTrimmedPlane(
        Plane.WorldXY(),
        exterior_crv,
    )

    return brep


def resolve_3dm_geom(series, file3dm, on_file3dm_layer, fid):
    """Resolve a :class:`GeoSeries` to a rhino3dm object.

    Args:
        file3dm (File3dm): The File3dm object to build the geometry to.
        on_file3dm_layer (Layer): The Layer object where the goemetry is
            created.
        fid (str): The label name containing the name (or id) of the
            geometry.

    Returns:
        str: The created rhino geometry guid.

    Raises:
        NotImplementedError: If the geometry is not of type
            shapely.geometry.Point, shapely.geometry.Polygon,
            shapely.geometry.MultiPolygon or
            shapely.geometry.linestring.LineString
    """
    geom = series.geometry  # Get the geometry
    if isinstance(geom, shapely.geometry.Point):
        # if geom is a Point
        guid = file3dm.Objects.AddPoint(geom.x, geom.y, 0)
        geom3dm = file3dm.Objects.FindId(guid)
        geom3dm.Attributes.LayerIndex = on_file3dm_layer.Index
        geom3dm.Attributes.Name = str(getattr(series, fid, ""))
        return guid
    elif isinstance(geom, (shapely.geometry.Polygon, shapely.geometry.MultiPolygon)):
        # if geom is a Polygon
        geom3dm = geom_to_brep(geom, 0, 0)

        # Set the pois attributes
        geom3dm_attr = ObjectAttributes()
        geom3dm_attr.LayerIndex = on_file3dm_layer.Index
        geom3dm_attr.Name = str(getattr(series, fid, ""))
        geom3dm_attr.ObjectColor = getattr(series, "color", (205, 247, 201, 255))
        geom3dm_attr.ColorSource = ObjectColorSource.ColorFromObject

        guid = file3dm.Objects.AddBrep(geom3dm, geom3dm_attr)
        return guid
    elif isinstance(geom, shapely.geometry.linestring.LineString):
        geom3dm = _linestring_to_curve(geom)
        geom3dm_attr = ObjectAttributes()
        geom3dm_attr.LayerIndex = on_file3dm_layer.Index
        geom3dm_attr.Name = str(getattr(series, fid, ""))

        guid = file3dm.Objects.AddCurve(geom3dm, geom3dm_attr)
        return guid
    else:
        raise NotImplementedError(
            f"geometry ({fid}={getattr(series, fid)}) of type "
            f"{type(geom)} cannot be parsed as a rhino3dm object"
        )


def _linestring_to_curve(geom):
    geom3dm = PolylineCurve(Point3dList([Point3d(x, y, 0) for x, y, *z in geom.coords]))
    return geom3dm
