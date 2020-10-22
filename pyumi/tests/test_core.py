import logging as lg

from path import Path

from pyumi.core import UmiFile


class TestCore:
    lg.basicConfig(filename="pyumi.log", level=lg.INFO)

    def test_from_gis(self):
        filename = Path("pyumi/tests/oshkosh_demo.zip")
        epw = Path("pyumi/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
        assert filename.exists()
        assert epw.exists()
        umi = UmiFile.from_gis(
            f"{'zip://' + filename.abspath()}", "Height", epw=epw
        )

        assert umi.name == "oshkosh_demo"
