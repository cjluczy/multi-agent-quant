import pathlib

from multi_agent_quant.config import load_config


def test_config_loads(tmp_path: pathlib.Path) -> None:
    sample = pathlib.Path("configs/system.example.yaml")
    cfg = load_config(sample)
    assert cfg.system.capital_base > 0
    assert cfg.agents.total_ratio <= 1.0
    assert cfg.system.market == "cn"
    assert cfg.execution.default_venue == "sim-ctp"


def test_realtime_config_loads() -> None:
    sample = pathlib.Path("configs/system.realtime.example.yaml")
    cfg = load_config(sample)
    assert cfg.system.mode == "realtime"
    assert cfg.system.poll_interval_seconds == 15
    assert cfg.feeds.market.type == "tushare_realtime"


def test_easyquotation_realtime_config_loads() -> None:
    sample = pathlib.Path("configs/system.easyquotation.example.yaml")
    cfg = load_config(sample)
    assert cfg.system.mode == "realtime"
    assert cfg.feeds.market.type == "easyquotation_realtime"
