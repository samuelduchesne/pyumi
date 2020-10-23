import logging as lg

import pytest
from path import Path

from pyumi.core import UmiProject


class TestCore:
    lg.basicConfig(filename="pyumi.log", level=lg.INFO)

    depth2 = {"COMMERCIAL": "B_Off_0", "RESIDENTIAL": "B_Res_0_WoodFrame"}

    depth3 = {
        "COMMERCIAL": {1948: "B_Off_0", 2008: "B_Off_0"},
        "RESIDENTIAL": {1948: "B_Res_0_WoodFrame", 2008: "B_Res_0_Masonry"},
    }

    depth4 = {
        "COMMERCIAL": {1948: {"UMU": "B_Off_0"}, 2008: "B_Off_0"},
        "RESIDENTIAL": {
            1948: {"CMU": "B_Res_0_WoodFrame", "TR-10": "B_Res_0_Masonry"},
            2008: {"TR-10": "B_Res_0_Masonry"},
        },
    }

    def test_from_gis(self):
        filename = "zip://" + Path("pyumi/tests/oshkosh_demo.zip")
        epw = Path("pyumi/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
        template_lib = Path("pyumi/tests/BostonTemplateLibrary.json")
        assert epw.exists()
        umi = UmiProject.from_gis(
            filename,
            "Height",
            epw=epw,
            template_lib=template_lib,
            template_map=TestCore.depth2,
            map_to_column="Use_Type",
        )
        # save UmiProject to created package.
        umi.save()
        assert umi.name == "oshkosh_demo"

    @pytest.mark.parametrize(
        "multi_attributes, map_to_column",
        [
            (depth2, ["Use_Type"]),
            (depth3, ["Use_Type", "Year_Built"]),
            (depth4, ["Use_Type", "Year_Built", "ZONING"]),
        ],
    )
    def test_multilevel(self, multi_attributes, map_to_column):
        filename = Path("pyumi/tests/oshkosh_demo.geojson")
        epw = Path("pyumi/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
        template_lib = Path("pyumi/tests/BostonTemplateLibrary.json")
        assert epw.exists()
        umi = UmiProject.from_gis(
            filename,
            "Height",
            epw=epw,
            template_lib=template_lib,
            template_map=multi_attributes,
            map_to_column=map_to_column,
        )
        # save UmiProject to created package.
        umi.save()
