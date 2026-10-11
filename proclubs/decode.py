"""Versioned community mappings; unknown fields and events stay available.

Source: Interactive-63/eafc-pro-clubs-api-research, read 2026-10-10.
Confidence describes community research, never official EA documentation.
"""

import json
import math
import re
from pathlib import Path

VERSION = "2026-10-10.1"
SOURCE = "https://github.com/Interactive-63/eafc-pro-clubs-api-research"
ENDPOINT_SOURCE = "https://github.com/1erkandogan/fc27-clubs-api/blob/main/docs/endpoints.md"

# A stat can have several event ids; these are additive, not duplicate aliases.
HIGH = {
    "passes_completed": (215,),
    "passes_failed": (216,),
    "passes_forward_completed": (30,),
    "passes_backward_completed": (32,),
    "passes_sideways_completed": (34,),
    "passes_short_completed": (24,),
    "passes_medium_completed": (26,),
    "passes_long_completed": (28,),
    "crosses_completed": (36,),
    "passes_forward_failed": (31,),
    "passes_backward_failed": (33,),
    "passes_sideways_failed": (35,),
    "passes_short_failed": (25,),
    "passes_medium_failed": (27,),
    "passes_long_failed": (29,),
    "crosses_failed_open_play": (37,),
    "first_time_passes": (143,),
    "switch_of_play_passes": (144,),
    "flair_passes": (147,),
    "through_balls_completed": (152,),
    "shots": (217, 218),
    "shots_on_target": (217,),
    "shots_on_target_inside_box": (13,),
    "shots_on_target_outside_box": (18,),
    "shots_off_target": (218,),
    "shots_off_target_inside_box": (14,),
    "shots_off_target_outside_box": (19,),
    "shots_saved": (202,),
    "goals": (214,),
    "goals_first_time": (128,),
    "goals_weak_foot": (131,),
    "goals_off_post": (136,),
    "assists": (11,),
    "second_assists": (115,),
    "assists_through_ball": (118,),
    "good_direction_saves": (267,),
    "dribbles_completed": (174,),
    "dribbles_carried": (97,),
    "dribble_skill_move_beat": (38,),
    "offside_passes": (153,),
    "standing_tackles_won": (229,),
    "sliding_tackles_won": (230,),
    "tackles_won": (0,),
    "tackles_lost": (1,),
    "dangerous_tackles": (163,),
    "clean_tackles": (164,),
    "interceptions": (6,),
    "opponent_dispossessed": (158,),
    "yellow_cards": (95, 213),
    "yellow_cards_immediate": (95,),
    "yellow_cards_delayed": (213,),
    "fouls_conceded": (2, 3),
    "fouls_conceded_other": (2,),
    "fouls_conceded_defensive_third": (3,),
    "fouls_won": (4,),
    "free_kicks_bad_tackle_candidate": (171,),
    "penalties_conceded": (94,),
    "corners_conceded": (10,),
    "corners_attempted": (145,),
    "crosses_blocked": (156,),
    "possession_lost_defensive_third": (105,),
    "possession_lost_middle_third": (106,),
    "possession_lost_attacking_third": (107,),
    "possession_won_defensive_third": (108,),
    "possession_won_middle_third": (109,),
    "possession_won_attacking_third": (110,),
    "aerial_duels_won_attacking": (265,),
    "aerial_duels_won_defending": (266,),
    "out_of_position_severity_1": (99,),
    "out_of_position_severity_2": (100,),
    "out_of_position_severity_3": (101,),
    "out_of_position_severity_4": (102,),
    "out_of_position_severity_5": (103,),
    "out_of_position": (219,),
    "good_position_feedback": (111,),
    "feedback_use_ball": (212,),
    "feedback_pick_pass": (207,),
    "feedback_no_good_option": (175,),
    "feedback_good_option": (176,),
    "feedback_best_option": (177,),
    "feedback_pass_elsewhere": (182,),
    "feedback_chose_pass": (183,),
}
PARTIAL = {
    "bad_pass_candidate": (151,),
    "standing_tackle_duplicate_candidate": (121,),
    "crosses_attempted_open_play_candidate": (157,),
    "severe_foul_candidate": (96,),
    "offsides_candidate": (104,),
    "save_subtype_49_unknown": (49,),
    "save_subtype_50_unknown": (50,),
    "goal_technique_12_unknown": (12,),
    "goal_technique_124_unknown": (124,),
    "goal_technique_137_unknown": (137,),
    "goal_technique_140_unknown": (140,),
    "goal_technique_93_unknown": (93,),
    "goal_technique_238_unknown": (238,),
    "chip_goal_candidate": (123,),
    "feedback_should_have_shot_candidate": (179,),
    "tiki_taka_pass_candidate": (150,),
    "tackle_ending_dribble_candidate": (159,),
}
EXPLORATORY = {
    f"goal_technique_{i}_unknown": (i,)
    for i in (
        46,
        141,
        126,
        17,
        125,
        15,
        239,
        138,
        139,
        130,
        135,
        134,
        203,
        21,
        173,
        194,
        117,
        48,
        132,
        122,
        199,
        168,
    )
}
KNOWN_IDS = {i for group in (HIGH, PARTIAL, EXPLORATORY) for ids in group.values() for i in ids} | {
    112
}
NATIONALITIES = json.loads((Path(__file__).parent / "nationalities.json").read_text())
DIVISIONS = {
    "1": "Elite",
    "2": "Division 1",
    "3": "Division 2",
    "4": "Division 3",
    "5": "Division 4",
    "6": "Division 5",
}
REPUTATION = {"0": "Hometown Heroes", "1": "Emerging Stars", "2": "Well Known", "3": "World Renown"}


def number(value, default=0):
    try:
        v = float(value)
        return int(v) if math.isfinite(v) and v.is_integer() else v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def normalize(value, key=""):
    """Identifiers retain exact text; values become numbers where unambiguous."""
    if isinstance(value, dict):
        return {k: normalize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v, key) for v in value]
    if isinstance(value, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        if key.lower().endswith("id") or key in {
            "TEAM",
            "namespace",
            "proPos",
            "proNationality",
            "name",
            "playername",
            "proName",
        }:
            return value
        return number(value)
    return value


def member_labels(row):
    nation_id = str(row.get("proNationality", ""))
    return {
        "nationality": NATIONALITIES.get(nation_id, {}).get("label", "Unresolved"),
        "nationality_iso": NATIONALITIES.get(nation_id, {}).get("isoCode"),
        "position_family": row.get("favoritePosition") or "Unresolved",
        "exact_position_id": str(row.get("proPos", "")) or "Unresolved",
    }


def percent(numerator, denominator):
    return round(100 * numerator / denominator, 2) if denominator else None


def parse_events(row):
    events, problems = {}, []
    for bucket in range(4):
        for pair in str(row.get(f"match_event_aggregate_{bucket}") or "").split(","):
            if not pair:
                continue
            try:
                event_id, count = (int(x) for x in pair.split(":"))
                if event_id < 0 or count < 0:
                    raise ValueError()
                key = str(event_id)
                if key in events:
                    # The buckets normally partition IDs. Do not silently double count.
                    problems.append(f"Duplicate event {event_id} across buckets; first value kept")
                else:
                    events[key] = count
            except ValueError:
                problems.append(f"Malformed event pair: {pair}")
    return events, problems


def decode_player(row):
    events, problems = parse_events(row)
    decoded = {}
    for confidence, group in (
        ("community_high", HIGH),
        ("community_partial", PARTIAL),
        ("exploratory", EXPLORATORY),
    ):
        for name, ids in group.items():
            decoded[name] = {
                "value": sum(events.get(str(i), 0) for i in ids),
                "confidence": confidence,
                "ids": list(ids),
            }

    def derived(name, value):
        decoded[name] = {"value": value, "confidence": "derived", "ids": []}

    def e(i):
        return events.get(str(i), 0)

    derived("dribble_beat_without_skill_move", max(0, e(112) - e(38)))
    derived("passes_completed_direction_unknown", max(0, e(215) - e(30) - e(32) - e(34)))
    derived("passes_completed_length_unknown", max(0, e(215) - e(24) - e(26) - e(28) - e(36)))
    derived("passes_failed_direction_unknown", max(0, e(216) - e(31) - e(33) - e(35)))
    derived("passes_failed_length_unknown", max(0, e(216) - e(25) - e(27) - e(29) - e(37)))
    for name, ids in (
        ("possession_won", (108, 109, 110)),
        ("possession_lost", (105, 106, 107)),
        ("aerial_duels_won", (265, 266)),
    ):
        derived(name, sum(e(i) for i in ids))
    raw = normalize(row)
    ratios = {
        "pass_completion": percent(number(row.get("passesmade")), number(row.get("passattempts"))),
        "tackle_success": percent(
            number(row.get("tacklesmade")), number(row.get("tackleattempts"))
        ),
        "shot_conversion": percent(number(row.get("goals")), number(row.get("shots"))),
        "shots_on_target_rate": percent(e(217), e(217) + e(218)),
    }
    # Keep named EA stats authoritative; report disagreements instead of replacing them.
    for name, key in (("goals", "goals"), ("assists", "assists"), ("shots", "shots")):
        if key in row and number(row[key]) != decoded[name]["value"]:
            problems.append(f"Named {key} differs from community event total")
    return {
        "raw": raw,
        "events": events,
        "decoded": decoded,
        "ratios": ratios,
        "unknown_events": {k: v for k, v in events.items() if int(k) not in KNOWN_IDS},
        "problems": problems,
        "platform_family": {"1": "PlayStation", "2": "Xbox", "3": "PC", "4": "Nintendo"}.get(
            str(row.get("namespace")), "Unresolved"
        ),
    }


def decode_info(info):
    region = number(info.get("regionId"))
    try:
        region_code = (
            int(region).to_bytes(max(1, (int(region).bit_length() + 7) // 8), "big").decode("ascii")
        )
    except (ValueError, OverflowError, UnicodeDecodeError):
        region_code = "Unknown"
    colours = {
        k: f"#{int(number(v)):06x}"
        for k, v in info.get("customKit", {}).items()
        if "color" in k.lower() and 0 <= number(v, -1) <= 0xFFFFFF
    }
    return {"raw": normalize(info), "region_code": region_code, "kit_colours": colours}


def catalog():
    return {
        "version": VERSION,
        "source": SOURCE,
        "endpoint_source": ENDPOINT_SOURCE,
        "metadata_source": "https://github.com/alex-jordan547/proclubs-sdk/blob/main/src/metadata.ts",
        "nationalities_source": "https://github.com/alex-jordan547/proclubs-sdk/blob/main/src/nationalities.ts",
        "mappings": {
            name: {"ids": ids, "confidence": confidence}
            for confidence, group in (
                ("community_high", HIGH),
                ("community_partial", PARTIAL),
                ("exploratory", EXPLORATORY),
            )
            for name, ids in group.items()
        },
        "notes": [
            "Event counters have no timestamps, coordinates or ordering; heatmaps and xG cannot be reconstructed.",
            "Goal technique tags overlap: never add them to get total goals.",
            "Event 217 can include blocked shots; treat shots on target as a community interpretation.",
            "Namespace mapping is community knowledge; 0 and unrecognized codes remain unresolved.",
            "secondsPlayed/gameTime units are not reliable across responses; kept raw, never used for per-90 stats.",
        ],
    }
