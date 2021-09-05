# Configuration file representation

from typing import List, Union

import attr


@attr.define
class HotspotConfig:
    rules: List[HotspotRule]

    adapter: str
    poll_delay: float
    rescan_time: float

    io_timeout: float
    connect_timeout: float
    fail_timeout: float


@attr.define
class HotspotRule:
    require: List[str] = attr.Factory(list)
    add: List[str] = attr.Factory(list)
