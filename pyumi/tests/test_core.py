import logging as lg
from path import Path

from pyumi.core import UmiFile


class TestCore:
    lg.basicConfig(filename="pyumi.log", level=lg.INFO)

    def test_from_gis(self):
        filename = Path("pyumi/tests/oshkosh_demo.zip")
        assert filename.exists()
        umi = UmiFile.from_gis(
            f"{'zip://' + filename.abspath()}", "Height"
        )

        assert umi.name == "oshkosh_demo"