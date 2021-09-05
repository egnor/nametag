# Configuration file representation

import attr


@attr.define
class BeaconConfig:
    adapter: str
    poll_time: float
    recheck_time: float
    io_timeout: float
    connect_timeout: float
    fail_timeout: float
