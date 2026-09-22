from core.wcdma_channel_config import WCDMA_BAND_PLANS, channels_for_band


def test_confirmed_band19_plan():
    plan = WCDMA_BAND_PLANS[19]
    assert (plan.begin, plan.end, plan.step, plan.bw_mhz) == (550, 575, 50, 5.0)
    assert plan.three_channels == (550, 560, 575)


def test_three_channel_mode():
    assert channels_for_band(1, "三信道") == [10562, 10700, 10838]
    assert channels_for_band(19, "三信道") == [550, 560, 575]


def test_traversal_includes_end_when_step_does_not_land_on_end():
    assert channels_for_band(19, "遍历") == [550, 575]
    assert channels_for_band(4, "遍历") == [3325, 3375, 3425, 3475, 3500]
