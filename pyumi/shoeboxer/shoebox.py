"""Shoebox class."""

import logging

from archetypal import IDF
from archetypal.template import BuildingTemplate

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
        cls, building_template, system="SimpleIdealLoadsSystem", ddy_file=None, **kwargs
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
            height=3,
            num_stories=1,
        )
        # Create Perimeter Box
        idf.add_block(
            name="Perim",
            coordinates=[(10, 5), (10, 10), (0, 10), (0, 5)],
            height=3,
            num_stories=1,
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
        idf.set_wwr(construction=window.Name, wwr_map=wwr_map, force=True)

        if ddy_file:
            idf.add_sizing_design_day(ddy_file)

        # add ground temperature
        idf.newidfobject(
            "Site:GroundTemperature:BuildingSurface".upper(),
            January_Ground_Temperature=18,
        )

        # Heating System; create one for each zone.
        for zone, zoneDefinition in zip(
            idf.idfobjects["ZONE"],
            [building_template.Core, building_template.Perimeter],
        ):
            HVACTemplates[system].create_from(zone, zoneDefinition)
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
