# Decoder research

Reviewed 2026-10-10. The API is undocumented; interpretations can vary across editions. Raw responses and unrecognized fields remain archived. Decoding is performed locally when reading, so updating the decoder retroactively improves old matches without network calls.

## Evidence and attribution

- [Interactive-63 original API and event research](https://github.com/Interactive-63/eafc-pro-clubs-api-research): high-confidence, partial and exploratory event mappings. These are observations, not official EA definitions.
- [1erkandogan endpoint observations](https://github.com/1erkandogan/fc27-clubs-api/blob/main/docs/endpoints.md): response shapes, recent-match limit, request parameters, named-stat quirks and result examples.
- [Alex Jordan metadata definitions](https://github.com/alex-jordan547/proclubs-sdk/blob/main/src/metadata.ts): namespaces, division codes and reputation labels.
- [Alex Jordan nationality table](https://github.com/alex-jordan547/proclubs-sdk/blob/main/src/nationalities.ts): 174 nationality IDs. Derived from EA ratings filters, with ten historical fallback entries documented by that project. Its MIT notice is retained in [proclubs-sdk-LICENSE.txt](proclubs-sdk-LICENSE.txt).

No external library's request code is used. The collector uses Python's standard library and a small browser-header set previously verified to return this club's JSON. No EA endpoint enumeration is performed.

## What is decoded

`proclubs/decode.py` contains a versioned catalog. Mappings, event IDs and confidence labels are available through the local dashboard API and exports; the UI presents plain-language stats. See [the detailed match inventory](match-stats.md).

| Family | Decoded data |
| --- | --- |
| Passing | Completions/failures, forward/backward/sideways, short/medium/long/cross, first-time, switches, flair, through balls, offside passes |
| Shooting | On/off-target, inside/outside box, saved shots, goals and overlapping technique tags |
| Creation | Assists, second assists, through-ball assists |
| Defending | Standing/sliding tackles, clean tackles, interceptions, dispossessions, aerial duels |
| Ball retention | Dribbles, skill-move beats, possession gained/lost by pitch third |
| Discipline | Yellow cards, fouls, penalties/corners conceded |
| Positioning | Out-of-position severity, in-position feedback, decision feedback |
| Goalkeeping | Named save subtype fields and community good-direction-save event |
| Metadata | Decimal RGB colours, packed-ASCII region, platform family, nationality, division and reputation labels |

`match_event_aggregate_0` through `_3` contain `eventId:count` pairs, not an event timeline. IDs are merged across buckets. A duplicate ID produces a warning and keeps the first value rather than counting it twice. Malformed pairs are reported. Missing IDs become zero in decoded counters; a player row without any event data is separately marked so coverage is visible.

Named EA goals/assists/shots remain authoritative. Event disagreements are counted and retained in the API and exports. EA `passesmade` and community `event_215` can differ because of offside passes. The archive preserves both. Goal tags overlap and are never summed into goals. Partial/exploratory meanings remain available in the API and exports and are omitted from the UI.

## Simple local derivations

- Passing/tackling efficiency: completions divided by attempts; denominator zero means unavailable.
- Shot conversion: named goals divided by named shots. Event-based on-target rate stays separate.
- Possession won/lost: sum the three pitch-third counters.
- Aerial duels won: attacking plus defending counters.
- Untyped passing: total minus mapped directions/lengths, clamped at zero and labeled derived.
- Non-skill dribble beats: event 112 minus event 38, clamped at zero.
- Match outcome: score comparison for friendlies, with explicit named league win/loss/draw flags taking priority for quit decisions. Original result code and `winnerByDnf` remain available.
- Sessions: adjacent captured matches within 90 minutes, with dates shown in the browser's timezone.

These require no extra requests. Ratios are weighted from raw counts, not means of percentages. Unconfirmed `gameTime`/`secondsPlayed` units are preserved without per-90 calculations. Player ratings are unweighted match averages because reliable minutes are unavailable.

## Deliberately unresolved

Exact numeric `proPos`, `proStyle`, archetype IDs, obscure result bits, hacking/attribute flags, game-time units, unknown event IDs, and uncertain technique names stay raw. Known position families are displayed without inventing exact positions. Nationality reflects the virtual pro's chosen nationality, not the person's real nationality. Platform-family mappings retain unknown namespaces as unresolved.

EA division codes are offset: **1 = Elite, 2 = Division 1, …, 6 = Division 5**. A raw code 2 should not be displayed as Division 2.

The data has no shot coordinates, event timestamps, full pitch coordinates, or reliable possession duration. We cannot claim xG, heatmaps, exact goal times or ball-possession percentages. Absent event counters do not prove absence of gameplay when the row has no event data.

## Annual collection limits

Snapshots are immutable, compressed and content-addressed; identical payloads reuse one stored blob. Detailed matches are deduplicated by match ID, with endpoint-type membership recorded separately. Corrected raw match versions remain in blob storage and snapshot history. Career/current/club snapshots never get blindly summed.

Counter decreases are observations, not proof of a season reset. The archive records them and leaves negative snapshot differences unavailable in the API. A separate tracking ledger carries the starting snapshot forward with captured league matches whose timestamps are after the baseline, excluding the initial recent window. That survives counter resets without inferring missing match events. It cannot fix missed windows, baseline scope differences, server clock discrepancies or delayed baseline updates. New archived players without a baseline link start at their captured counts; unmatched baseline names remain separate. Baseline ratings/percentages are not turned into approximate count denominators.

Departed members remain in snapshots, the ledger and the player-ID archive. Name-only member snapshots cannot reliably resolve renames; initial match IDs are used where possible and later name-based links are labeled. New editions use new databases.
