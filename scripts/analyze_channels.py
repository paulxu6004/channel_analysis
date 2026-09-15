#!/usr/bin/env python3
"""Prepare evidence for manual channel-level relevance decisions with pandas."""

import argparse
from pathlib import Path

import pandas as pd


SOURCE_COLUMNS = ['id', 'channelId', 'channelTitle', 'title', 'tags', 'Category']
FINAL_COLUMNS = ['channel_title', 'video_count', 'relevance']
REVIEW_COLUMNS = [
    'row_type', 'channel_title', 'total_videos', 'personal_finance_pct',
    'top_10_tags', 'sample_number', 'video_title', 'tags', 'category',
]
MANIFEST_COLUMNS = ['channel_id', 'channel_title', 'selection_order', 'video_id']
SAMPLE_SIZE = 10
TOP_TAG_COUNT = 10
DEFAULT_SEED = 42
DEFAULT_LEGACY_REVIEW = Path('outputs/review/channel_review.csv')


def read_source(path):
    data = pd.read_csv(path, usecols=SOURCE_COLUMNS, dtype=str, keep_default_na=False)
    for col in ['id', 'channelId', 'channelTitle', 'title']:
        if data[col].str.strip().eq('').any():
            raise ValueError(f'Source has blank {col} values; investigate before proceeding.')
    if data.empty or data['id'].duplicated().any():
        raise ValueError('Source is empty or has duplicate video IDs; investigate first.')
    if data.groupby('channelId')['channelTitle'].nunique().gt(1).any():
        raise ValueError('A channel ID has multiple titles; resolve the names first.')
    if data.groupby('channelTitle')['channelId'].nunique().gt(1).any():
        raise ValueError('Multiple channel IDs share a title; a decision keyed by title is ambiguous.')
    return data


def inventory(data):
    result = data.groupby('channelId', as_index=False).agg(
        channel_title=('channelTitle', 'first'), video_count=('id', 'nunique'))
    result = result.rename(columns={'channelId': 'channel_id'})
    return result.sort_values(
        ['video_count', 'channel_title', 'channel_id'], ascending=[False, True, True])


def write_csv(frame, path):
    frame.to_csv(path, index=False, encoding='utf-8-sig')


def expected_sample_sizes(channels):
    return {
        row.channel_id: min(SAMPLE_SIZE, int(row.video_count))
        for row in channels.itertuples(index=False)
    }


def source_maps(data, channels):
    by_id = data.set_index('id', drop=False).to_dict('index')
    groups = {
        channel_id: group.sort_values('id')
        for channel_id, group in data.groupby('channelId', sort=False)
    }
    titles = {row.channel_id: row.channel_title for row in channels.itertuples(index=False)}
    return by_id, groups, titles


def validate_selection_map(selections, channels, by_id, channel_titles, origin):
    expected_sizes = expected_sample_sizes(channels)
    if set(selections) != set(expected_sizes):
        raise ValueError(f'{origin} must contain one sample list for every current channel.')
    for channel_id, video_ids in selections.items():
        if len(video_ids) != expected_sizes[channel_id]:
            raise ValueError(
                f'{origin} has {len(video_ids)} samples for {channel_titles[channel_id]!r}; '
                f'expected {expected_sizes[channel_id]}.')
        if len(video_ids) != len(set(video_ids)):
            raise ValueError(f'{origin} has duplicate samples for {channel_titles[channel_id]!r}.')
        for video_id in video_ids:
            if video_id not in by_id:
                raise ValueError(f'{origin} contains video ID {video_id!r} that is not in the source.')
            if by_id[video_id]['channelId'] != channel_id:
                raise ValueError(f'{origin} assigns video ID {video_id!r} to the wrong channel.')


def load_manifest(path, channels, by_id, channel_titles):
    manifest = pd.read_csv(path, dtype=str, keep_default_na=False)
    if manifest.columns.tolist() != MANIFEST_COLUMNS:
        raise ValueError(f'Sampling manifest must contain exactly these columns: {MANIFEST_COLUMNS}')
    if manifest[['channel_id', 'selection_order', 'video_id']].duplicated().any():
        raise ValueError('Sampling manifest has duplicate channel/order/video records.')
    selections = {}
    for channel_id, group in manifest.groupby('channel_id', sort=False):
        try:
            order = pd.to_numeric(group['selection_order'], errors='raise').astype(int)
        except (TypeError, ValueError):
            raise ValueError('Sampling manifest selection_order values must be integers.') from None
        if set(order) != set(range(1, len(group) + 1)):
            raise ValueError(f'Sampling manifest has non-contiguous selection_order values for {channel_id!r}.')
        ordered = group.assign(_order=order).sort_values('_order')
        expected_title = channel_titles.get(channel_id)
        if expected_title is None or not ordered['channel_title'].eq(expected_title).all():
            raise ValueError(f'Sampling manifest has an unknown or mismatched channel title for {channel_id!r}.')
        selections[channel_id] = ordered['video_id'].tolist()
    validate_selection_map(selections, channels, by_id, channel_titles, 'Sampling manifest')
    return selections


def load_legacy_samples(path, channels, by_id, channel_titles):
    legacy = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = ['channel_id', 'channel_title'] + [f'video_url_{i}' for i in range(1, SAMPLE_SIZE + 1)]
    missing = [column for column in required if column not in legacy.columns]
    if missing:
        raise ValueError(f'Legacy review is missing required columns: {", ".join(missing)}')
    if legacy['channel_id'].duplicated().any():
        raise ValueError('Legacy review has duplicate channel IDs.')

    selections = {}
    prefix = 'https://www.youtube.com/watch?v='
    for row in legacy.to_dict('records'):
        channel_id = row['channel_id']
        if channel_id not in channel_titles or row['channel_title'] != channel_titles[channel_id]:
            raise ValueError(f'Legacy review has an unknown or mismatched channel: {channel_id!r}.')
        video_ids = []
        for number in range(1, SAMPLE_SIZE + 1):
            url = row[f'video_url_{number}']
            if not url:
                continue
            if not url.startswith(prefix) or not url[len(prefix):]:
                raise ValueError(f'Legacy review has an invalid sample URL for {channel_id!r}.')
            video_ids.append(url[len(prefix):])
        selections[channel_id] = video_ids
    validate_selection_map(selections, channels, by_id, channel_titles, 'Legacy review')
    return selections


def generate_samples(groups, channels, seed):
    selections = {}
    for row in channels.itertuples(index=False):
        group = groups[row.channel_id]
        samples = group if len(group) <= SAMPLE_SIZE else group.sample(
            n=SAMPLE_SIZE, random_state=seed)
        selections[row.channel_id] = samples['id'].tolist()
    return selections


def save_manifest(path, selections, channels):
    channel_titles = {row.channel_id: row.channel_title for row in channels.itertuples(index=False)}
    rows = []
    for channel_id in channels['channel_id']:
        for selection_order, video_id in enumerate(selections[channel_id], 1):
            rows.append({
                'channel_id': channel_id,
                'channel_title': channel_titles[channel_id],
                'selection_order': selection_order,
                'video_id': video_id,
            })
    write_csv(pd.DataFrame(rows, columns=MANIFEST_COLUMNS), path)


def display_order(video_ids, by_id):
    first_personal_finance = next(
        (index for index, video_id in enumerate(video_ids)
         if by_id[video_id]['Category'] == 'personal_finance'),
        None)
    if first_personal_finance is None:
        return video_ids
    return [video_ids[first_personal_finance]] + video_ids[:first_personal_finance] + video_ids[first_personal_finance + 1:]


def top_tags(group, limit=TOP_TAG_COUNT):
    """Return a channel's most common normalized tags, once per video."""
    counts = {}
    for tags in group['tags']:
        video_tags = {
            tag.strip().casefold()
            for tag in tags.split(',')
            if tag.strip()
        }
        for tag in video_tags:
            counts[tag] = counts.get(tag, 0) + 1
    return [tag for tag, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def build_review_rows(channels, groups, selections, by_id):
    rows = []
    channel_records = list(channels.itertuples(index=False))
    for channel_index, channel in enumerate(channel_records):
        group = groups[channel.channel_id]
        personal_finance_pct = 100 * group['Category'].eq('personal_finance').sum() / len(group)
        rows.append({
            'row_type': 'channel',
            'channel_title': channel.channel_title,
            'total_videos': int(channel.video_count),
            'personal_finance_pct': f'{personal_finance_pct:.1f}%',
            'top_10_tags': ', '.join(top_tags(group)),
            'sample_number': '',
            'video_title': '',
            'tags': '',
            'category': '',
        })
        for sample_number, video_id in enumerate(display_order(selections[channel.channel_id], by_id), 1):
            video = by_id[video_id]
            rows.append({
                'row_type': 'video',
                'channel_title': '',
                'total_videos': '',
                'personal_finance_pct': '',
                'top_10_tags': '',
                'sample_number': sample_number,
                'video_title': video['title'],
                'tags': video['tags'],
                'category': video['Category'],
            })
        if channel_index < len(channel_records) - 1:
            rows.append({column: '' for column in REVIEW_COLUMNS})
    return rows


def validate_review_rows(rows, channels, groups, selections, by_id):
    position = 0
    channel_records = list(channels.itertuples(index=False))
    for channel_index, channel in enumerate(channel_records):
        group_ids = [video_id for video_id, video in by_id.items()
                     if video['channelId'] == channel.channel_id]
        personal_count = sum(by_id[video_id]['Category'] == 'personal_finance' for video_id in group_ids)
        expected_pct = f'{100 * personal_count / len(group_ids):.1f}%'
        summary = rows[position]
        if summary != {
            'row_type': 'channel', 'channel_title': channel.channel_title,
            'total_videos': int(channel.video_count), 'personal_finance_pct': expected_pct,
            'top_10_tags': ', '.join(top_tags(groups[channel.channel_id])),
            'sample_number': '', 'video_title': '', 'tags': '', 'category': '',
        }:
            raise ValueError(f'Review summary validation failed for {channel.channel_title!r}.')
        position += 1
        expected_ids = display_order(selections[channel.channel_id], by_id)
        for sample_number, video_id in enumerate(expected_ids, 1):
            video = by_id[video_id]
            expected_row = {
                'row_type': 'video', 'channel_title': '', 'total_videos': '',
                'personal_finance_pct': '', 'top_10_tags': '', 'sample_number': sample_number,
                'video_title': video['title'], 'tags': video['tags'], 'category': video['Category'],
            }
            if rows[position] != expected_row:
                raise ValueError(f'Review sample validation failed for {channel.channel_title!r}.')
            position += 1
        if channel_index < len(channel_records) - 1:
            if rows[position] != {column: '' for column in REVIEW_COLUMNS}:
                raise ValueError('Review separator validation failed.')
            position += 1
    if position != len(rows):
        raise ValueError('Review validation found unexpected rows.')


def validate_existing_decisions(path, channels):
    decisions = pd.read_csv(path, dtype=str, keep_default_na=False)
    if decisions.columns.tolist() != FINAL_COLUMNS:
        raise ValueError(f'Decision file must contain exactly these columns: {FINAL_COLUMNS}')
    if decisions['channel_title'].duplicated().any():
        raise ValueError('Decision file has duplicate channel titles.')
    expected = channels[['channel_title', 'video_count']]
    if set(decisions['channel_title']) != set(expected['channel_title']):
        raise ValueError('Decision file has missing or unexpected channels.')
    merged = expected.merge(decisions, on='channel_title', suffixes=('_source', '_entered'),
                            validate='one_to_one')
    entered_counts = pd.to_numeric(merged['video_count_entered'], errors='coerce')
    if not entered_counts.eq(merged['video_count_source']).all():
        raise ValueError('One or more decision-file video counts do not match the supplied source.')


def prepare(args):
    source = Path(args.input)
    out = Path(args.out)
    review_path = out / 'channel_review_revised.csv'
    manifest_path = out / 'channel_sampling_manifest.csv'
    decisions_path = out / 'channel_decisions.csv'
    if review_path.exists():
        raise ValueError(f'{review_path} already exists; choose a new --out folder to protect that review.')

    data = read_source(source)
    channels = inventory(data)
    by_id, groups, channel_titles = source_maps(data, channels)

    if decisions_path.exists():
        validate_existing_decisions(decisions_path, channels)
    if manifest_path.exists():
        selections = load_manifest(manifest_path, channels, by_id, channel_titles)
        manifest_is_new = False
    elif Path(args.prior_review).exists():
        selections = load_legacy_samples(Path(args.prior_review), channels, by_id, channel_titles)
        manifest_is_new = True
    else:
        selections = generate_samples(groups, channels, DEFAULT_SEED)
        validate_selection_map(selections, channels, by_id, channel_titles, 'Generated samples')
        manifest_is_new = True

    review_rows = build_review_rows(channels, groups, selections, by_id)
    validate_review_rows(review_rows, channels, groups, selections, by_id)

    out.mkdir(parents=True, exist_ok=True)
    if not decisions_path.exists():
        decisions = channels[['channel_title', 'video_count']].copy()
        decisions['relevance'] = ''
        write_csv(decisions[FINAL_COLUMNS], decisions_path)
    if manifest_is_new:
        save_manifest(manifest_path, selections, channels)
    write_csv(pd.DataFrame(review_rows, columns=REVIEW_COLUMNS), review_path)
    print(f'Prepared {len(channels)} channels covering {len(data):,} videos.')
    print(f'Review CSV: {review_path}')
    print(f'Sampling manifest: {manifest_path}')
    print(f'Decisions CSV: {decisions_path}')


def finalize(args):
    source = read_source(args.input)
    decisions = pd.read_csv(args.decisions, dtype=str, keep_default_na=False)
    if decisions.columns.tolist() != FINAL_COLUMNS:
        raise ValueError(f'Decision file must contain exactly these columns: {FINAL_COLUMNS}')
    if decisions['channel_title'].duplicated().any():
        raise ValueError('Decision file has duplicate channel titles.')
    expected = inventory(source)[['channel_title', 'video_count']]
    if set(decisions['channel_title']) != set(expected['channel_title']):
        raise ValueError('Decision file has missing or unexpected channels.')
    merged = expected.merge(decisions, on='channel_title', suffixes=('_source', '_entered'),
                            validate='one_to_one')
    entered_counts = pd.to_numeric(merged['video_count_entered'], errors='coerce')
    if not entered_counts.eq(merged['video_count_source']).all():
        raise ValueError('One or more video counts do not match the supplied source.')
    labels = merged['relevance'].str.strip()
    invalid = ~labels.isin(['0', '1'])
    if invalid.any():
        examples = ', '.join(merged.loc[invalid, 'channel_title'].head(5))
        raise ValueError(f'{int(invalid.sum())} channels need a binary decision. Examples: {examples}')
    output = Path(args.output)
    if output.exists():
        raise ValueError('Final output already exists. Choose a new path to preserve that version.')
    result = merged[['channel_title']].copy()
    result['video_count'] = merged['video_count_source'].astype(int)
    result['relevance'] = labels.astype(int)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(result[FINAL_COLUMNS], output)
    print(f'Exported {len(result)} verified channel decisions to {output}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare', help='Build a CSV for manual channel review.')
    prep.add_argument('--input', required=True)
    prep.add_argument('--out', default='outputs/review')
    prep.add_argument('--prior-review', default=str(DEFAULT_LEGACY_REVIEW),
                      help='Legacy wide review CSV whose saved sample IDs should be preserved.')
    prep.set_defaults(func=prepare)
    final = commands.add_parser('finalize', help='Validate human decisions and export three columns.')
    final.add_argument('--input', required=True)
    final.add_argument('--decisions', required=True)
    final.add_argument('--output', required=True)
    final.set_defaults(func=finalize)
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
