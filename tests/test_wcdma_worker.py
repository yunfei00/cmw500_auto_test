from core.fake_cmw500 import FakeCMW500
from core.models import WcdmaTestConfig
from core.wcdma_test_worker import WcdmaTestWorker


def test_wcdma_worker_runs_band_channel_scene_flow():
    instrument = FakeCMW500()
    config = WcdmaTestConfig(
        cable_loss=35.0,
        initial_level=-70.1,
        connection_level=-60.0,
        max_step=2.0,
        min_step=0.2,
        packet_count=500,
        fast_packet_count=50,
        ber_threshold=0.1,
        selected_bands=[1],
        channels_by_band={1: [10562]},
        scenes=["默认"],
    )
    worker = WcdmaTestWorker(config, instrument, run_id="wcdma-test")
    rows = []
    states = []
    worker.row_signal.connect(rows.append)
    worker.state_signal.connect(states.append)
    worker.run()
    assert states[-1] == "COMPLETED"
    assert len(rows) == 1
    assert rows[0].mode == "WCDMA"
    assert rows[0].band == "B1"
    assert rows[0].channel == 10562
    assert rows[0].metric_type == "BER"
