import logging as lg

import pytest
from path import Path

from pyumi.core import UmiFile


class TestCore:
    lg.basicConfig(filename="pyumi.log", level=lg.INFO)

    @pytest.fixture()
    def attributes(self):
        """Creates a dictionary of {gdf_attribute:template_name}. This is
        specific to the `pyumi/tests/oshkosh_demo.zip"` file.
        """
        yield dict(COMMERCIAL="B_Off_0", RESIDENTIAL="B_Res_0_WoodFrame")

    @pytest.fixture()
    def multi_attributes(self):
        """Creates a dictionary of {gdf_attribute:template_name}. This is
        specific to the `pyumi/tests/oshkosh_demo.zip"` file.
        """
        yield dict(
            COMMERCIAL={1948: "B_Off_0", 2008: "B_Off_0"},
            RESIDENTIAL={1948: "B_Res_0_WoodFrame", 2008: "B_Res_0_Masonry"},
        )

    def test_from_gis(self, attributes):
        filename = "zip://" + Path("pyumi/tests/oshkosh_demo.zip")
        epw = Path("pyumi/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
        template_lib = Path("pyumi/tests/BostonTemplateLibrary.json")
        assert filename.exists()
        assert epw.exists()
        umi = UmiFile.from_gis(
            filename,
            "Height",
            epw=epw,
            template_lib=template_lib,
            template_map=attributes,
            map_to_column="Year_Built",
        )

        assert umi.name == "oshkosh_demo"

    def test_multilevel(self, multi_attributes):
        filename = Path("pyumi/tests/oshkosh_demo.geojson")
        epw = Path("pyumi/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
        template_lib = Path("pyumi/tests/BostonTemplateLibrary.json")
        assert filename.exists()
        assert epw.exists()
        umi = UmiFile.from_gis(
            filename,
            "Height",
            epw=epw,
            template_lib=template_lib,
            template_map=multi_attributes,
            map_to_column=["Use_Type", "Year_Built"],
        )
