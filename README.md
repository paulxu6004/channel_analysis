# Manual channel relevance review

This project uses pandas to create supporting evidence for a human channel-level
decision. It does not classify videos or channels, fill in relevance values, or
treat the supplied category labels as verified truth.

## Review files

- `outputs/review/channel_review_revised.csv` is generated locally as the
  spreadsheet for manual review. It contains one block per channel, ordered
  from the largest channel to the smallest.
- `outputs/review/channel_sampling_manifest.csv` is generated locally and
  records the selected video IDs and their original selection order.
- `outputs/review/channel_decisions.csv` is versioned and contains exactly
  `channel_title`, `video_count`, and `relevance`. This is the only file where a
  reviewer enters `0` or `1`.
- `outputs/review/category_summary.csv` is the versioned aggregate category
  summary.

Detailed review files contain source-derived video metadata and are intentionally
excluded from Git. If a legacy `outputs/review/channel_review.csv` is available
locally, the script can reuse its sample video IDs. Existing human decisions are
never overwritten.

## Generate and open the review CSV

The source CSV stays outside this project folder. From this folder, install the
pinned dependency once:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Generate the review CSV:

```bash
python scripts/analyze_channels.py prepare \
  --input "/path/to/youtube_channel_content.csv" \
  --out outputs/review
```

Open `outputs/review/channel_review_revised.csv` in Excel, Numbers, Google
Sheets, or another spreadsheet program. A later run will not overwrite that
review; use a different `--out` directory if you need another version.

The supplied source currently contains 108 channels and 56,948 unique video
IDs. The script derives and validates those values from the CSV rather than
assuming them.

## Review CSV layout and sampling

The review CSV has exactly these columns:

```text
row_type,channel_title,total_videos,personal_finance_pct,top_10_tags,sample_number,video_title,tags,category
```

Each channel has a `channel` summary row, followed by up to ten `video` rows,
then a blank separator row. Summary rows show the channel title, its unique
video count, `personal_finance_pct`, and its ten most common tags. The tags are
comma-separated and normalized by trimming whitespace and case-folding. A tag
is counted at most once per video, and equal-frequency tags are ordered
alphabetically. Video rows show the sample number, original title, original
tags, and original category; missing tags remain blank.

`personal_finance_pct` is the percentage of the channel's unique videos whose
`Category` is exactly `personal_finance`, formatted to one decimal place. It is
not overall financial relevance: the supplied categories also include
`investing`, `budgeting`, `retirement`, and others. Use the percentage as
supporting evidence, not a decision rule.

The script keeps existing sample IDs from the legacy review file when they match
the supplied source, and records them in the sampling manifest. If no saved
sample exists, it sorts that channel by video ID and samples without replacement
using fixed seed `42`. A channel with fewer than ten videos contributes all of
its videos. After selection, the first selected `personal_finance` video, if
any, is moved to display position 1; no video is added or replaced, and every
other selected video keeps its relative order.

## Enter decisions and export the final file

Open `outputs/review/channel_decisions.csv` and enter `1` for relevant or `0`
for not relevant in every `relevance` cell. Leave the channel titles and video
counts unchanged. The decision should reflect whether helping individuals or
households understand or manage money is a central, recurring purpose of the
channel's supplied content.

After all rows have a human decision, create the validated three-column export:

```bash
python scripts/analyze_channels.py finalize \
  --input "/path/to/youtube_channel_content.csv" \
  --decisions outputs/review/channel_decisions.csv \
  --output outputs/channel_relevance_final.csv
```

`finalize` rejects altered video counts, missing or extra channels, blank
decisions, and relevance values other than `0` or `1`.
