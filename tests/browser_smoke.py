"""Local UI QA: uv run --no-project --with playwright python tests/browser_smoke.py.

Starts a temporary authenticated server with anonymized fixtures. Blocks external requests; never calls EA.
"""

import copy
import json
import re
import sys
import tempfile
import threading
import tomllib
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "artifacts"
OUTPUT.mkdir(exist_ok=True)


@contextmanager
def offline_viewer():
    sys.path.insert(0, str(ROOT))
    from proclubs.collector import import_seed
    from proclubs.security import hash_password
    from proclubs.server import BoundedHTTPServer, handler

    with tempfile.TemporaryDirectory() as folder:
        config = tomllib.loads((ROOT / "tests/fixtures/config.toml").read_text())
        database = Path(folder) / "stats.sqlite3"
        import_seed(database, config, ROOT / "tests/fixtures/seed")
        credentials = {"username": "club", "password": "browser-test-password"}
        sharing = {
            "username": credentials["username"],
            "password_hash": hash_password(credentials["password"]),
        }
        server = BoundedHTTPServer(("127.0.0.1", 0), handler(database, config, sharing))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", credentials
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


def main(URL, credentials):
    errors, external = [], []
    existing = sorted(
        (Path.home() / ".cache/ms-playwright").glob("chromium-*/chrome-linux64/chrome")
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, **({"executable_path": str(existing[-1])} if existing else {})
        )
        page = browser.new_page(
            viewport={"width": 1440, "height": 1100}, http_credentials=credentials
        )
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

        def local_only(route):
            if route.request.url.startswith(URL + "/"):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        page.route("**/*", local_only)
        data = page.request.get(URL + "/api/dashboard").json()
        games = data["archive"]["games"]
        player_name = data["archive"]["players"][0]["name"]
        page.goto(URL, wait_until="networkidle")
        expect(page.locator("#recordLabel")).to_have_text(
            f"{data['overall']['gamesPlayed']} matches"
        )
        expect(page.locator("#divisionChart svg.chart")).to_be_visible()
        expect(page.locator(".division-badge")).to_have_attribute(
            "aria-label", data["labels"]["division"] + " badge"
        )
        expect(page.locator("#resultsChart .key.gold")).to_have_css(
            "background-color", "rgb(223, 210, 155)"
        )
        expect(page.locator("#overview .date-tick, #overview .index-tick")).to_have_count(0)
        expect(page.locator("#skillChart .axis-label")).to_have_count(4)
        expect(page.locator("#divisionChart .axis-label")).to_have_count(6)
        expect(page.locator("#skillChart circle").first).to_have_attribute(
            "aria-label", re.compile(r"^[A-Z][a-z]{2} \d{1,2} · .+ · Skill rating:")
        )
        assert page.evaluate(
            "Object.values(GROUPS).flat().every(field=>Boolean(STAT_EXPLANATIONS[field.key]))"
        )
        pass_help = page.locator('#passingSummary [data-stat-help="pass_completion"]')
        pass_help.hover()
        expect(page.locator("#statExplanation")).to_be_visible()
        expect(page.locator("#statExplanation")).to_contain_text(
            "Completed passes divided by attempted passes"
        )
        page.keyboard.press("Escape")
        expect(page.locator("#statExplanation")).to_be_hidden()
        pass_help.focus()
        expect(pass_help).to_have_attribute("aria-describedby", "statExplanation")
        expect(page.locator("#statExplanation")).to_be_visible()
        page.keyboard.press("Escape")
        page.locator('#passingChart [data-stat-help="passing_forward"]').click()
        expect(page.locator("#statExplanation")).to_contain_text(
            "chart separates completed and unsuccessful passes"
        )
        page.keyboard.press("Escape")

        assert not page.locator("#error").is_visible()
        expect(page.locator("#teamTrend svg.chart")).to_be_visible()
        assert page.locator("#overview svg.chart").count() == 12
        trends = page.request.get(URL + "/api/trends").json()
        assert len(trends["team"]) == games
        # Division steps occur at observation dates; levels never interpolate.
        step_graph = page.evaluate(
            """() => lineChart([{observed:1700000000,rank:1},{observed:1700086400,rank:3}], [{key:'rank',label:'Division',colour:COLOURS.gold}], 'Division', {bounds:[1,6],step:true,ticks:6})"""
        )
        assert re.search(r'd="M[^"]+H[^"]+V', step_graph)
        same_day = page.evaluate(
            """() => lineChart([{timestamp:1700000000,goals:1},{timestamp:1700000600,goals:2}], [{key:'goals',label:'Goals',colour:COLOURS.lime}], 'Goals')"""
        )
        assert "date-tick" not in same_day and "index-tick" not in same_day
        expect(page.locator("#goalsChart .axis-label")).to_have_count(4)
        expect(page.locator("#goalsChart circle").first).to_have_attribute(
            "aria-label", re.compile(r"^[A-Z][a-z]{2} \d{1,2} · .+ · Scored:")
        )
        # Uneven match dates must not change spacing on a match-index chart.
        indexed = page.evaluate("""() => {
          const html = lineChart([{timestamp:1700000000,goals:1},{timestamp:1700000600,goals:2},{timestamp:1701000000,goals:3}], [{key:'goals',label:'Goals',colour:COLOURS.lime}], 'Goals', {temporal:false});
          const root = new DOMParser().parseFromString(html, 'text/html');
          return [...root.querySelectorAll('circle')].map(p => Number(p.getAttribute('cx')));
        }""")
        assert abs((indexed[1] - indexed[0]) - (indexed[2] - indexed[1])) < 0.02
        # Match Trends stay equally spaced across session gaps; calendar points use period starts.
        axis_checks = page.evaluate("""() => {
          const rows = [new Date(2026,9,5,12),new Date(2026,9,5,13),new Date(2026,9,8,21)].map((d,i) => ({timestamp:d.getTime()/1000,rating:7+i}));
          const points = makeTrendPoints(rows,{type:'rating',key:'rating'},{period:'match',window:0,mode:'average'});
          const html = lineChart(points,[{key:'value',label:'Rating',colour:COLOURS.blue}],'Trends',{temporal:false});
          const root = new DOMParser().parseFromString(html,'text/html');
          return {x:[...root.querySelectorAll('circle')].map(p=>Number(p.getAttribute('cx'))),
            days:makeTrendPoints(rows,{type:'rating',key:'rating'},{period:'day',window:0,mode:'average'}).map(p=>new Date(p.timestamp*1000).getHours()),
            week:new Date(makeTrendPoints(rows,{type:'rating',key:'rating'},{period:'week',window:0,mode:'average'})[0].timestamp*1000).getDay(),
            month:new Date(makeTrendPoints(rows,{type:'rating',key:'rating'},{period:'month',window:0,mode:'average'})[0].timestamp*1000).getDate(),
            range:trendDateRange(rows)};
        }""")
        assert (
            abs(
                (axis_checks["x"][1] - axis_checks["x"][0])
                - (axis_checks["x"][2] - axis_checks["x"][1])
            )
            < 0.02
        )
        assert (
            axis_checks["days"] == [0, 0] and axis_checks["week"] == 1 and axis_checks["month"] == 1
        )
        assert axis_checks["range"] == "Oct 5 – Oct 8"
        expect(page.locator("#teamTrend .section-heading > span")).to_contain_text("Oct 10")
        # Ratios are weighted by attempts; missing values stay gaps, not zero.
        calculated = page.evaluate("""() => {
          const rows=[{named:{passesmade:80,passattempts:100},timestamp:1},{named:{passesmade:1,passattempts:1},timestamp:2}];
          const field={type:'ratio',key:'pass_completion'};
          const points=makeTrendPoints(rows,field,{period:'match',window:2,mode:'average'});
          return {weighted:trendValue(field,rows),rolling:points[1].rolling,first:points[0].rolling,
            missing:trendValue({type:'events',key:'interceptions'},[{events:null}]),
            emptyRate:trendValue(field,[{named:{passesmade:0,passattempts:0}}])};
        }""")
        assert abs(calculated["weighted"] - 100 * 81 / 101) < 0.000001
        assert calculated["rolling"] == calculated["weighted"]
        assert (
            calculated["first"] is None
            and calculated["missing"] is None
            and calculated["emptyRate"] is None
        )
        page.locator('[data-trend-scope="team"][data-trend-setting="group"]').select_option(
            "Passing"
        )
        page.locator('[data-trend-scope="team"][data-trend-setting="metric"]').select_option(
            "ratio:pass_completion"
        )
        page.locator('[data-trend-scope="team"][data-trend-setting="period"]').select_option("week")
        expect(page.locator("#teamTrend circle").first).to_have_attribute(
            "aria-label", re.compile("Accuracy:")
        )
        expect(page.locator('[data-trend-setting="source"]')).to_have_count(0)
        assert "snapshots" not in trends
        page.locator('[data-trend-scope="team"][data-trend-setting="group"]').select_option(
            "Mistakes"
        )
        page.locator('[data-trend-scope="team"][data-trend-setting="metric"]').select_option(
            "events:fouls_conceded"
        )
        expect(page.locator("#teamTrend svg.chart")).to_be_visible()
        page.locator('[data-trend-scope="team"][data-trend-setting="period"]').select_option(
            "match"
        )
        events = data["archive"]["events"]
        box_shots = events["shots_on_target_inside_box"] + events["shots_off_target_inside_box"]

        def display_count(value):
            rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return f"{rounded:,.2f}".rstrip("0").rstrip(".")

        expect(page.locator("#shootingBreakdown .chart-value").first).to_have_text(
            display_count(box_shots / games)
        )
        expect(page.locator("#shootingSummary dd").first).to_have_text(
            display_count(data["archive"]["outcomes"]["goals"] / games)
        )
        pass_accuracy = page.locator("#passingSummary dd").first.inner_text()
        forward_passes = events["passes_forward_completed"] + events["passes_forward_failed"]
        expect(page.locator("#passingChart .chart-value").first).to_have_text(
            display_count(forward_passes / games)
        )
        expect(page.locator("#possessionChart .chart-value").first).to_have_text(
            display_count(
                (
                    events["possession_won_defensive_third"]
                    + events["possession_lost_defensive_third"]
                )
                / games
            )
        )
        cross_rate = (
            page.locator("#rangeBreakdown .stat-list > div")
            .filter(has=page.locator(".stat-name", has_text="Cross accuracy"))
            .locator("strong")
        )
        cross_accuracy = cross_rate.inner_text()
        loss_player = max(
            data["archive"]["players"], key=lambda p: p["events"]["possession_lost"] / p["games"]
        )
        expect(page.locator("#controlBreakdown .chart-subsection .chart-value").first).to_have_text(
            display_count(loss_player["events"]["possession_lost"] / loss_player["games"])
        )
        page.locator('[data-overview-average="total"]').click()
        expect(page.locator("#shootingBreakdown .chart-value").first).to_have_text(str(box_shots))
        expect(page.locator("#shootingSummary dd").first).to_have_text(
            str(data["archive"]["outcomes"]["goals"])
        )
        expect(page.locator("#passingSummary dd").first).to_have_text(pass_accuracy)
        expect(page.locator("#passingChart .chart-value").first).to_have_text(str(forward_passes))
        expect(page.locator("#possessionChart .chart-value").first).to_have_text(
            str(
                events["possession_won_defensive_third"] + events["possession_lost_defensive_third"]
            )
        )
        expect(cross_rate).to_have_text(cross_accuracy)
        loss_total = max(p["events"]["possession_lost"] for p in data["archive"]["players"])
        expect(page.locator("#controlBreakdown .chart-subsection .chart-value").first).to_have_text(
            str(loss_total)
        )
        penalties = (
            page.locator("#defenceBreakdown .stat-list > div")
            .filter(has=page.locator(".stat-name", has_text="Penalties conceded"))
            .locator("strong")
        )
        expect(penalties).to_have_text(str(events["penalties_conceded"]))
        expect(page.locator("#defenceBreakdown .chart-value").first).to_have_text(
            str(data["archive"]["team_named"]["tackleattempts"])
        )
        expect(page.locator("#defenceBreakdown rect.bar")).to_have_count(2)
        page.locator('[data-overview-average="average"]').click()
        expect(page.locator("#defenceBreakdown .chart-value").first).to_have_text(
            display_count(data["archive"]["team_named"]["tackleattempts"] / games)
        )
        expect(page.locator("#possessionChart rect.bar")).to_have_count(6)
        assert page.locator("#goalsChart [data-match]").count() == len(data["match_trend"]) * 2
        page.locator('[data-stat-scope="team"][data-stat-group="Passing"]').click()
        accuracy = (
            page.locator("#teamStats .stat-list > div")
            .filter(has=page.locator(".stat-name", has_text="Accuracy"))
            .locator("strong")
        )
        expected_accuracy = accuracy.inner_text()
        page.locator('[data-team-average="average"]').click()
        expect(accuracy).to_have_text(expected_accuracy)
        page.locator('[data-team-average="total"]').click()
        page.locator('[data-stat-scope="team"][data-stat-group="Goalkeeping"]').click()
        conceded = (
            page.locator("#teamStats .stat-list > div")
            .filter(has=page.locator(".stat-name", has_text="Goals conceded"))
            .locator("strong")
        )
        expect(conceded).to_have_text(str(data["archive"]["outcomes"]["goalsAgainst"]))
        page.locator('[data-stat-scope="team"][data-stat-group="Attack"]').click()
        page.screenshot(path=str(OUTPUT / "overview-desktop.png"), full_page=True)
        # Charts support keyboard drill-down, including the player's own history.
        page.locator("#comparisonChart [data-player]").first.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#pageTitle")).to_have_text("Players")
        expect(page.locator("#playerDetail")).to_be_visible()
        page.locator("#playerSearch").fill(player_name)
        expect(page.locator("#playerTable tbody tr")).to_have_count(1)
        page.locator("#playerTable [data-player]").click()
        detail = next(p for p in data["archive"]["players"] if p["name"] == player_name)
        current = next(m["current"] for m in data["members"] if m["current"]["name"] == player_name)
        row = page.locator("#playerTable tbody tr").first

        def stat(section, label):
            return (
                page.locator(
                    section
                    + " .stat-list:not(.hierarchical-stats) > div, "
                    + section
                    + " .stat-row"
                )
                .filter(has=page.get_by_text(label, exact=True))
                .locator("strong")
            )

        def formatted(value):
            return f"{value:,.2f}".rstrip("0").rstrip(".")

        expected_contributions = formatted(
            (detail["named"]["goals"] + detail["named"]["assists"]) / detail["games"]
        )
        club_contributions = formatted(
            (current["goals"] + current["assists"]) / current["gamesPlayed"]
        )
        missing = next(
            i["missing_matches"] for i in data["initial_player_history"] if i["name"] == player_name
        )
        expect(page.locator("#playerDetail .player-history-note")).to_contain_text(
            f"first {missing} matches"
        )
        expect(page.locator("#playerDetail .player-history-note")).to_contain_text(
            f"Showing {detail['games']} matches"
        )
        expect(stat("#playerDetail .player-record", "Wins")).to_have_text(str(detail["W"]))
        expect(stat("#playerDetail .player-record", "Draws")).to_have_text(str(detail["D"]))
        expect(stat("#playerDetail .player-record", "Losses")).to_have_text(str(detail["L"]))
        expect(stat("#playerDetail .player-record", "Goals + assists / match")).to_have_text(
            expected_contributions
        )
        expect(row.locator("td").last).to_have_text(club_contributions)
        win_rate = row.locator("td").nth(9).inner_text()
        expect(row.locator("td").nth(4)).to_have_text(str(current["ratingAve"]))
        expect(row.locator("td").nth(9)).to_have_text(win_rate)
        expect(row.locator("td").last).to_have_text(club_contributions)
        expect(stat("#playerDetail .player-record", "Goals + assists / match")).to_have_text(
            expected_contributions
        )
        page.locator('[data-sort="contributions_per_game"]').click()
        page.locator('[data-average="average"]').click()
        expect(row.locator("td").nth(2)).to_have_text(
            f"{current['goals'] / current['gamesPlayed']:,.2f}".rstrip("0").rstrip(".")
        )
        expect(row.locator("td").nth(4)).to_have_text(str(current["ratingAve"]))
        for group in [
            "Passing",
            "Defence",
            "Ball control",
            "Goalkeeping",
            "Discipline",
            "Positioning",
            "Mistakes",
            "Decisions",
            "Attack",
        ]:
            page.locator(f'[data-stat-scope="player"][data-stat-group="{group}"]').click()
            expect(page.locator("#playerDetail .stat-heading h2")).to_have_text(group)
        # Every metric remains reachable exactly once after nesting.
        assert page.evaluate("""() => Object.values(GROUPS).every(fields => {
            const keys=[];
            const walk=nodes=>nodes.forEach(node=>{keys.push(node.field.key);walk(node.children);});
            walk(statTree(fields));
            return keys.length===fields.length && new Set(keys).size===fields.length && fields.every(f=>keys.includes(f.key));
        })""")
        page.locator('[data-average="total"]').click()
        expect(page.locator("#playerDetail .stat-tab")).to_have_count(10)
        page.locator('[data-stat-scope="player"][data-stat-group="Mistakes"]').click()
        expect(stat("#playerDetail", "Possession lost")).to_have_text(
            str(detail["events"]["possession_lost"])
        )
        loss_group = page.locator("#playerDetail .stat-node").filter(
            has=page.locator('[data-stat-field="possession_lost"]')
        )
        expect(loss_group.locator(".stat-children .stat-name")).to_have_text(
            ["Defence", "Midfield", "Attack"]
        )
        loss_group.locator('[data-stat-help="possession_lost_middle_third"]').click()
        expect(page.locator("#statExplanation")).to_contain_text("middle third")
        loss_group.locator('[data-stat-help="possession_lost_middle_third"]').click()
        expect(page.locator("#statExplanation")).to_be_hidden()

        for zone in ["defensive", "middle", "attacking"]:
            expect(
                loss_group.locator(f'[data-stat-field="possession_lost_{zone}_third"] strong')
            ).to_have_text(str(detail["events"][f"possession_lost_{zone}_third"]))
        page.screenshot(path=str(OUTPUT / "player-mistakes-desktop.png"), full_page=True)
        page.locator('[data-average="average"]').click()
        expect(
            loss_group.locator('[data-stat-field="possession_lost_middle_third"] strong')
        ).to_have_text(
            display_count(detail["events"]["possession_lost_middle_third"] / detail["games"])
        )
        page.locator('[data-average="total"]').click()
        page.locator('[data-stat-scope="player"][data-stat-group="Ball control"]').click()
        expect(
            page.locator(
                '#playerDetail .stat-node:has(> .stat-row[data-stat-field="possession_won"]), #playerDetail .stat-node:has(> .stat-row[data-stat-field="possession_lost"])'
            )
        ).to_have_count(2)
        expect(
            page.locator(
                '#playerDetail .hierarchical-stats > .stat-node > .stat-row[data-stat-field$="_third"]'
            )
        ).to_have_count(0)

        page.locator('[data-stat-scope="player"][data-stat-group="Pitch"]').click()
        expect(page.locator("#playerDetail .pitch [data-zone]")).to_have_count(3)
        defence = page.locator('#playerDetail .pitch [data-zone="Defence"]')
        expect(defence.locator(".pitch-won")).to_have_text(
            str(detail["events"]["possession_won_defensive_third"])
        )
        page.locator('[data-pitch-scope="player"][data-pitch-mode="shots"]').click()
        expect(page.locator("#playerDetail .pitch [data-zone]")).to_have_count(2)
        expect(
            page.locator('#playerDetail .pitch [data-zone="Inside box"] .pitch-won')
        ).to_have_text(str(detail["events"]["shots_on_target_inside_box"]))
        page.screenshot(path=str(OUTPUT / "player-pitch-desktop.png"), full_page=True)
        page.locator('[data-stat-scope="player"][data-stat-group="Positioning"]').click()
        expect(
            page.locator(
                '#playerDetail .stat-node:has(> [data-stat-field="out_of_position"]) .stat-children .stat-name'
            )
        ).to_have_text(["Level 1", "Level 2", "Level 3", "Level 4", "Level 5"])
        page.locator('[data-stat-scope="player"][data-stat-group="Attack"]').click()
        expect(
            page.locator('#playerDetail [data-stat-field="shots_on_target_inside_box"]')
        ).to_have_attribute("data-stat-depth", "2")
        expect(
            page.locator('#playerDetail [data-stat-field="goals_first_time"]')
        ).to_have_attribute("data-stat-depth", "1")
        page.locator('[data-stat-scope="player"][data-stat-group="Passing"]').focus()
        page.keyboard.press("Enter")
        expect(page.locator("#playerDetail .stat-heading h2")).to_have_text("Passing")
        completed = page.locator('#playerDetail .stat-node:has(> [data-stat-field="passesmade"])')
        expect(completed.locator(".stat-children .stat-name")).to_have_text(
            ["Forward", "Sideways", "Backward", "Short", "Medium", "Long"]
        )
        expect(
            completed.locator('[data-stat-field="passes_forward_completed"] strong')
        ).to_have_text(str(detail["events"]["passes_forward_completed"]))

        page.screenshot(path=str(OUTPUT / "players-desktop.png"), full_page=True)
        # Compare players with different appearances; rates must not be divided twice.
        page.locator("[data-compare-player]").click()
        expect(page.locator("#headToHead")).to_be_visible()
        expect(page.locator("#compareLeft")).to_have_value(detail["id"])

        def left_number(key):
            return page.locator(f'#headToHead [data-compare-field="{key}"] .duel-number').first

        expect(left_number("goals")).to_have_text(
            formatted(detail["named"]["goals"] / detail["games"])
        )
        expect(left_number("rating")).to_have_text(str(detail["rating"]))
        page.locator('[data-compare-average="total"]').click()
        expect(left_number("goals")).to_have_text(str(detail["named"]["goals"]))
        expect(left_number("rating")).to_have_text(str(detail["rating"]))
        page.locator('[data-stat-scope="compare"][data-stat-group="Passing"]').click()
        expect(left_number("pass_completion")).to_have_text(
            f"{detail['pass_completion']:.1f}".rstrip("0").rstrip(".") + "%"
        )
        page.locator('[data-compare-average="average"]').click()
        expect(left_number("pass_completion")).to_have_text(
            f"{detail['pass_completion']:.1f}".rstrip("0").rstrip(".") + "%"
        )
        alternatives = [
            p
            for p in data["archive"]["players"]
            if p["id"] not in [detail["id"], page.locator("#compareRight").input_value()]
        ]
        third = next((p for p in alternatives if p["games"] != detail["games"]), alternatives[0])
        page.locator("#compareRight").select_option(third["id"])
        expect(page.locator("#compareRight")).to_have_value(third["id"])
        expect(
            page.locator('#headToHead [data-compare-field="passesmade"] .duel-number').last
        ).to_have_text(formatted(third["named"]["passesmade"] / third["games"]))
        page.locator('[data-stat-scope="compare"][data-stat-group="Mistakes"]').click()
        expect(
            page.locator('#headToHead .duel-node:has(> [data-compare-field="possession_lost"])')
        ).to_have_count(1)
        expect(
            page.locator(
                '#headToHead .duel-node:has(> [data-compare-field="possession_lost"]) .duel-children .duel-row > span'
            )
        ).to_have_text(["Defence", "Midfield", "Attack"])
        expect(left_number("possession_lost_middle_third")).to_have_text(
            formatted(detail["events"]["possession_lost_middle_third"] / detail["games"])
        )
        page.locator('[data-stat-scope="compare"][data-stat-group="Passing"]').click()
        page.screenshot(path=str(OUTPUT / "head-to-head-desktop.png"), full_page=True)
        page.locator('[data-stat-scope="compare"][data-stat-group="Pitch"]').click()
        expect(page.locator("#headToHead .pitch")).to_have_count(2)
        page.locator('[data-pitch-scope="compare"][data-pitch-mode="shots"]').click()
        expect(page.locator("#headToHead .pitch [data-zone]")).to_have_count(4)
        page.screenshot(path=str(OUTPUT / "head-to-head-pitch-desktop.png"), full_page=True)
        page.locator('[data-players-view="roster"]').click()

        page.locator("#playerDetail svg [data-match]").first.click()
        expect(page.locator("#matchDetail .scoreboard")).to_be_visible()
        page.locator("#closeDialog").click()
        page.locator("#playerSearch").fill("")
        expect(page.locator("[data-source]")).to_have_count(0)
        expect(
            page.locator("#playerTable [data-player]").first.locator(".player-chevron")
        ).to_have_text("›")
        expect(page.locator("#playerTable")).not_to_contain_text("View stats")
        page.locator("#playerSearch").fill(player_name)
        page.get_by_role("button", name=f"View stats for {player_name}", exact=True).focus()
        page.keyboard.press("Enter")
        expect(page.locator("#playerDetail")).to_be_visible()
        current = next(m["current"] for m in data["members"] if m["current"]["name"] == player_name)
        for label, field in [
            ("Win rate", "winRate"),
            ("Shot success", "shotSuccessRate"),
            ("Tackle success", "tackleSuccessRate"),
        ]:
            expect(stat("#playerDetail .player-summary", label)).to_have_text(
                str(current[field]) + "%"
            )
        for label, field in [
            ("Red cards", "redCards"),
            ("Defender clean sheets", "cleanSheetsDef"),
            ("Goalkeeper clean sheets", "cleanSheetsGK"),
        ]:
            expect(stat("#playerDetail .player-summary", label)).to_have_text(str(current[field]))
        expect(stat("#playerDetail .player-summary", "Goals + assists / match")).to_have_text(
            formatted((current["goals"] + current["assists"]) / current["gamesPlayed"])
        )
        expect(stat("#playerDetail .player-record", "Wins")).to_have_text(str(detail["W"]))
        expect(page.locator("#playerAverage")).to_be_visible()
        page.locator('#playerDetail [data-detail-average="average"]').click()
        expect(page.locator("#playerDetail .cards .value").nth(1)).to_have_text(
            formatted(current["goals"] / current["gamesPlayed"])
        )
        expect(stat("#playerDetail .player-summary", "Win rate")).to_have_text(
            str(current["winRate"]) + "%"
        )
        expect(stat("#playerDetail .player-summary", "Red cards")).to_have_text(
            formatted(current["redCards"] / current["gamesPlayed"])
        )
        page.locator('[data-stat-scope="player"][data-stat-group="Passing"]').click()
        expect(stat("#playerDetail .stats-group", "Completed")).to_have_text(
            formatted(detail["named"]["passesmade"] / detail["games"])
        )
        expect(stat("#playerDetail .stats-group", "Accuracy")).to_have_text(
            f"{detail['pass_completion']:.1f}".rstrip("0").rstrip(".") + "%"
        )
        expect(page.locator('[data-average="average"]')).to_have_attribute("aria-pressed", "true")
        page.locator('#playerDetail [data-detail-average="total"]').click()
        expect(stat("#playerDetail .stats-group", "Completed")).to_have_text(
            str(detail["named"]["passesmade"])
        )
        page.screenshot(path=str(OUTPUT / "player-club-desktop.png"), full_page=True)
        page.locator("#playerSearch").fill("")
        page.locator('[data-sort="assists"]').click()
        page.locator('[data-tab="matches"]').click()
        expect(page.locator("#matchTable tbody tr")).to_have_count(min(20, games))
        page.locator("#matchSearch").fill(data["archive"]["matches"][0]["opponent"])
        assert page.locator("#matchTable tbody tr").count() > 0
        page.locator("#matchSearch").fill("")
        page.locator("#matchTable [data-match]").first.click()
        expect(page.locator("#matchDetail .scoreboard")).to_be_visible()
        assert page.locator("#matchDetail .comparison-row").count() == 7
        for group in ["Passing", "Ball control", "Goalkeeping"]:
            page.locator(f'[data-stat-scope="match"][data-stat-group="{group}"]').click()
            expect(page.locator("#matchDetail .stats-group .section-heading h2").last).to_have_text(
                group
            )
        match_id = data["archive"]["matches"][0]["id"]
        raw = page.request.get(URL + "/api/matches/" + match_id).json()["raw"]
        conceded = (
            page.locator("#matchDetail .stat-list > div")
            .filter(has=page.locator(".stat-name", has_text="Goals conceded"))
            .locator("strong")
        )
        expect(conceded).to_have_text(str(raw["clubs"][str(data["club"]["id"])]["goalsAgainst"]))
        page.locator("[data-match-player]").first.click()
        expect(page.locator("[data-match-team]")).to_be_visible()
        page.locator("[data-match-team]").click()
        page.screenshot(path=str(OUTPUT / "match-desktop.png"), full_page=True)
        page.locator("#closeDialog").click()
        page.locator("#matchKind").select_option("friendly")
        page.locator("#applyFilters").click()
        expected = page.request.get(URL + "/api/dashboard?kind=friendly").json()["archive"]["games"]
        expect(page.locator("#matchCount")).to_have_text(f"{expected} matches")
        page.locator("#resetFilters").click()
        expect(page.locator("#matchCount")).to_have_text(f"{games} matches")
        page.locator("#startDate").fill("2026-10-11")
        page.locator("#endDate").fill("2026-10-10")
        page.locator("#applyFilters").click()
        expect(page.locator("#error")).to_contain_text("end date")
        page.locator("#resetFilters").click()
        expect(page.locator("#error")).to_be_hidden()
        assert page.request.get(URL + "/api/players.csv").status == 200
        assert page.request.get(URL + "/api/export").status == 404
        assert not page.locator('a[href="/api/export"]').count()
        page.locator('[data-tab="overview"]').click()
        for metric in [
            "rating",
            "pass_completion",
            "interceptions",
            "second_assists",
            "possession_won",
            "possession_lost",
            "aerial_duels_won",
            "contributions",
        ]:
            page.locator("#comparisonMetric").select_option(metric)
            assert page.locator("#comparisonChart svg").count() == 1
        for width in [390, 768]:
            page.set_viewport_size({"width": width, "height": 844})
            for tab in ["overview", "players", "matches"]:
                page.locator(f'[data-tab="{tab}"]').click()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                    f"{width}px {tab} overflow"
                )
                if width == 390:
                    page.screenshot(path=str(OUTPUT / f"{tab}-mobile.png"), full_page=True)
            page.locator('[data-tab="players"]').click()
            page.locator("#playerTable [data-player]").first.click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                "Player detail overflow"
            )
            if width == 390:
                page.screenshot(path=str(OUTPUT / "player-club-mobile.png"), full_page=True)
            page.locator('[data-stat-scope="player"][data-stat-group="Ball control"]').click()
            expect(
                page.locator(
                    '#playerDetail .stat-node:has(> .stat-row[data-stat-field="possession_won"]), #playerDetail .stat-node:has(> .stat-row[data-stat-field="possession_lost"])'
                )
            ).to_have_count(2)
            page.locator('#playerDetail [data-stat-help="possession_lost"]').click()
            expect(page.locator("#statExplanation")).to_be_visible()
            assert page.locator("#statExplanation").evaluate(
                "(el)=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;}"
            )
            if width == 390:
                page.screenshot(path=str(OUTPUT / "stat-explanation-mobile.png"))
            page.locator("#pageTitle").click()
            expect(page.locator("#statExplanation")).to_be_hidden()

            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                "Possession breakdown overflow"
            )
            if width == 390:
                page.screenshot(path=str(OUTPUT / "player-possession-mobile.png"), full_page=True)
            page.locator('[data-stat-scope="player"][data-stat-group="Pitch"]').click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                "Pitch overflow"
            )
            page.locator('[data-players-view="compare"]').click()
            expect(page.locator("#headToHead")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                "Head to head overflow"
            )
            if width == 390:
                page.screenshot(path=str(OUTPUT / "head-to-head-mobile.png"), full_page=True)
            page.locator('[data-players-view="roster"]').click()
            page.locator('[data-tab="matches"]').click()
            page.locator("#matchTable [data-match]").first.click()
            expect(page.locator("#matchDetail .scoreboard")).to_be_visible()
            page.locator('[data-stat-scope="match"][data-stat-group="Passing"]').click()
            page.locator('#matchDetail [data-stat-help="passesmade"]').click()
            expect(page.locator("#matchDialog #statExplanation")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.locator("#matchDialog")).to_be_visible()
            expect(page.locator("#statExplanation")).to_be_hidden()

            assert page.evaluate(
                'document.querySelector("dialog").scrollWidth <= document.querySelector("dialog").clientWidth'
            ), "Dialog overflow"
            page.locator("#closeDialog").click()
        assert not any(
            word in page.locator("body").inner_text().lower()
            for word in [
                "decoder",
                "raw response",
                "coverage",
                "confidence",
                "baseline",
                "unknown event",
            ]
        )
        # Exercise missing ratings, a single point, and an empty period via local fixtures.
        fixture = copy.deepcopy(data)
        expect(page.locator("#refresh")).to_have_count(0)
        fixture["activity"] = {"active_until": 4102444800, "paused_until": 0}
        fixture["match_trend"] = fixture["match_trend"][:1]
        fixture["trend"] = fixture["trend"][:1]
        for player in fixture["archive"]["players"]:
            player["rating"] = None
            for entry in player["history"]:
                entry["rating"] = None
        page.route("**/api/dashboard*", lambda route: route.fulfill(json=fixture))
        page.locator("#applyFilters").click()
        page.locator('[data-tab="overview"]').click()
        expect(page.locator("#activity")).to_be_visible()
        expect(page.locator("#goalsChart circle")).to_have_count(2)
        expect(page.locator("#goalsChart .index-tick")).to_have_count(0)
        assert "NaN" not in page.locator("body").inner_text()
        assert "NaN" not in page.locator("#goalsChart").inner_html()
        page.locator('[data-tab="players"]').click()
        page.locator("#playerTable [data-player]").first.click()
        expect(page.locator("#playerDetail")).to_contain_text("No ratings yet.")
        fixture["archive"].update(
            games=0,
            players=[],
            matches=[],
            outcomes={},
            team_named={},
            events={},
            sessions=[],
            opponents=[],
            event_player_rows=0,
        )
        fixture["activity"]["active_until"] = 0
        fixture["match_trend"] = []
        page.locator("#applyFilters").click()
        expect(page.locator("#activity")).to_be_hidden()
        expect(page.locator("#matchCount")).to_have_text("0 matches")
        page.locator('[data-tab="players"]').click()
        page.locator('[data-players-view="compare"]').click()
        expect(page.locator("#headToHead")).to_contain_text(
            "Choose a period with at least two players."
        )
        page.locator('[data-tab="overview"]').click()
        expect(page.locator("#goalsChart")).to_have_text("No matches in this period.")
        # Real touch interaction: no hover dependency on phones.
        touch = browser.new_page(
            viewport={"width": 390, "height": 844},
            has_touch=True,
            is_mobile=True,
            http_credentials=credentials,
        )
        touch.route("**/*", local_only)
        touch.on("pageerror", lambda err: errors.append(str(err)))
        touch.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        touch.goto(URL, wait_until="networkidle")
        record = touch.locator('#recordLabel [data-stat-help="matches"]')
        record.tap()
        expect(touch.locator("#statExplanation")).to_be_visible()
        expect(touch.locator("#statExplanation")).to_contain_text(
            "including wins, draws and losses"
        )
        record.tap()
        expect(touch.locator("#statExplanation")).to_be_hidden()
        touch.close()
        # External player names must remain literal text, including in detail views.
        hostile = '<img src="/unexpected-xss" onerror="window.injected=true">'
        malicious_data = copy.deepcopy(data)
        original_name = malicious_data["members"][0]["current"]["name"]
        malicious_data["members"][0]["current"]["name"] = hostile
        for player in malicious_data["archive"]["players"]:
            if original_name in player["names"]:
                player["name"] = hostile
                player["names"] = [hostile]
        secure = browser.new_page(http_credentials=credentials)
        secure.route("**/*", local_only)
        secure.route("**/api/dashboard*", lambda route: route.fulfill(json=malicious_data))
        secure.goto(URL, wait_until="networkidle")
        secure.get_by_role("button", name="Players", exact=True).click()
        player_link = secure.locator("#playerTable").get_by_role("button", name=hostile)
        expect(player_link).to_be_visible()
        assert secure.locator("#playerTable img").count() == 0
        player_link.click()
        expect(secure.locator("#playerDetail")).to_contain_text(hostile)
        assert secure.locator("#playerDetail img").count() == 0
        assert secure.evaluate("window.injected") is None
        secure.close()
        assert not errors, errors
        assert not external, external
        print(
            json.dumps(
                {
                    "status": "passed",
                    "console_errors": errors,
                    "external_requests": external,
                    "checks": "icon categories, head to head, pitch zones, graphs, keyboard drilldowns, weighted stats, averages, sources, sorting, search, match comparison, filters, exports, mobile, missing and empty data",
                },
                indent=2,
            )
        )
        browser.close()


if __name__ == "__main__":
    with offline_viewer() as (url, credentials):
        main(url, credentials)
