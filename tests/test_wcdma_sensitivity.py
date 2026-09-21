from core.wcdma_sensitivity import fast_step_for_ber, search_wcdma_sensitivity


def test_fast_step_v1_rules():
    assert fast_step_for_ber(0.08, 2.0) == 0.3
    assert fast_step_for_ber(0.02, 2.0) == 0.5
    assert fast_step_for_ber(0.008, 2.0) == 0.7
    assert fast_step_for_ber(0.002, 2.0) == 1.0
    assert fast_step_for_ber(0.0005, 2.0) == 2.0
    assert fast_step_for_ber(0.002, 0.5) == 0.5


def test_confirm_window_returns_current_level():
    levels = []
    values = iter([0.11, 0.09])
    result = search_wcdma_sensitivity(
        start_level=-100.0, max_step=0.5, min_step=0.2, threshold=0.1,
        fast_packet_count=50, confirm_packet_count=500,
        set_level=levels.append, ensure_connected=lambda: True,
        measure_ber=lambda _count: next(values),
    )
    assert result.sensitivity == -100.0
    assert result.ber == 0.09
    assert result.phase == "CONFIRM_WINDOW"


def test_confirm_above_threshold_backtracks_with_min_step():
    levels = []
    values = iter([0.2, 0.2, 0.15, 0.09])
    result = search_wcdma_sensitivity(
        start_level=-105.0, max_step=0.5, min_step=0.2, threshold=0.1,
        fast_packet_count=50, confirm_packet_count=500,
        set_level=levels.append, ensure_connected=lambda: True,
        measure_ber=lambda _count: next(values),
    )
    assert result.sensitivity == -104.6
    assert result.phase == "BACKTRACK"
    assert levels[-2:] == [-104.8, -104.6]
