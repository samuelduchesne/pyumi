import uuid

import pytest
from archetypal import UmiTemplateLibrary
from shapely.geometry import Polygon, LineString

from pyumi.shoeboxer import ShoeBox

import logging

logging.getLogger(__name__)


class TestShoebox:
    @pytest.fixture()
    def template(self):
        yield UmiTemplateLibrary.open("tests/BostonTemplateLibrary.json")

    @pytest.fixture()
    def building_template(self, template):
        yield next(iter(template.BuildingTemplates))

    def test_from_template(self, building_template, template):
        name = "test.idf"
        sb = ShoeBox.from_template(
            building_template,
            ddy_file="tests/CAN_PQ_Montreal.Intl.AP.716270_CWEC.ddy",
            name=name,
        )
        sb.saveas(sb.name)
        sb.outputs.add_dxf().apply()
        sb.simulate(
            epw="tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw",
            expandobjects=True,
            design_day=False,
            annual=True,
            keep_data_err=True,
        )

        sb.view_model()
        sb.meters.OutputMeter.Heating__DistrictHeating.values().plot2d()
        sb.open_htm()
