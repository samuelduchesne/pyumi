"""Shoebox class."""
import logging
from typing import Optional

from archetypal import IDF
from archetypal.template.building_template import BuildingTemplate
from eppy.idf_msequence import Idf_MSequence
from geomeppy.recipes import (
    _has_correct_orientation,
    _is_window,
    window_vertices_given_wall,
)

from pyumi.shoeboxer.hvac_templates import HVACTemplates

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# create formatter
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# add formatter to ch
ch.setFormatter(formatter)

# add ch to logger
logger.addHandler(ch)


class ShoeBox(IDF):
    """Shoebox Model."""

    def __init__(self, *args, azimuth=180, **kwargs):
        """Initialize Shoebox."""
        super(ShoeBox, self).__init__(*args, **kwargs)
        self.azimuth = azimuth  # 0 is north

    @classmethod
    def minimal(cls, **kwargs):
        """Create the minimal viable IDF model.

        BUILDING, GlobalGeometryRules, LOCATION and DESIGNDAY (or RUNPERIOD) are the
        absolute minimal required input objects.

        Args:
            **kwargs: keyword arguments passed to the IDF constructor.

        Returns:
            ShoeBox: The ShoeBox model.
        """
        idf = cls(**kwargs)

        idf.newidfobject("BUILDING", Name=idf.name or "None")
        idf.newidfobject(
            "GLOBALGEOMETRYRULES",
            Starting_Vertex_Position="UpperLeftCorner",
            Vertex_Entry_Direction="CounterClockWise",
            Coordinate_System="World",
        )
        idf.newidfobject(
            "RUNPERIOD",
            Name="Run Period 1",
            Begin_Month=1,
            Begin_Day_of_Month=1,
            End_Month=12,
            End_Day_of_Month=31,
        )
        idf.newidfobject(
            "SIMULATIONCONTROL",
            Do_Zone_Sizing_Calculation="Yes",
            Do_System_Sizing_Calculation="Yes",
            Run_Simulation_for_Sizing_Periods="No",
            Do_HVAC_Sizing_Simulation_for_Sizing_Periods="Yes",
        )
        return idf

    @classmethod
    def from_template(
        cls,
        building_template,
        system="SimpleIdealLoadsSystem",
        ddy_file=None,
        height=3,
        number_of_stories=1,
        **kwargs
    ):
        """Create Shoebox from a template.

        Args:
            system (str): Name of HVAC system template. Default
                :"SimpleIdealLoadsSystem".
            building_template (BuildingTemplate):
            ddy_file:

        Returns:
            ShoeBox: A shoebox for this building_template
        """
        idf = cls.minimal(**kwargs)

        # Create Core box
        idf.add_block(
            name="Core",
            coordinates=[(10, 0), (10, 5), (0, 5), (0, 0)],
            height=height,
            num_stories=number_of_stories,
            zoning="by_storey",
            perim_depth=3,
        )
        # Create Perimeter Box
        idf.add_block(
            name="Perim",
            coordinates=[(10, 5), (10, 10), (0, 10), (0, 5)],
            height=height,
            num_stories=number_of_stories,
            zoning="by_storey",
            perim_depth=3,
        )
        # Join adjacent walls
        idf.intersect_match()

        # split roof and ceiling:

        # Constructions
        idf.set_default_constructions()

        # Add window construction
        window = building_template.Windows.Construction.to_epbunch(idf)

        # Set wwr
        wwr_map = {0: 0, 90: 0, 180: 0, 270: 0}  # initialize wwr_map for orientation.
        wwr_map.update({idf.azimuth: building_template.DefaultWindowToWallRatio})
        set_wwr(idf, construction=window.Name, wwr_map=wwr_map, force=False)

        if ddy_file:
            idf.add_sizing_design_day(ddy_file)

        # add ground temperature
        idf.newidfobject(
            "Site:GroundTemperature:BuildingSurface".upper(),
            January_Ground_Temperature=18,
        )

        # add internal gains
        zone_name = idf.idfobjects["ZONE"][0].Name
        building_template.Perimeter.Loads.to_epbunch(idf, zone_name)

        # Heating System; create one for each zone.
        for zone, zoneDefinition in zip(
            idf.idfobjects["ZONE"],
            [building_template.Core, building_template.Perimeter],
        ):
            HVACTemplates[system].create_from(zone, zoneDefinition)

        # infiltration, only `window` surfaces are considered.
        window_area = 0
        opening_area_ratio = building_template.Windows.OperableArea
        for zone in idf.idfobjects["ZONE"]:
            for surface in zone.zonesurfaces:
                for sub_surface in surface.subsurfaces:
                    if sub_surface.Surface_Type.lower() == "window":
                        window_area += sub_surface.area

        building_template.Perimeter.Ventilation.to_epbunch(
            idf, zone_name, opening_area=window_area * opening_area_ratio
        )
        return idf

    def add_sizing_design_day(self, ddy_file):
        """Read ddy file and copy objects over to self."""
        ddy = IDF(
            ddy_file, as_version="9.2.0", file_version="9.2.0", prep_outputs=False
        )
        for sequence in ddy.idfobjects.values():
            if sequence:
                for obj in sequence:
                    self.addidfobject(obj)
        del ddy


def set_wwr(
    idf, wwr=0.2, construction=None, force=False, wwr_map=None, orientation=None
):
    # type: (IDF, Optional[float], Optional[str], Optional[bool], Optional[dict], Optional[str]) -> None
    """Set the window to wall ratio on all external walls.

    :param idf: The IDF to edit.
    :param wwr: The window to wall ratio.
    :param construction: Name of a window construction.
    :param force: True to remove all subsurfaces before setting the WWR.
    :param wwr_map: Mapping from wall orientation (azimuth) to WWR, e.g. {180: 0.25, 90: 0.2}.
    :param orientation: One of "north", "east", "south", "west". Walls within 45 degrees will be affected.

    Todo: replace with original package method when PR is accepted.
    """
    try:
        ggr = idf.idfobjects["GLOBALGEOMETRYRULES"][0]  # type: Optional[Idf_MSequence]
    except IndexError:
        ggr = None

    # check orientation
    orientations = {
        "north": 0.0,
        "east": 90.0,
        "south": 180.0,
        "west": 270.0,
        None: None,
    }
    degrees = orientations.get(orientation, None)
    external_walls = filter(
        lambda x: x.Outside_Boundary_Condition.lower() == "outdoors",
        idf.getsurfaces("wall"),
    )
    external_walls = filter(
        lambda x: _has_correct_orientation(x, degrees), external_walls
    )
    subsurfaces = idf.getsubsurfaces()
    base_wwr = wwr
    for wall in external_walls:
        # get any subsurfaces on the wall
        wall_subsurfaces = list(
            filter(lambda x: x.Building_Surface_Name == wall.Name, subsurfaces)
        )
        if not all(_is_window(wss) for wss in wall_subsurfaces) and not force:
            raise ValueError(
                'Not all subsurfaces on wall "{name}" are windows. '
                "Use `force=True` to replace all subsurfaces.".format(name=wall.Name)
            )

        if wall_subsurfaces and not construction:
            constructions = list(
                {wss.Construction_Name for wss in wall_subsurfaces if _is_window(wss)}
            )
            if len(constructions) > 1:
                raise ValueError(
                    'Not all subsurfaces on wall "{name}" have the same construction'.format(
                        name=wall.Name
                    )
                )
            construction = constructions[0]
        # remove all subsurfaces
        for ss in wall_subsurfaces:
            idf.removeidfobject(ss)
        wwr = (wwr_map or {}).get(wall.azimuth, base_wwr)
        if not wwr:
            continue
        coords = window_vertices_given_wall(wall, wwr)
        window = idf.newidfobject(
            "FENESTRATIONSURFACE:DETAILED",
            Name="%s window" % wall.Name,
            Surface_Type="Window",
            Construction_Name=construction or "",
            Building_Surface_Name=wall.Name,
            View_Factor_to_Ground="autocalculate",  # from the surface angle
        )
        window.setcoords(coords, ggr)
