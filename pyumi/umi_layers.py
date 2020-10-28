from itertools import accumulate

from rhino3dm import *


class UmiLayers:
    """Handles creation of :class:`rhino3dm.Layer` for umi projects"""

    _base_layers = [
        "umi::Buildings",
        "umi::Context",
        "umi::Context::Site boundary",
        "umi::Context::Streets",
        "umi::Context::Parks",
        "umi::Context::Boundary objects",
        "umi::Context::Shading",
        "umi::Context::Trees",
    ]

    _file3dm = None

    @classmethod
    def __getitem__(cls, x):
        return getattr(cls, x)

    def __init__(self, file3dm):
        """Initializes the UmiLayer Class.

        Args:
            file3dm (File3dm): The File3dm onto which this class is attached
        """
        self._file3dm = file3dm

        for layer in UmiLayers._base_layers:
            self.add_layer(layer)

    def add_layer(self, full_path, delimiter="::"):
        """Adds a layer to the file3dm. Sub-layers can be specified using a
        names separated by a delimiter. For example,
        "umi::Context::Street" creates the *Street* layer but also creates the
        *Context* layer and the umi layer if they don't exist. If a layer
        already exists it is simply returned.

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
              list: A list containing the guid of the created layer, or all
                layers if parent layers were created
        """
        if self.find_layer_from_fullpath(full_path):
            return self.find_layer_from_fullpath(full_path)
        else:
            # Cumulative List Split
            # Using accumulate() + join()
            temp = full_path.split(delimiter)
            res = list(accumulate(temp, lambda x, y: delimiter.join([x, y])))
            parent_layer = None
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
                    _layer = self.find_layer_from_fullpath(part)
                    if not parent_layer:
                        parent_layer = _layer
                    # Sets Layer as class attr
                    setattr(UmiLayers, _layer.FullPath, _layer)

    def find_layer_from_id(self, id):
        try:
            _layer, *_ = filter(lambda x: x.Id == id, self._file3dm.Layers)
            return _layer
        except ValueError:
            return None

    def find_layer_from_name(self, name):
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
        try:
            _layer, *_ = filter(lambda x: x.FullPath == full_path, self._file3dm.Layers)
            return _layer
        except ValueError:
            return None
