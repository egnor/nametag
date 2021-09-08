# Configuration file representation

from typing import List

import attr


@attr.define
class HotspotConfig:
    rules: List[HotspotRule]

    adapter: str
    poll_delay: float
    rescan_time: float
    min_rssi: int

    step_timeout: float
    connect_timeout: float
    fail_timeout: float


@attr.define
class HotspotRule:
    require: List[str] = attr.Factory(list)
    set_flag: List[str] = attr.Factory(list)
