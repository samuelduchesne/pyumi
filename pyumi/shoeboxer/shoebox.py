"""Shoebox class."""
from archetypal import IDF
from archetypal.template import BuildingTemplate, ZoneConstructionSet
from archetypal.umi_template import traverse
from eppy.bunch_subclass import EpBunch
from opyplus.epm.epm import Epm
import logging

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

    def __init__(self, *args, **kwargs):
        super(ShoeBox, self).__init__(*args, **kwargs)
        pass

    @classmethod
    def from_template(cls, name, building_template, **kwargs):
        """

        Args:
            building_template (BuildingTemplate):

        Returns:
            ShoeBox: A shoebox for this building_template
        """
        idf = cls.minimal(name=name, **kwargs)

        idf.add_block(
            name="Core",
            coordinates=[(10, 0), (10, 5), (0, 5), (0, 0)],
            height=3,
            num_stories=1,
        )
        idf.add_block(
            name="Perim",
            coordinates=[(10, 5), (10, 10), (0, 10), (0, 5)],
            height=3,
            num_stories=1,
        )

        idf.intersect_match()

        # Constructions
        idf.set_default_constructions()

        # Heating System
        stat = idf.newidfobject(
            "HVACTEMPLATE:THERMOSTAT",
            Name="Zone Stat",
            Constant_Heating_Setpoint=20,
            # easy to change to Heating_Setpoint_Schedule_Name
            Constant_Cooling_Setpoint=25,
            # easy to change to Cooling_Setpoint_Schedule_Name
        )

        for zone in idf.idfobjects["ZONE"]:
            idf.newidfobject(
                "HVACTEMPLATE:ZONE:IDEALLOADSAIRSYSTEM",
                Zone_Name=zone.Name,
                Template_Thermostat_Name=stat.Name,
            )
        return idf

    @classmethod
    def minimal(cls, name=None, **kwargs):
        """

        BUILDING, GlobalGeometryRules, LOCATION and DESIGNDAY (or RUNPERIOD) are the
        absolute minimal required input objects.

        Args:
            name (str): Name of the Shoebox
            **kwargs:

        Returns:

        """
        idf = cls(name=name, **kwargs)

        idf.newidfobject("BUILDING", Name="None")
        idf.newidfobject(
            "GLOBALGEOMETRYRULES",
            Starting_Vertex_Position="UpperLeftCorner",
            Vertex_Entry_Direction="CounterClockWise",
            Coordinate_System="World",
        )
        # idf.newidfobject("SITE:LOCATION")
        idf.newidfobject(
            "RUNPERIOD",
            Name="Run Period 1",
            Begin_Month=1,
            Begin_Day_of_Month=1,
            End_Month=12,
            End_Day_of_Month=31,
        )
        idf.newidfobject("SIMULATIONCONTROL")

        return idf
