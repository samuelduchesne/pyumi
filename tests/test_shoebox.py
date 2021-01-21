import pytest
from archetypal import UmiTemplateLibrary

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

    def test_form_template(self, building_template):
        sb = ShoeBox.from_template("test.idf", building_template)
        sb.simulate(
            epw="tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw",
            expandobjects=True, annual=True
        )
