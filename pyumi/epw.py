import io
import logging
import os
from io import TextIOWrapper

import chardet
import geopandas as gpd
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import urllib3
from ladybug.epw import EPW
from path import Path
from shapely.geometry import Point

log = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_TIMEOUT = 5  # seconds


class TimeoutHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        self.timeout = DEFAULT_TIMEOUT
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        timeout = kwargs.get("timeout")
        if timeout is None:
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


retry_strategy = Retry(
    total=3,
    status_forcelist=[403, 429, 500, 502, 503, 504],
    method_whitelist=["HEAD", "GET", "OPTIONS"],
    backoff_factor=1,
)
adapter = TimeoutHTTPAdapter(max_retries=retry_strategy)
http = requests.Session()
http.mount("https://", adapter)
http.mount("http://", adapter)


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


class Epw(EPW):
    """A class to read Epw files.

    Subclass of :class:`ladybug.epw.EPW`. It adds functionality to retrieve IDF
    files by lat lon.
    """

    def __init__(self, buffer_or_path):
        """Construct Epw object."""
        super(Epw, self).__init__(buffer_or_path)

        self.name = buffer_or_path

    @staticmethod
    def _is_path(buffer_or_path):
        """Check if path or buffer."""
        try:
            exists = Path(buffer_or_path).exists()
        except TypeError:
            exists = False
        return exists

    @property
    def headers(self):
        return self.header

    @property
    def name(self):
        """Name of Epw file.

        Examples:
            "USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
        """
        return (
            f"{self.location.country}_{self.location.state}-{self.location.city}."
            f"{self.location.station_id}_{self.location.source}.epw"
        )

    @name.setter
    def name(self, value):
        if isinstance(value, (io.StringIO, TextIOWrapper)):
            self._name = value.name
        elif isinstance(value, (str, Path)):
            self._name = Path(value).basename()

    def as_str(self):
        """Get a text string for the entirety of the EPW file contents."""
        return self.to_file_string()

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

            return cls.from_file_string(epw_str.read())

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
        r = http.get(
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
        r = http.get(url)
        if r.ok:
            # py2 and 3 compatible: binary write, encode text first
            log.debug(" ... OK!")
            return io.StringIO(r.text)
        else:
            log.error(" connection error status code: %s" % r.status_code)
            r.raise_for_status()
