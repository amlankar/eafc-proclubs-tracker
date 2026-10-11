# Match stats

The dashboard groups detailed counters by player and team. Choose **Matches** on the Players page for match-based totals or per-match averages. Date and match-type filters apply to detailed stats and charts. Open a match for both teams and individual performances. Visible icon tabs expose every stat group. Players → Head to head compares any two archived players, using the same date/type filter and each player's own appearances for per-match counts. Ratings, percentages and goals + assists per match are not divided again.

The Pitch tab draws possession won/lost in the defensive, middle and attacking thirds, or on/off-target shots inside/outside the penalty area. Both modes show aggregate counts or counts per match on a normalized pitch facing right. The diagram marks whole areas and does not represent shot coordinates, individual event locations or player movements. Outside-box shots are not restricted to a particular pitch half. Pitch views are available for teams, individual players, a selected match performance and head-to-head comparisons.

## Available fields

| Group | Named match fields | Decoded event counters |
| --- | --- | --- |
| Attack | Goals, assists, shots, rating, man of the match | Second assists; through-ball assists; shots on/off target, each inside/outside the box; shots saved; first-time goals, weak-foot goals, goals off the post |
| Passing | Passes completed and attempted | Completed/failed passes forward, sideways and backward; short, medium and long passes; completed/failed crosses; first-time passes; switches of play; flair passes; completed through balls; offside passes |
| Defence | Tackles won and attempted; defender and ANY clean sheets | Standing/sliding tackles won; tackles lost; clean/dangerous tackles; interceptions; opponents dispossessed; crosses blocked; defending aerial wins |
| Ball control | — | Dribbles completed and carried; players beaten using skill moves or without skill moves; possession won/lost in defensive, middle and attacking thirds; attacking and defending aerial wins |
| Goalkeeping | Saves, goals conceded, goalkeeper clean sheets; diving, cross, good-direction, parry, punch and reflex saves | Good-direction saves are also available as an event counter |
| Discipline | Red cards | Immediate/delayed yellow cards; fouls committed in defence/elsewhere; fouls won; penalties conceded; corners conceded/taken |
| Positioning | — | Out-of-position events; severity levels 1–5; good-position feedback |
| Decisions | — | Use the ball, pick your pass, no good option, good option, best option, pass elsewhere, chose to pass feedback |
| Match | Match ID, timestamp, both clubs and their IDs, score, win/loss/draw, match type, quit-win flag, participating players | No event timeline |
| Player metadata | Stable player ID, gamertag, platform namespace, position and archetype codes | Platform family; exact numeric position/archetype meanings remain unresolved |

The decoder additionally preserves event totals for goals, assists, shots, passes and tackles alongside the named counters. The UI uses named counters for these familiar totals, avoiding overlapping counts. Yellow-card subtypes and possession/aerial components likewise have combined totals; components must not be added to those totals again. Direction/length remainders are retained as derived unclassified pass counts. Unconfirmed foul/technique interpretations stay in exports rather than the UI.

## Player summaries

Club player details show the cumulative win rate, passing accuracy, shot success, tackle success, red cards, defender clean sheets and goalkeeper clean sheets from the current member snapshot. The same profile includes captured detailed match stats, with a note identifying the initial matches excluded. Goals + assists per match is calculated separately for the cumulative summary and captured match record. It stays a rate when per-match display is enabled.

Match record shows each player's captured wins, draws, losses, win rate and goals + assists per match, with its match count displayed. It follows date/type filters and stays separate from cumulative club stats. These summaries need no additional collection endpoints.

## Aggregation

- **Player and team totals:** every unique captured match contributes once. Updated EA responses replace a match's current stats. Detailed team counters combine participating player rows; goals conceded uses the club score because player rows can each repeat it. Clean-sheet counters count qualifying player appearances.
- **Per-match averages:** total counters divided by captured games. Team counts are divided by team games, rather than player appearances.
- **Passing accuracy:** total completed passes / total attempts.
- **Tackle success:** total tackles won / total attempts.
- **Shot conversion:** named goals / named shots.
- **On-target rate:** decoded on-target shots / decoded shots.
- **Rating:** mean of positive match ratings. Missing ratings stay unavailable and appear as gaps in graphs.
- **Trends:** skill rating from dated club snapshots; goals scored/conceded per match; each player's rating, goals and assists per match.
- **Opponents and sessions:** games, wins/draws/losses and score totals. Sessions group matches separated by at most 90 minutes. Full detailed counter breakdowns are currently available by player, team and date/type filter, rather than by opponent or session.

The year ledger starts with the initial club/player snapshot and adds captured league games after that snapshot. Detailed counters start with the ten captured matches; the earlier 62-game snapshot cannot supply historical interceptions, possession or individual match ratings. These totals remain separate.

There are no coordinates, event times or reliable possession duration. This data cannot produce xG, heatmaps, exact goal times, ball-possession percentages or reliable per-90 stats. Counts for positioning and decisions are feedback occurrences, not percentages or durations.

Full mappings and interpretation notes: [decoder research](research.md). All calculations use saved responses and require no extra EA requests.

## Unified player profiles

Players now have one roster/profile rather than separate Club totals and Match stats views. Current EA counters form the broad summary; detailed categories and match records use captured appearances, without adding those matches onto the current counters. Archived players absent from current membership remain available when they have matches in the selected window. A note identifies how many initial player appearances have no detailed history: starting member games minus unique player appearances in the starting league window. The count comes from frozen initial snapshots, stays independent of filters and later matches, and is omitted when there is no known starting record. New gaps after collection began are not assumed to be part of that initial number.

### Time series

The authenticated read-only `/api/trends` route reconstructs chronological team points and per-player appearance points from the entire selected match archive. Points retain named counters, all decoded event values, ratio components, results and positive ratings; absent event payloads are null. Team goals/conceded scores come from the club result, while named player-derived goal and shot counters remain separate for conversion math. Team conceded counters use the club score once rather than summing copies from players. Raw archived match corrections naturally update historical points without introducing another match.

The frontend makes the currently displayed statistic groups available as selectable trends, including ratings/results, all passing directions/distances, possession thirds, attacking, defensive, goalkeeper, discipline, positioning and decision measures. It recomputes percentages from pooled attempts for time buckets and rolling windows. Trends use detailed archived matches only. Overall/member snapshots remain saved for cumulative summaries but are excluded from the Trends controls and endpoint response. Date and match-type filters apply to all trend points. The initial recent-game window supplies the first detailed points; the earlier global snapshot cannot supply detailed stats for missing games.

### Mistakes

The Mistakes category groups already archived counters for possession lost (including each pitch third), failed/offside passes, tackles lost, dangerous tackles, fouls committed, penalties conceded, out-of-position feedback, yellow cards and red cards. It is available in team stats, player profiles, match details, head-to-head and detailed-match Trends. These counters overlap and are kept separate; no combined error score or errors-leading-to-goals value is inferred. Decision feedback such as No good option is not classified as a mistake.

Overview Defence adds tackle losses, dangerous tackles, penalties conceded and out-of-position counts alongside its existing figures. Ball control adds a player possession-loss chart: Totals uses each player's count, while Per match uses that player's captured appearances rather than the club's match count. Selecting a player bar opens their profile. The Player comparison selector also supports failed/offside passes, tackles lost, dangerous tackles, fouls committed, penalties conceded and out-of-position feedback. All figures use detailed archived matches and the existing filters, with no additional EA calls.

Overview Defence uses a stacked green/rose tackle chart: named detailed-match tackles won versus attempts minus wins, matching the named tackle-success percentage. This remainder is labelled Not won; the separate decoded Tackles lost event counter remains a distinct metric. Standing/sliding wins, interceptions and defending aerial wins remain in the supporting figures. Ball control uses the same horizontal stacked-bar style for possession won/lost across defence, midfield and attack, with dribbling and player possession losses beneath. Counts follow the Overview Totals / Per match toggle.

Detailed stat lists use a shared parent/child hierarchy with indented rows, rather than possession-specific cards. Explicit presentation relationships cover possession by third, shots by outcome and location, goals/assists by type, completed/failed passes by direction and distance, aerial wins, defensive-third fouls, positioning levels and save types. Children stay with their parent in responsive columns; nested shot locations use a second indentation level. These are related counters, not necessarily exhaustive or mutually exclusive components, and no totals are calculated by summing them. The same hierarchy applies to team/player/match details and head-to-head. Trends retain the flat inventory of individual metrics, and Totals / Per match calculations are unchanged.

### Division history and chart dates

The read-only dashboard exposes `division_history` from retained summary endpoint snapshots as observation timestamp, mapped division code and label. This is a separate club progression graph, not a metric added to detailed-match Trends. It shares the current Division label's source. Unavailable or invalid values remain null; no pre-tracking history or intermediate division values are invented. The frontend draws steps at observed changes, with Elite above Divisions 1–5 and a simple inline SVG badge. All history graphs use dates on the horizontal axis, actual timestamps for spacing, unique same-day labels, and exact time in point tooltips.

### In-place stat explanations

The existing statistic labels have a faint dotted underline. Hover, keyboard focus or tap reveals a shared explanation popover; tapping again, tapping elsewhere or Escape dismisses it. No separate per-stat icon is added. The same definitions are used for detailed team/player/match lists, nested breakdowns, head-to-head, supporting Overview figures, relevant chart labels, summary figures and the selected Trends metric. Player-name chart labels retain their profile navigation.

Definitions live in `web/stat-help.js` and follow existing decoded counters and calculations. Direction and distance breakdowns describe the same passes; overlapping goal/save types are not summed; tackle attempts minus wins differs from Tackles lost; positioning levels and decision feedback do not invent a mistake score or precise trigger. Ratio explanations include their formula, and per-match detailed counts explain their team/player match denominator. Every metric in the existing stat categories has a definition. The popover remains within the viewport and is hosted in the match dialog when needed; no requests or archive writes are triggered by opening explanations.
