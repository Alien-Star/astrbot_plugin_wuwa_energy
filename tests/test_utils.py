"""离线单元测试：验证体力文案格式化。

运行：python tests/test_utils.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from astrbot_plugin_wuwa_energy.kuro_client import EnergyInfo
from astrbot_plugin_wuwa_energy.main import WuwaEnergyPlugin


def test_format_energy():
    info = EnergyInfo(remain=45, max=240, total_second=70200)
    txt = WuwaEnergyPlugin._format_energy("12345", info)
    assert "45/240" in txt
    assert "回满还需" in txt


def test_format_energy_full():
    info = EnergyInfo(remain=240, max=240, total_second=0)
    txt = WuwaEnergyPlugin._format_energy("12345", info)
    assert "体力已回满" in txt


def test_format_energy_zero():
    info = EnergyInfo(remain=0, max=240, total_second=85057)
    txt = WuwaEnergyPlugin._format_energy("12345", info)
    assert "0/240" in txt
    assert "回满还需" in txt


if __name__ == "__main__":
    test_format_energy()
    test_format_energy_full()
    test_format_energy_zero()
    print("全部测试通过")
