class DashboardError(RuntimeError):
    """An expected, user-readable operation failure."""


class BusyError(DashboardError):
    pass
