import csv
import io
import logging
import os
from io import TextIOWrapper

import chardet
import geopandas as gpd
import pandas as pd
import requests
from epw import epw
from path import Path

from shapely.geometry import Point

log = logging.getLogger(__name__)


def to_buffer(buffer_or_path):
    """Get a buffer from a buffer or a path.

    Args:
        buffer_or_path (typing.StringIO or str):

    Returns:
        typing.StringIO
    """
    if isinstance(buffer_or_path, str):
        if not os.path.isfile(buffer_or_path):
            raise FileNotFoundError(f"no file found at given path: {buffer_or_path}")
        path = buffer_or_path
        with open(buffer_or_path, "rb") as f:
            encoding = chardet.detect(f.read())
        buffer = open(buffer_or_path, encoding=encoding["encoding"], errors="ignore")
    else:
        path = None
        buffer = buffer_or_path
    return path, buffer


class Epw(epw):
    """A class to read Epw files."""

    def __init__(self, buffer_or_path):
        """Construct Epw object."""
        super(Epw, self).__init__()

        # prepare buffer
        _source_file_path, buffer = to_buffer(buffer_or_path)

        self.name = _source_file_path or "epw"
        self.read(buffer)

        buffer.seek(0)
        self._epw_io = buffer.read()
        buffer.close()

    def _read_headers(self, fp):
        """Read the headers of an epw file.

        Args:
            - fp (str): the file path of the epw file

        Returns:
            - d (dict): a dictionary containing the header rows

        """
        d = {}
        if isinstance(fp, str):
            csvfile = open(fp, newline="")
        else:
            csvfile = fp
        csvreader = csv.reader(csvfile, delimiter=",", quotechar='"')
        for row in csvreader:
            if row[0].isdigit():
                break
            else:
                d[row[0]] = row[1:]

        return d

    def _read_data(self, fp):
        """Read the climate data of an epw file.

        Args:
            - fp (str): the file path of the epw file

        Returns:
            - df (pd.DataFrame): a DataFrame containing the climate data
        """
        names = [
            "Year",
            "Month",
            "Day",
            "Hour",
            "Minute",
            "Data Source and Uncertainty Flags",
            "Dry Bulb Temperature",
            "Dew Point Temperature",
            "Relative Humidity",
            "Atmospheric Station Pressure",
            "Extraterrestrial Horizontal Radiation",
            "Extraterrestrial Direct Normal Radiation",
            "Horizontal Infrared Radiation Intensity",
            "Global Horizontal Radiation",
            "Direct Normal Radiation",
            "Diffuse Horizontal Radiation",
            "Global Horizontal Illuminance",
            "Direct Normal Illuminance",
            "Diffuse Horizontal Illuminance",
            "Zenith Luminance",
            "Wind Direction",
            "Wind Speed",
            "Total Sky Cover",
            "Opaque Sky Cover (used if Horizontal IR Intensity missing)",
            "Visibility",
            "Ceiling Height",
            "Present Weather Observation",
            "Present Weather Codes",
            "Precipitable Water",
            "Aerosol Optical Depth",
            "Snow Depth",
            "Days Since Last Snowfall",
            "Albedo",
            "Liquid Precipitation Depth",
            "Liquid Precipitation Quantity",
        ]

        first_row = self._first_row_with_climate_data(fp)
        df = pd.read_csv(fp, skiprows=first_row, header=None, names=names)
        return df

    def _first_row_with_climate_data(self, fp):
        """Find the first row with the climate data of an epw file.

        Args:
            fp (str): the file path of the epw file

        Returns:
            (int): the row number

        """
        if isinstance(fp, str):
            csvfile = open(fp, newline="")
        else:
            csvfile = fp
        csvreader = csv.reader(csvfile, delimiter=",", quotechar='"')
        for i, row in enumerate(csvreader):
            if row[0].isdigit():
                break
        return i

    @property
    def name(self):
        """Name of Epw file."""
        return self._name

    @name.setter
    def name(self, value):
        if isinstance(value, (io.StringIO, TextIOWrapper)):
            self._name = value.name
        elif isinstance(value, (str, Path)):
            self._name = Path(value).basename()

    def as_str(self):
        """Return Epw as a string."""
        # Todo: Epw, make sure modified string is returned. Needs parsing
        #  fix of epw file
        return self._epw_io

    @classmethod
    def from_nrel(cls, lat, lon):
        """Get EPW from NREL closest to lat, lon."""
        path_to_save = "EPWs"  # create a directory and write the name of directory here
        if not os.path.exists(path_to_save):
            os.makedirs(path_to_save)

        # Get the list of EPW filenames and lat/lon
        gdf = cls._return_epw_names()

        # find the closest EPW file to the given lat/lon
        if (lat is not None) & (lon is not None):
            url, name = cls._find_closest_epw(lat, lon, gdf)

            # download the EPW file to the local drive.
            log.info("Getting weather file: " + name)
            epw_str = cls._download_epw_file(url)

            return cls(epw_str)

    @staticmethod
    def _find_closest_epw(lat, lon, df):
        """Locate the record with the nearest lat/lon."""
        from shapely.ops import nearest_points

        # find the nearest point and return the corresponding Place value
        pts = df.unary_union
        nearest = df.geometry == nearest_points(Point(lon, lat), pts)[1]

        return df.loc[nearest, ["url", "title"]].iloc[0]

    @staticmethod
    def _return_epw_names():
        """Return a dataframe with the name, lat, lon, url of available files."""
        r = requests.get(
            "https://github.com/NREL/EnergyPlus/raw/develop/weather/master.geojson",
            verify=False,
        )
        data = r.json()  # metadata for available files
        # download lat/lon and url details for each .epw file into a GeoDataFrame
        gdf = gpd.GeoDataFrame.from_features(data)
        gdf["url"] = gdf.epw.str.extract(r'href=[\'"]?([^\'" >]+)')
        gdf.drop(columns=["epw", "ddy", "dir"], inplace=True)
        return gdf

    @staticmethod
    def _download_epw_file(url):
        """Download the url and return a buffer."""
        r = requests.get(url)
        if r.ok:
            # py2 and 3 compatible: binary write, encode text first
            log.debug(" ... OK!")
            return io.StringIO(r.text)
        else:
            log.error(" connection error status code: %s" % r.status_code)
            r.raise_for_status()