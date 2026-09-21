from ui.left_panel import LeftPanel


def test_wifi_channel_parser_accepts_spaces_commas_and_mixed_input():
    assert LeftPanel._parse_wifi_channels("1 6 11") == [1, 6, 11]
    assert LeftPanel._parse_wifi_channels("1,6,11") == [1, 6, 11]
    assert LeftPanel._parse_wifi_channels("1 6,11，13") == [1, 6, 11, 13]
