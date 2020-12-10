"""Module to handle layers common to Umi projects and rhino3dm files."""
import logging
from itertools import accumulate

from rhino3dm import File3dm, Layer

log = logging.getLogger(__name__)


class UmiLayers:
    """UmiLayers Class.

    Handle creation of :class:`rhino3dm.Layer` for umi projects.
    """

    _base_layers = {
        "umi::Buildings": {"Color": (0, 0, 0, 255)},
        "umi::Context": {"Color": (0, 0, 0, 255)},
        "umi::Context::Site boundary": {"Color": (255, 0, 255, 255)},
        "umi::Context::Streets": {"Color": (0, 0, 0, 255)},
        "umi::Context::Parks": {"Color": (0, 127, 0, 255)},
        "umi::Context::Boundary objects": {"Color": (0, 0, 0, 255)},
        "umi::Context::Shading": {"Color": (191, 63, 63, 255)},
        "umi::Context::Trees": {"Color": (63, 191, 127, 255)},
    }

    _file3dm = None

    @classmethod
    def __getitem__(cls, layer_name):
        """Get record by index name.

        Args:
            layer_name (str): The layer name.

        Returns:
            Layer: The Layer object.

        Examples:
            >>> UmiLayers["umi::Context::Streets"]
        """
        return getattr(cls, layer_name)

    def __init__(self, file3dm=None):
        """Initialize the UmiLayer Class.

        Args:
            file3dm (File3dm): The File3dm onto which this class is attached
        """
        self._file3dm = file3dm or File3dm()

        # Loop over layers in the file3dm and add them as classattributes
        # with their full name
        for layer in self._file3dm.Layers:
            setattr(UmiLayers, layer.FullPath, layer)

        # Loop over predefined umi layers, add them (if they don't exist) and
        # set their color; default color is black (0,0,0,255) if not defined.
        for layer_name in UmiLayers._base_layers:
            layer = self.add_layer(layer_name)
            # Try Sets Layers as class attr
            layer.Color = UmiLayers._base_layers.get(layer.FullPath, (0, 0, 0, 255))[
                "Color"
            ]

    def add_layer(self, full_path, delimiter="::"):
        """Add a layer to  self.file3dm.

        Sub-layers can be specified using a names separated by a delimiter.
        For example, "umi::Context::Street" creates the *Street* layer but
        also creates the *Context* layer and the umi layer if they don't
        exist. If a layer already exists it is simply returned.

        Args:
            full_path (str): the layer name. For sub-layers, parent layers
                are created if they don't exits yet
            delimiter (str): defaults to "::"

        Examples:
            >>> from pyumi.umi_project import UmiProject
            >>> umi = UmiProject()  # Initialize the umi project
            >>> umi.umiLayers.add_layer("umi::Context::Amenities")
            >>> umi.umiLayers["umi::Context::Amenities"]
            <rhino3dm._rhino3dm.Layer object at 0x000001DB953052B0>

        Returns:
              Layer: The Rhino Layer object. If Parent layers had to be
              created, those are not returned. Only the lowest level layer
              is returned.
        """
        if self.find_layer_from_fullpath(full_path):
            return self.find_layer_from_fullpath(full_path)
        else:
            # Cumulative List Split
            # Using accumulate() + join()
            temp = full_path.split(delimiter)
            res = list(accumulate(temp, lambda x, y: delimiter.join([x, y])))
            parent_layer = Layer()
            for part in res:
                if self.find_layer_from_fullpath(part):
                    parent_layer = self.find_layer_from_fullpath(part)
                    continue
                else:
                    *parent_name, name = part.split(delimiter)
                    _layer = Layer()  # Create Layer
                    _layer.Name = name  # Set Layer Name
                    if parent_layer:
                        _layer.ParentLayerId = parent_layer.Id  # Set parent Id
                    self._file3dm.Layers.Add(_layer)  # Add Layer
                    _layer = self._file3dm.Layers.FindName(name, parent_layer.Id)

                    # set parent layer to this layer (for next iter)
                    parent_layer = _layer
                    # Sets Layer as class attr
                    setattr(UmiLayers, _layer.FullPath, _layer)
            return _layer

    def find_layer_from_id(self, id):
        """Find layer from Guid."""
        try:
            _layer, *_ = filter(lambda x: x.Id == id, self._file3dm.Layers)
            return _layer
        except ValueError:
            return None

    def find_layer_from_name(self, name):
        """Find layer from name."""
        try:
            _first, *others = filter(lambda x: x.Name == name, self._file3dm.Layers)
            if others:
                raise ReferenceError(
                    "There are more than one layers with " f"the name '{name}'"
                )
            return _first
        except ValueError:
            return None

    def find_layer_from_fullpath(self, full_path):
        """Find layer frm full path."""
        try:
            _layer, *_ = filter(lambda x: x.FullPath == full_path, self._file3dm.Layers)
            return _layer
        except ValueError:
            return None
