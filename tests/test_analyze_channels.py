import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).parents[1] / 'scripts' / 'analyze_channels.py'
SPEC = importlib.util.spec_from_file_location('analyze_channels', SCRIPT_PATH)
ANALYZE_CHANNELS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZE_CHANNELS)


def test_top_tags_normalizes_and_counts_each_tag_once_per_video():
    group = pd.DataFrame({
        'tags': [
            'Budget, saving, BUDGET, ',
            'saving, investing',
            'budget, Investing',
        ]
    })

    assert ANALYZE_CHANNELS.top_tags(group) == ['budget', 'investing', 'saving']


def test_top_tags_limits_results_and_breaks_ties_alphabetically():
    group = pd.DataFrame({'tags': ['z, a, b', 'c, d']})

    assert ANALYZE_CHANNELS.top_tags(group, limit=3) == ['a', 'b', 'c']


def test_review_places_top_tags_only_on_channel_summary_row():
    channels = pd.DataFrame([{'channel_id': 'channel-1', 'channel_title': 'Channel', 'video_count': 1}])
    group = pd.DataFrame([{
        'id': 'video-1', 'tags': 'Budget, Saving', 'Category': 'personal_finance',
    }])
    by_id = {
        'video-1': {
            'id': 'video-1', 'tags': 'Budget, Saving', 'Category': 'personal_finance',
            'title': 'Video', 'channelId': 'channel-1',
        }
    }

    rows = ANALYZE_CHANNELS.build_review_rows(
        channels, {'channel-1': group}, {'channel-1': ['video-1']}, by_id)

    assert rows[0]['top_10_tags'] == 'budget, saving'
    assert rows[1]['top_10_tags'] == ''
