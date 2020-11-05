import logging as lg
import uuid

import pytest
from fiona.errors import DriverError
from path import Path

from pyumi.umi_project import UmiProject


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
            1948: {"CMU": "B_Res_0_WoodFrame", "TR-10": "B_Res_0_Masonry"},
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
            epw=epw,
            template_lib=template_lib,
            template_map=TestUmiProject.depth2,
            map_to_column="Use_Type",
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
        "multi_attributes, map_to_column",
        [
            (depth2, ["Use_Type"]),
            (depth3, ["Use_Type", "Year_Built"]),
            (depth4, ["Use_Type", "Year_Built", "ZONING"]),
        ],
    )
    def test_multilevel(self, multi_attributes, map_to_column):
        filename = Path("tests/oshkosh_demo.geojson")
        epw = Path("tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
        template_lib = Path("tests/BostonTemplateLibrary.json")
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
            epw=epw,
            template_lib=template_lib,
            template_map=TestUmiProject.depth2,
            map_to_column="Use_Type",
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


class TestUmiModules:
    @pytest.fixture()
    def umi_project(self):
        yield UmiProject.open("tests/oshkosh_demo.umi")

    def test_diveristy(self, umi_project):
        umi_project.diversity.grid_thermal_diversity()
        umi_project.diversity.grid_to_file3dm()

        umi_project.save()
