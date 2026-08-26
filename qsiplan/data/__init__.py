"""Package-data access for qsiplan's viewer assets."""

from importlib.resources import files


class _Loader:
    """The subset of :class:`acres.Loader` the viewers use."""

    def readable(self, name):
        return files(__package__) / name


load = _Loader()
