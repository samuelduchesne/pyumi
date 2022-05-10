import io
import logging as lg
import uuid

import pytest
from fiona.errors import DriverError
from path import Path
from rhino3dm import Brep, File3dm
from shapely.geometry import MultiPolygon, Polygon

from pyumi.geom_ops import geom_to_brep
from pyumi.umi_project import UmiProject
from pyumi.epw import Epw


class TestUmiProject:
    lg.basicConfig(filename="pyumi.log", level=lg.INFO)

    depth2 = {"COMMERCIAL": "B_Off_0", "RESIDENTIAL": "B_Res_0_WoodFrame"}

    depth3 = {
        "COMMERCIAL": {1948: "B_Off_0", 2008: "B_Off_0"},
        "RESIDENTIAL": {1948: "B_Res_0_WoodFrame", 2008: "B_Res_0_Masonry"},
    }

    depth4 = {
        "COMMERCIAL": {1948: {"UMU": "B_Off_0"}, 2008: "B_Off_0"},
        "RESIDENTIAL": {
            "1948": {"CMU": "B_Res_0_WoodFrame", "TR-10": "B_Res_0_Masonry"},
            2008: {"TR-10": "B_Res_0_Masonry"},
        },
    }

    def test_create_umiproject_from_geojson_testfile(self):
        filename = Path("tests/oshkosh_demo.geojson")
        epw = Path("tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
        template_lib = Path("tests/BostonTemplateLibrary.json")
        assert epw.exists()
        umi = UmiProject.from_gis(
            filename,
            "Height",
            template_lib=template_lib,
            template_map=TestUmiProject.depth2,
            map_to_columns=["Use_Type"],
            epw=epw,
        )
        # Add a Street Graph
        umi.add_street_graph(
            network_type="all_private", retain_all=True, clean_periphery=False
        )
        umi.add_pois(
            tags=dict(natural=["tree_row", "tree", "wood"], trees=True),
            on_file3dm_layer="umi::Context::Trees",
        ).add_pois(
            tags=dict(leisure="park", amenity="park", landuse="park"),
            on_file3dm_layer="umi::Context::Parks",
        ).add_pois(
            tags=dict(landuse="commercial"), on_file3dm_layer="umi::Context"
        )
        # save UmiProject to created package.
        projectName = "oshkosh_demo.umi"
        umi.save(projectName)

        # assert the name has changed
        assert umi.name == projectName

    @pytest.mark.parametrize(
        "multi_attributes, map_to_columns",
        [
            (depth2, ["Use_Type"]),
            (depth3, ["Use_Type", "Year_Built"]),
            (depth4, ["Use_Type", "Year_Built", "ZONING"]),
        ],
    )
    def test_multilevel(self, multi_attributes, map_to_columns):
        filename = Path("tests/oshkosh_demo.geojson")
        template_lib = Path("tests/BostonTemplateLibrary.json")
        umi = UmiProject.from_gis(
            filename,
            "Height",
            template_lib=template_lib,
            template_map=multi_attributes,
            map_to_columns=map_to_columns,
            epw=None,
            fid="ID",
        )
        # save UmiProject to created package.
        umi.save()

        # Assert ewp is downloaded for correct location
        assert umi.epw.location.city == "Wittman Rgnl"

    def test_from_cityjson(self):
        """TODO: Create test for cityjson to umi project"""
        pass


class TestGeom:
    """Testing related to geometry conversion between shapely and rhino3dm"""

    @pytest.fixture()
    def file3dm(self):
        yield File3dm()

    @pytest.fixture()
    def multipolygon_with_hole(self):
        # From coordinate tuples
        geom = MultiPolygon(
            [
                (
                    ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
                    [((0.25, 0.25), (0.25, 0.5), (0.5, 0.5), (0.5, 0.25))],
                )
            ]
        )
        yield geom

    @pytest.fixture()
    def polygon_with_hole(self):
        geom = Polygon(
            shell=((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)),
            holes=[((0.25, 0.25), (0.25, 0.5), (0.5, 0.5), (0.5, 0.25))],
        )
        yield geom

    def test_multipolygon(self, multipolygon_with_hole):
        rhino3dm_geom = geom_to_brep(multipolygon_with_hole, 0, 1)
        assert isinstance(rhino3dm_geom, Brep)

        assert rhino3dm_geom.IsSolid is True

    def test_polygon(self, polygon_with_hole):
        rhino3dm_geom = geom_to_brep(polygon_with_hole, 0, 0)
        assert isinstance(rhino3dm_geom, Brep)


class TestUmiProjectOps:
    @pytest.fixture()
    def project_from_gis(self):
        filename = Path("tests/oshkosh_demo.geojson")
        epw = Path("tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
        template_lib = Path("tests/BostonTemplateLibrary.json")
        assert epw.exists()
        yield UmiProject.from_gis(
            filename,
            "Height",
            template_lib=template_lib,
            template_map=TestUmiProject.depth2,
            map_to_columns="Use_Type",
            epw=epw,
        )

    def test_save_to_non_existent_path(self):
        umi = UmiProject()
        with pytest.raises(FileNotFoundError):
            umi.save("./temp/should_fail.umi")

    def test_save_to_valid_path(self, project_from_gis):
        umi = UmiProject()
        umi.save("empty_project.umi")

        assert Path("empty_project.umi").exists()

    def test_save_to_valid_path_no_extension(self, project_from_gis):
        umi = UmiProject()
        umi.save("empty_project_other_name_no_extension")

        assert Path("empty_project_other_name_no_extension.umi").exists()

    def test_export_to_file(self, project_from_gis):
        project_from_gis.export("test_project.geojson")

        assert Path("test_project.geojson").exists()

    def test_export_to_file_shapefile(self, project_from_gis):
        project_from_gis.export("test_project", driver="ESRI Shapefile")

        assert Path("test_project").isdir()
        assert Path("test_project").exists()

    def test_export_to_file_invalid_dst(self, project_from_gis):
        with pytest.raises(DriverError):
            project_from_gis.export("a_folder/test_project.geojson")

    def test_open(self):
        umi = UmiProject.open("tests/oshkosh_demo.umi", fast_open=True)

    def test_open_with_origin_unset(self):
        umi = UmiProject.open(
            "tests/oshkosh_demo.umi", origin_unset=(0, 0), fast_open=True
        )


class TestUmiLayers:
    @pytest.fixture()
    def umi_project(self):
        yield UmiProject()

    def test_get_attr_layer(self, umi_project):
        assert (
            umi_project.umiLayers["umi::Context::Streets"].FullPath
            == "umi::Context::Streets"
        )

    def test_add_new_layer(self, umi_project):
        umi_project.umiLayers.add_layer("umi::Context::Amenities")
        umi_project.umiLayers.add_layer("umi::Buildings::Amenities")

        assert (
            umi_project.umiLayers["umi::Context::Amenities"].Id
            != umi_project.umiLayers["umi::Buildings::Amenities"]
        )

    def test_add_new_layer_not_twice(self, umi_project):
        umi_project.umiLayers.add_layer("umi::Context::Amenities")
        umi_project.umiLayers.add_layer("umi::Context::Amenities")

    def test_get_layer_by_fullpath(self, umi_project):
        umi_project.umiLayers.add_layer("umi::Context::Amenities")
        umi_project.umiLayers.add_layer("umi::Buildings::Amenities")

        umi_project.umiLayers.find_layer_from_fullpath(
            "umi::Context::Amenities"
        ) == umi_project.umiLayers["umi::Context::Amenities"]

    def test_get_layer_by_fullpath_none(self, umi_project):
        name = "A later::that does::not exist"
        assert umi_project.umiLayers.find_layer_from_id(name) is None

    def test_get_layer_by_name(self, umi_project):
        umi_project.umiLayers.add_layer("umi::Context::Amenities")

        assert (
            umi_project.umiLayers.find_layer_from_name("Amenities").Name == "Amenities"
        )

    def test_get_layer_by_name_none(self, umi_project):
        umi_project.umiLayers.add_layer("umi::Context::Amenities")
        name = "A later that does not exist"
        assert umi_project.umiLayers.find_layer_from_name(name) is None

    def test_get_layer_by_name_raises_error_if_more_than_one(self, umi_project):
        umi_project.umiLayers.add_layer("umi::Context::Amenities")
        umi_project.umiLayers.add_layer("umi::Buildings::Amenities")

        with pytest.raises(ReferenceError):
            umi_project.umiLayers.find_layer_from_name("Amenities")

    def test_get_layer_by_id(self, umi_project):
        a_layer = umi_project.file3dm.Layers[0]

        assert umi_project.umiLayers.find_layer_from_id(a_layer.Id).Id == a_layer.Id

    def test_get_layer_by_id_none(self, umi_project):
        id = uuid.uuid1()
        assert umi_project.umiLayers.find_layer_from_id(id) is None


class TestEpw:
    """Tests for the Epw module."""

    @pytest.fixture()
    def epw_buffer(self):
        """Yields an epw string."""
        yield Epw._download_epw_file(
            "https://energyplus-weather.s3.amazonaws.com/north_and_central_america_wmo_region_4/USA/WI/USA_WI_Wittman.Rgnl.AP.726456_TMY3/USA_WI_Wittman.Rgnl.AP.726456_TMY3.epw"
        )

    @pytest.fixture()
    def epw_file(self, tmpdir_factory, epw_buffer):
        fn = tmpdir_factory.mktemp("epw").join("weather.epw")
        fn.write("\n".join(epw_buffer.read().splitlines()))
        yield fn.strpath

    def test_from_path(self, epw_file):
        epw = Epw(epw_file)
        assert epw
        assert epw.location.city == "Wittman Rgnl"
        assert epw.as_str()

    def test_from_io(self, epw_buffer):
        epw = Epw.from_file_string(epw_buffer.read())
        assert epw
        assert epw.location.city == "Wittman Rgnl"
        assert epw.as_str()

    def test_from_nrel(self):
        lat, lon = 42.361145, -71.057083
        epw = Epw.from_nrel(lat, lon)
        assert epw.location.city == "Boston"
        assert epw.as_str()
