"use strict";
const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "—").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (value, decimals = 0) =>
  value == null || !Number.isFinite(Number(value))
    ? "—"
    : Number(value).toLocaleString(undefined, {
        maximumFractionDigits: decimals,
      });
const pct = (n, d) => (d ? (100 * n) / d : null);
const date = (t) =>
  new Date(t * 1000).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
const time = (t) =>
  new Date(t * 1000).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
const stamp = (t) => `${date(t)} · ${time(t)}`;
const COLOURS = {
  lime: "#c7ef83",
  rose: "#dfa393",
  blue: "#8fb9cd",
  gold: "#dfd29b",
};
let data,
  query = "",
  average = false,
  selectedPlayer = null,
  category = "Attack",
  sortKey = "goals",
  sortDirection = -1;
let requestVersion = 0,
  matchPage = 0,
  matchPayload = null,
  matchPlayer = null,
  matchCategory = "Attack",
  openMatchId = null,
  matchRequest = 0;
let teamCategory = "Attack",
  teamAverage = false,
  overviewAverage = true;
let playersView = "roster",
  compareLeft = null,
  compareRight = null,
  compareCategory = "Attack",
  compareAverage = true;
const pitchModes = {
  team: "possession",
  player: "possession",
  match: "possession",
  compare: "possession",
};
const numeric = (v) => typeof v === "number" && Number.isFinite(v);
function empty(message = "No matches in this period.") {
  return `<div class="empty">${esc(message)}</div>`;
}
function card(label, value, sub = "") {
  return `<article class="card"><div class="label">${statHelpLabel(label, statHelpKey(label), "")}</div><div class="value">${esc(value)}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}</article>`;
}
function table(headers, rows) {
  return rows.length
    ? `<table><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table>`
    : empty();
}
function resultBadge(r) {
  return `<span class="result ${["W", "D", "L"].includes(r) ? r : "D"}">${esc(r)}</span>`;
}
function playerLink(key, name, details = false) {
  return `<button class="player-link" data-player="${esc(key)}"${details ? ` aria-label="View stats for ${esc(name)}" aria-controls="playerDetail"` : ""}><span class="avatar">${esc(name.slice(0, 2).toUpperCase())}</span>${esc(name)}${details ? '<span class="player-chevron" aria-hidden="true">›</span>' : ""}</button>`;
}
function matchLink(id, label) {
  return `<button class="player-link" data-match="${esc(id)}">${esc(label)}</button>`;
}
function svg(content, width, height, label) {
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)}">${content}</svg>`;
}
function lineChart(
  points,
  series,
  label,
  {
    bounds = null,
    compact = false,
    temporal = true,
    step = false,
    axisFormat = null,
    ticks = 4,
    emptyMessage = "No ratings yet.",
  } = {},
) {
  if (!points.length) return empty();
  const width = 560,
    height = compact ? 175 : 205,
    left = axisFormat ? 65 : 36,
    right = 35,
    top = 18,
    bottom = 18;
  const values = points.flatMap((p) =>
    series.map((s) => p[s.key]).filter(numeric),
  );
  if (!values.length) return empty(emptyMessage);
  let lo = bounds ? bounds[0] : Math.min(0, ...values),
    hi = bounds
      ? bounds[1]
      : Math.max(3, Math.ceil((Math.max(...values) * 1.12) / 3) * 3);
  if (hi <= lo) hi = lo + 1;
  const firstTime = points[0].timestamp || points[0].observed,
    lastTime = points.at(-1).timestamp || points.at(-1).observed;
  const x = (i) =>
    points.length === 1
      ? width / 2
      : left +
        (temporal && lastTime > firstTime
          ? ((points[i].timestamp || points[i].observed) - firstTime) /
            (lastTime - firstTime)
          : i / (points.length - 1)) *
          (width - left - right);
  const y = (v) => top + ((hi - v) / (hi - lo)) * (height - top - bottom);
  let content = "";
  for (let i = 0; i < ticks; i++) {
    const v = lo + ((hi - lo) * i) / (ticks - 1),
      py = y(v);
    content += `<path class="grid" d="M${left} ${py.toFixed(2)}H${width - right}"/><text class="axis-label" x="${left - 8}" y="${py + 3}" text-anchor="end">${esc(axisFormat ? axisFormat(v) : num(v, hi - lo < 5 ? 1 : 0))}</text>`;
  }
  for (const s of series) {
    // Missing ratings break the line; they are never plotted as zero.
    let path = "",
      previous = false;
    points.forEach((p, i) => {
      if (!numeric(p[s.key])) {
        previous = false;
        return;
      }
      path +=
        previous && step
          ? `H${x(i).toFixed(2)}V${y(p[s.key]).toFixed(2)} `
          : `${previous ? "L" : "M"}${x(i).toFixed(2)},${y(p[s.key]).toFixed(2)} `;
      previous = true;
    });
    content += `<path class="line" stroke="${s.colour}" d="${path}"/>`;
    points.forEach((p, i) => {
      if (!numeric(p[s.key])) return;
      const tip = `${stamp(p.timestamp || p.observed)}${p.opponent ? " · " + p.opponent : ""} · ${s.label}: ${s.format ? s.format(p[s.key]) : num(p[s.key], 2)}`;
      content += `<circle class="point${p.id ? " clickable" : ""}" cx="${x(i).toFixed(2)}" cy="${y(p[s.key]).toFixed(2)}" r="3.5" fill="${s.colour}" tabindex="0" aria-label="${esc(tip)}" ${p.id ? `data-match="${esc(p.id)}"` : ""}><title>${esc(tip)}</title></circle>`;
    });
  }
  return svg(content, width, height, label);
}
function barChart(
  rows,
  label,
  { colours = [COLOURS.lime], maximum = null } = {},
) {
  if (!rows.length) return empty();
  const width = 560,
    rowHeight = 42,
    height = Math.max(130, rows.length * rowHeight + 8),
    left = 145,
    right = 65;
  const max =
    maximum ||
    Math.max(
      1,
      ...rows.map((r) =>
        r.values.reduce((sum, v) => sum + (numeric(v) ? v : 0), 0),
      ),
    );
  let content = "";
  rows.forEach((r, i) => {
    const py = i * rowHeight + 20,
      tip = `${r.label}: ${r.values.map((v) => num(v, 2)).join(" + ")}${r.suffix || ""}`;
    const helpKey = r.key ? null : statHelpKey(r.label);
    const attr = r.key ? `data-player="${esc(r.key)}" role="button"` : "";
    content += `<g class="${r.key ? "clickable" : ""}" tabindex="0" aria-label="${esc(tip)}" ${attr}><title>${esc(tip)}</title><text class="bar-label${STAT_EXPLANATIONS[helpKey] ? " stat-help" : ""}" ${STAT_EXPLANATIONS[helpKey] ? `data-stat-help="${esc(helpKey)}" tabindex="0" role="button" aria-label="Explain ${esc(r.label)}"` : ""} x="0" y="${py + 4}">${esc(r.label.length > 20 ? r.label.slice(0, 19) + "…" : r.label)}</text><rect x="${left}" y="${py - 9}" width="${width - left - right}" height="18" rx="3" fill="#273023"/>`;
    let pos = left;
    r.values.forEach((v, index) => {
      const barWidth =
        ((numeric(v) ? Math.max(0, v) : 0) / max) * (width - left - right);
      content += `<rect class="bar" x="${pos.toFixed(2)}" y="${py - 9}" width="${barWidth.toFixed(2)}" height="18" rx="2" fill="${colours[index % colours.length]}"/>`;
      pos += barWidth;
    });
    content += `<text class="chart-value" x="${width - 1}" y="${py + 4}" text-anchor="end">${esc(
      r.display ??
        num(
          r.values.reduce((sum, v) => sum + (v || 0), 0),
          r.decimals || 0,
        ),
    )}${esc(r.suffix || "")}</text></g>`;
  });
  return svg(content, width, height, label);
}
function possessionChart(events, decimals = 0) {
  return barChart(
    ["defensive", "middle", "attacking"].map((third, i) => ({
      label: ["Defence", "Midfield", "Attack"][i],
      decimals,
      values: [
        events[`possession_won_${third}_third`] || 0,
        events[`possession_lost_${third}_third`] || 0,
      ],
    })),
    "Possession won and lost by pitch third",
    { colours: [COLOURS.lime, COLOURS.rose] },
  );
}
function passingChart(events, decimals = 0) {
  return barChart(
    [
      ["Forward", "forward"],
      ["Sideways", "sideways"],
      ["Backward", "backward"],
    ].map(([label, k]) => ({
      label,
      decimals,
      values: [
        events[`passes_${k}_completed`] || 0,
        events[`passes_${k}_failed`] || 0,
      ],
    })),
    "Completed and failed passes by direction",
    { colours: [COLOURS.lime, COLOURS.rose] },
  );
}
function donut(w, d, l) {
  const total = w + d + l;
  if (!total) return empty("No games yet.");
  const radius = 65,
    circ = 2 * Math.PI * radius;
  let offset = 0;
  let rings = `<circle cx="90" cy="90" r="65" fill="none" stroke="#293324" stroke-width="15"/>`;
  [
    [w, COLOURS.lime, "Wins"],
    [d, COLOURS.gold, "Draws"],
    [l, COLOURS.rose, "Losses"],
  ].forEach(([value, colour, label]) => {
    if (!value) return;
    const length = (value / total) * circ;
    rings += `<circle cx="90" cy="90" r="65" fill="none" stroke="${colour}" stroke-width="15" stroke-dasharray="${length} ${circ - length}" stroke-dashoffset="${-offset}" transform="rotate(-90 90 90)"><title>${label}: ${value}</title></circle>`;
    offset += length;
  });
  return `<div class="donut-wrap"><svg class="donut" viewBox="0 0 180 180" role="img" aria-label="${w} wins, ${d} draws, ${l} losses">${rings}<text class="center-value" x="90" y="89" text-anchor="middle">${num((100 * w) / total, 1)}%</text><text class="center-label stat-help" data-stat-help="win_rate" tabindex="0" role="button" aria-label="Explain win rate" x="90" y="110" text-anchor="middle">win rate</text></svg><div class="donut-legend">${[
    ["Wins", w, "lime"],
    ["Draws", d, "gold"],
    ["Losses", l, "rose"],
  ]
    .map(
      ([label, value, colour]) =>
        `<div><span class="key ${colour}"></span>${statHelpLabel(label, statHelpKey(label), "")}<strong>${num(value)}</strong></div>`,
    )
    .join("")}</div></div>`;
}
const DIVISION_NAMES = {
  1: "Elite",
  2: "Division 1",
  3: "Division 2",
  4: "Division 3",
  5: "Division 4",
  6: "Division 5",
};
function divisionBadge(code) {
  if (!DIVISION_NAMES[code]) return "";
  return `<svg class="division-badge" viewBox="0 0 64 72" role="img" aria-label="${esc(DIVISION_NAMES[code])} badge"><path d="M32 3 58 12v25c0 16-26 31-26 31S6 53 6 37V12z"/><path class="badge-inner" d="M32 9 52 16v21c0 10-20 24-20 24S12 47 12 37V16z"/><path class="badge-crown" d="m21 22 4 5 7-9 7 9 4-5v11H21z"/><text x="32" y="51" text-anchor="middle">${code === 1 ? "★" : code - 1}</text></svg>`;
}
function renderClubSummary() {
  const o = data.overall,
    division = data.labels.division;
  const history = data.division_history || [],
    code = Number(
      Object.keys(DIVISION_NAMES).find(
        (key) => DIVISION_NAMES[key] === division,
      ),
    );
  $("clubCards").innerHTML =
    `<article class="panel results-summary"><div class="section-heading"><h2>Results</h2><span id="recordLabel">${statHelpLabel(`${num(o.gamesPlayed)} matches`, "matches", "")}</span></div><div id="resultsChart">${donut(o.wins || 0, o.ties || 0, o.losses || 0)}</div>${o.unbeatenstreak ? `<div class="record-note">${num(o.unbeatenstreak)} unbeaten</div>` : ""}</article><article class="panel division-summary"><div class="section-heading"><h2>${statHelpLabel("Division", "division", "")}</h2><span>${num(o.promotions)} promotions</span></div><div class="division-current">${divisionBadge(code)}<strong>${esc(division === "Unresolved" ? "—" : division)}</strong></div><div id="divisionChart"></div></article>`;
  const points = history.map((p) => ({
    ...p,
    rank: DIVISION_NAMES[p.division] ? 7 - p.division : null,
  }));
  $("divisionChart").innerHTML = lineChart(
    points,
    [
      {
        key: "rank",
        label: "Division",
        colour: COLOURS.gold,
        format: (rank) => DIVISION_NAMES[7 - rank],
      },
    ],
    "Division over time",
    {
      bounds: [1, 6],
      ticks: 6,
      step: true,
      axisFormat: (rank) => (rank === 6 ? "Elite" : `D${6 - rank}`),
      emptyMessage: "No division history yet.",
    },
  );
  const scored = o.goals || 0,
    conceded = o.goalsAgainst || 0,
    total = scored + conceded;
  $("clubGoals").innerHTML =
    `<div class="goal-totals"><div>${statHelpLabel("Scored", "goals", "")}<strong>${num(scored)}</strong></div><div>${statHelpLabel("Conceded", "goalsconceded", "")}<strong>${num(conceded)}</strong></div></div><svg class="goal-balance" viewBox="0 0 560 9" preserveAspectRatio="none" role="img" aria-label="${num(scored)} goals scored, ${num(conceded)} conceded"><rect width="560" height="9" fill="#30392e"/>${total ? `<rect width="${(560 * scored) / total}" height="9" fill="${COLOURS.lime}"/><rect x="${(560 * scored) / total + (scored && conceded ? 3 : 0)}" width="${Math.max(0, (560 * conceded) / total - (scored && conceded ? 3 : 0))}" height="9" fill="${COLOURS.rose}"/>` : ""}</svg><div class="goal-caption">${statHelpLabel("Goal difference", "goal_difference", "")}<strong>${scored - conceded > 0 ? "+" : ""}${num(scored - conceded)}</strong></div>`;
}
function switchTab(tab) {
  document
    .querySelectorAll(".tab")
    .forEach((el) => (el.hidden = el.id !== tab));
  document.querySelectorAll(".nav").forEach((el) => {
    el.classList.toggle("active", el.dataset.tab === tab);
    if (el.dataset.tab === tab) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  $("pageTitle").textContent = {
    overview: "Overview",
    players: "Players",
    matches: "Matches",
  }[tab];
}
function windowLabel() {
  return `${num(data.archive.games)} matches${query ? " · selected period" : " · all dates"}`;
}
function render() {
  const o = data.overall,
    a = data.archive,
    n = a.team_named,
    e = a.events;
  $("clubMeta").textContent = data.club.name;
  document.title = data.club.name;
  document
    .querySelector(".brand")
    .setAttribute("aria-label", `${data.club.name} home`);
  const clubWords = data.club.name
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .split(/\s+/)
    .filter(Boolean);
  $("clubInitials").textContent = clubWords
    .map((word) => word[0])
    .join("")
    .slice(0, 3)
    .toUpperCase();
  $("clubEdition").textContent = data.club.edition.replace(/^FC/i, "");
  const lastWord = document.createElement("strong");
  lastWord.textContent = `${clubWords.at(-1).toUpperCase()}.`;
  $("brandName").replaceChildren(
    clubWords.slice(0, -1).join(" ").toUpperCase(),
    document.createElement("br"),
    lastWord,
  );
  $("division").textContent =
    data.labels.division === "Unresolved" ? "FC 27" : data.labels.division;
  const now = Date.now() / 1000;
  $("activity").hidden = !(
    data.activity?.active_until > now && !(data.activity?.paused_until > now)
  );
  const updated = Math.max(
    ...Object.values(data.endpoint_times).filter(numeric),
  );
  $("sync").textContent = updated ? `Updated ${time(updated)}` : "";
  renderClubSummary();
  $("skillValue").textContent = num(o.skillRating);
  $("skillChart").innerHTML = lineChart(
    data.trend.filter((p) => numeric(p.skillRating)),
    [{ key: "skillRating", label: "Skill rating", colour: COLOURS.lime }],
    "Skill rating by update index",
    { bounds: skillBounds(), temporal: false },
  );
  document
    .querySelectorAll(".windowLabel")
    .forEach((el) => (el.textContent = windowLabel()));
  $("filterSummary").textContent = windowLabel();
  renderOverviewStats();
  $("goalsChart").innerHTML = lineChart(
    data.match_trend,
    [
      { key: "goals", label: "Scored", colour: COLOURS.lime },
      { key: "goalsAgainst", label: "Conceded", colour: COLOURS.rose },
    ],
    "Goals scored and conceded by match index",
    { temporal: false },
  );
  renderComparison();
  $("form").innerHTML = a.matches
    .slice(0, 10)
    .map(
      (m) =>
        `<button class="text-button" data-match="${esc(m.id)}" aria-label="${esc(`${m.opponent}, ${m.goals}–${m.goalsAgainst}`)}">${resultBadge(m.result)}</button>`,
    )
    .join("");
  $("recentMatches").innerHTML =
    a.matches
      .slice(0, 4)
      .map(
        (m) =>
          `<div class="match-row">${resultBadge(m.result)}<div class="opponent">${matchLink(m.id, m.opponent)}<div class="small-text">${esc(stamp(m.timestamp))}</div></div><span class="score">${m.goals}–${m.goalsAgainst}</span></div>`,
      )
      .join("") || empty();
  $("sessions").innerHTML = table(
    ["Date", "Games", "W–D–L", "Goals"],
    a.sessions
      .slice(0, 6)
      .map((s) => [
        esc(date(s.start)),
        num(s.games),
        `${s.W}–${s.D}–${s.L}`,
        `${s.goals}–${s.goalsAgainst}`,
      ]),
  );
  $("csvExport").href = "/api/players.csv" + query;
  renderTeamStats();
  renderPlayers();
  renderHeadToHead();
  renderMatches();
}
function renderOverviewStats() {
  const a = data.archive,
    n = a.team_named,
    e = a.events,
    events = Boolean(a.event_player_rows);
  const count = (v) => (overviewAverage ? (a.games ? v / a.games : null) : v);
  const formatted = (v) => num(count(v), overviewAverage ? 2 : 0);
  const rate = (n, d) => (d ? `${num(pct(n, d), 1)}%` : "—");
  const rows = (items) =>
    items.map(([label, values]) => ({
      label,
      values: values.map(count),
      decimals: overviewAverage ? 2 : 0,
    }));
  const metrics = (items) =>
    `<div class="overview-metrics">${statList(items)}</div>`;
  const summary = (items) =>
    `<dl class="performance-summary">${items.map(([label, value]) => `<div><dt>${statHelpLabel(label, statHelpKey(label), "", overviewAverage && !["Accuracy", "Conversion", "Tackle success"].includes(label))}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>`;
  const eventCount = (v) => (events ? formatted(v || 0) : "—");
  $("shootingSummary").innerHTML = summary([
    ["Goals", formatted(a.outcomes.goals || 0)],
    ["Shots", formatted(n.shots || 0)],
    ["Conversion", rate(n.goals, n.shots)],
  ]);
  $("passingSummary").innerHTML = summary([
    ["Accuracy", rate(n.passesmade, n.passattempts)],
    ["Completed", formatted(n.passesmade || 0)],
    ["Attempted", formatted(n.passattempts || 0)],
  ]);
  $("defenceSummary").innerHTML = summary([
    ["Conceded", formatted(a.outcomes.goalsAgainst || 0)],
    ["Tackle success", rate(n.tacklesmade, n.tackleattempts)],
    ["Tackles won", formatted(n.tacklesmade || 0)],
  ]);
  $("controlSummary").innerHTML = summary([
    ["Dribbles", eventCount(e.dribbles_completed)],
    ["Possession won", eventCount(e.possession_won)],
    ["Possession lost", eventCount(e.possession_lost)],
  ]);
  const scaledEvents = Object.fromEntries(
    Object.entries(e).map(([k, v]) => [k, count(v)]),
  );
  $("passingChart").innerHTML = events
    ? passingChart(scaledEvents, overviewAverage ? 2 : 0)
    : empty();
  $("possessionChart").innerHTML = events
    ? possessionChart(scaledEvents, overviewAverage ? 2 : 0)
    : empty();
  document.querySelectorAll("[data-overview-average]").forEach((el) => {
    const active =
      (el.dataset.overviewAverage === "average") === overviewAverage;
    el.classList.toggle("active", active);
    el.setAttribute("aria-pressed", String(active));
  });
  if (!a.games || !events) {
    for (const id of [
      "shootingBreakdown",
      "rangeBreakdown",
      "defenceBreakdown",
      "controlBreakdown",
    ])
      $(id).innerHTML = empty();
    return;
  }
  $("shootingBreakdown").innerHTML =
    barChart(
      rows([
        [
          "Inside box",
          [
            e.shots_on_target_inside_box || 0,
            e.shots_off_target_inside_box || 0,
          ],
        ],
        [
          "Outside box",
          [
            e.shots_on_target_outside_box || 0,
            e.shots_off_target_outside_box || 0,
          ],
        ],
      ]),
      "On-target and off-target shots by area",
      { colours: [COLOURS.lime, COLOURS.rose] },
    ) +
    metrics([
      ["On target", rate(e.shots_on_target, e.shots)],
      ["First-time goals", formatted(e.goals_first_time || 0)],
      ["Weak-foot goals", formatted(e.goals_weak_foot || 0)],
      ["Second assists", formatted(e.second_assists || 0)],
    ]);
  $("rangeBreakdown").innerHTML =
    barChart(
      rows(
        ["short", "medium", "long"].map((k) => [
          k[0].toUpperCase() + k.slice(1),
          [e[`passes_${k}_completed`] || 0, e[`passes_${k}_failed`] || 0],
        ]),
      ),
      "Completed and failed passes by distance",
      { colours: [COLOURS.lime, COLOURS.rose] },
    ) +
    metrics([
      [
        "Cross accuracy",
        rate(
          e.crosses_completed || 0,
          (e.crosses_completed || 0) + (e.crosses_failed_open_play || 0),
        ),
      ],
      ["Through balls", formatted(e.through_balls_completed || 0)],
      ["Switches of play", formatted(e.switch_of_play_passes || 0)],
      ["First-time passes", formatted(e.first_time_passes || 0)],
    ]);
  $("defenceBreakdown").innerHTML =
    barChart(
      rows([
        [
          "Tackles",
          [
            n.tacklesmade || 0,
            Math.max(0, (n.tackleattempts || 0) - (n.tacklesmade || 0)),
          ],
        ],
      ]),
      "Tackles won and not won",
      { colours: [COLOURS.lime, COLOURS.rose] },
    ) +
    metrics([
      ["Standing tackles won", formatted(e.standing_tackles_won || 0)],
      ["Sliding tackles won", formatted(e.sliding_tackles_won || 0)],
      ["Interceptions", formatted(e.interceptions || 0)],
      ["Defending aerial wins", formatted(e.aerial_duels_won_defending || 0)],
      ["Dispossessions", formatted(e.opponent_dispossessed || 0)],
      ["Crosses blocked", formatted(e.crosses_blocked || 0)],
      ["Fouls", formatted(e.fouls_conceded || 0)],
      ["Red cards", formatted(n.redcards || 0)],
      ["Tackles lost", formatted(e.tackles_lost || 0)],
      ["Dangerous tackles", formatted(e.dangerous_tackles || 0)],
      ["Penalties conceded", formatted(e.penalties_conceded || 0)],
      ["Out of position", formatted(e.out_of_position || 0)],
    ]);
  $("controlBreakdown").innerHTML =
    barChart(
      rows([
        ["Dribble carries", [e.dribbles_carried || 0]],
        ["Skill moves", [e.dribble_skill_move_beat || 0]],
        ["Players beaten", [e.dribble_beat_without_skill_move || 0]],
      ]),
      "Dribbling actions",
      { colours: [COLOURS.blue] },
    ) +
    `<div class="chart-subsection"><div class="chart-heading"><h3>Possession lost by player</h3><span class="small-text">${overviewAverage ? "Per match played" : "Totals"}</span></div>${barChart(
      a.players
        .filter((p) => p.event_games)
        .map((p) => ({
          label: p.name,
          key: p.id,
          values: [
            overviewAverage
              ? (p.events.possession_lost || 0) / p.games
              : p.events.possession_lost || 0,
          ],
          decimals: overviewAverage ? 2 : 0,
        }))
        .sort((a, b) => b.values[0] - a.values[0]),
      "Possession lost by player",
      { colours: [COLOURS.rose] },
    )}</div>`;
}
function skillBounds() {
  const values = data.trend.map((p) => p.skillRating).filter(numeric);
  return values.length
    ? [Math.min(...values) - 30, Math.max(...values) + 30]
    : null;
}
function comparisonValue(p, metric) {
  if (metric === "contributions")
    return (p.named.goals || 0) + (p.named.assists || 0);
  if (metric === "rating" || metric === "pass_completion") return p[metric];
  return p.event_games ? (p.events[metric] ?? 0) : null;
}
function renderComparison() {
  const metric = $("comparisonMetric").value;
  const rows = data.archive.players
    .filter((p) => numeric(comparisonValue(p, metric)))
    .sort((a, b) => comparisonValue(b, metric) - comparisonValue(a, metric))
    .slice(0, 8)
    .map((p) => ({
      label: p.name,
      key: p.id,
      values:
        metric === "contributions"
          ? [p.named.goals || 0, p.named.assists || 0]
          : [comparisonValue(p, metric)],
      suffix: metric === "pass_completion" ? "%" : "",
      decimals: metric === "rating" ? 2 : metric === "pass_completion" ? 1 : 0,
    }));
  $("comparisonChart").innerHTML = barChart(rows, "Player comparison", {
    colours:
      metric === "contributions"
        ? [COLOURS.lime, COLOURS.blue]
        : [COLOURS.lime],
    maximum:
      metric === "rating" ? 10 : metric === "pass_completion" ? 100 : null,
  });
  $("comparisonLegend").hidden = metric !== "contributions";
}
function playerRows() {
  const archived = data.archive.players,
    initial = data.initial_player_history || [];
  const rows = data.members.map((m) => {
    const p = m.current,
      a = archived.find((a) => a.names.includes(p.name)),
      first = initial.find((i) => i.name === p.name || i.id === a?.id);
    return {
      ...p,
      id: a?.id || first?.id,
      key: a?.id || first?.id || p.name,
      cumulative: true,
      games: p.gamesPlayed,
      rating: p.ratingAve,
      passes: p.passesMade,
      tackles: p.tacklesMade,
      pass_completion: p.passSuccessRate,
    };
  });
  for (const a of archived) {
    if (rows.some((p) => p.id === a.id || a.names.includes(p.name))) continue;
    rows.push({
      ...a,
      key: a.id,
      cumulative: false,
      goals: a.named.goals || 0,
      assists: a.named.assists || 0,
      manOfTheMatch: a.named.mom || 0,
      passes: a.named.passesmade || 0,
      tackles: a.named.tacklesmade || 0,
      winRate: pct(a.W, a.games),
    });
  }
  return rows.map((p) => ({
    ...p,
    contributions_per_game:
      p.games && numeric(p.goals) && numeric(p.assists)
        ? (p.goals + p.assists) / p.games
        : null,
  }));
}

const PLAYER_RATES = new Set([
  "rating",
  "pass_completion",
  "winRate",
  "contributions_per_game",
]);
function displayPlayer(p, k) {
  if (PLAYER_RATES.has(k))
    return (
      num(p[k], k === "rating" || k === "contributions_per_game" ? 2 : 1) +
      (["pass_completion", "winRate"].includes(k) && p[k] != null ? "%" : "")
    );
  return num(
    average && k !== "games" && p[k] != null ? p[k] / (p.games || 1) : p[k],
    average && k !== "games" ? 2 : 0,
  );
}
function renderPlayers() {
  $("playerScope").textContent = "Club totals";
  $("playerAverage").hidden = false;
  document.querySelectorAll("[data-average]").forEach((el) => {
    const active = (el.dataset.average === "average") === average;
    el.classList.toggle("active", active);
    el.setAttribute("aria-pressed", String(active));
  });
  const fields = [
    "name",
    "games",
    "goals",
    "assists",
    "rating",
    "passes",
    "pass_completion",
    "tackles",
    "manOfTheMatch",
    "winRate",
  ];
  fields.push("contributions_per_game");
  const labels = {
    name: "Player",
    games: "Games",
    goals: "Goals",
    assists: "Assists",
    rating: "Rating",
    passes: "Passes",
    pass_completion: "Pass %",
    tackles: "Tackles",
    interceptions: "Interceptions",
    manOfTheMatch: "MOTM",
    winRate: "Win %",
    contributions_per_game: "G+A / match",
  };
  const search = $("playerSearch").value.toLowerCase();
  const rows = playerRows()
    .filter((p) => p.name.toLowerCase().includes(search))
    .sort((a, b) => {
      let av = a[sortKey] ?? -1,
        bv = b[sortKey] ?? -1;
      if (
        average &&
        !PLAYER_RATES.has(sortKey) &&
        !["name", "games"].includes(sortKey)
      ) {
        av /= a.games || 1;
        bv /= b.games || 1;
      }
      return (
        sortDirection *
        (typeof av === "string" ? av.localeCompare(String(bv)) : av - bv)
      );
    });
  $("playerTable").innerHTML = table(
    fields.map(
      (k) =>
        `<button class="sort ${sortKey === k ? "active" : ""}" data-sort="${k}">${labels[k]} ${sortKey === k ? (sortDirection < 0 ? "↓" : "↑") : ""}</button>`,
    ),
    rows.map((p) =>
      fields.map((k) =>
        k === "name" ? playerLink(p.key, p.name, true) : displayPlayer(p, k),
      ),
    ),
  );
  if (selectedPlayer) renderPlayerDetail(selectedPlayer);
}
function archivePlayer(p) {
  return (
    data.archive.players.find((a) => a.id === p.id || a.id === p.key) ||
    data.archive.players.find(
      (a) => a.names.includes(p.name) || a.names.includes(p.baseline_name),
    )
  );
}
const N = (label, key) => ({ label, key, type: "named" }),
  E = (label, key) => ({ label, key, type: "events" }),
  R = (label, key) => ({ label, key, type: "ratio" });
const GROUPS = {
  Attack: [
    N("Goals", "goals"),
    N("Assists", "assists"),
    E("Second assists", "second_assists"),
    N("Shots", "shots"),
    E("On target", "shots_on_target"),
    E("Off target", "shots_off_target"),
    R("Shot conversion", "shot_conversion"),
    R("On target %", "shots_on_target_rate"),
    E("On target · inside box", "shots_on_target_inside_box"),
    E("On target · outside box", "shots_on_target_outside_box"),
    E("Off target · inside box", "shots_off_target_inside_box"),
    E("Off target · outside box", "shots_off_target_outside_box"),
    E("Shots saved", "shots_saved"),
    E("First-time goals", "goals_first_time"),
    E("Weak-foot goals", "goals_weak_foot"),
    E("Goals off the post", "goals_off_post"),
    E("Through-ball assists", "assists_through_ball"),
    N("Man of the match", "mom"),
  ],
  Passing: [
    N("Completed", "passesmade"),
    N("Attempted", "passattempts"),
    R("Accuracy", "pass_completion"),
    E("Failed", "passes_failed"),
    E("Forward · completed", "passes_forward_completed"),
    E("Forward · failed", "passes_forward_failed"),
    E("Sideways · completed", "passes_sideways_completed"),
    E("Sideways · failed", "passes_sideways_failed"),
    E("Backward · completed", "passes_backward_completed"),
    E("Backward · failed", "passes_backward_failed"),
    E("Short · completed", "passes_short_completed"),
    E("Short · failed", "passes_short_failed"),
    E("Medium · completed", "passes_medium_completed"),
    E("Medium · failed", "passes_medium_failed"),
    E("Long · completed", "passes_long_completed"),
    E("Long · failed", "passes_long_failed"),
    E("Crosses · completed", "crosses_completed"),
    E("Crosses · failed", "crosses_failed_open_play"),
    E("First-time passes", "first_time_passes"),
    E("Switches of play", "switch_of_play_passes"),
    E("Flair passes", "flair_passes"),
    E("Through balls", "through_balls_completed"),
    E("Offside passes", "offside_passes"),
  ],
  Defence: [
    N("Tackles won", "tacklesmade"),
    N("Tackles attempted", "tackleattempts"),
    R("Tackle success", "tackle_success"),
    E("Standing tackles won", "standing_tackles_won"),
    E("Sliding tackles won", "sliding_tackles_won"),
    E("Tackles lost", "tackles_lost"),
    E("Clean tackles", "clean_tackles"),
    E("Dangerous tackles", "dangerous_tackles"),
    E("Interceptions", "interceptions"),
    E("Opponents dispossessed", "opponent_dispossessed"),
    E("Crosses blocked", "crosses_blocked"),
    E("Aerial wins · defending", "aerial_duels_won_defending"),
    N("Defender clean sheets", "cleansheetsdef"),
    N("ANY clean sheets", "cleansheetsany"),
  ],
  "Ball control": [
    E("Dribbles completed", "dribbles_completed"),
    E("Dribble carries", "dribbles_carried"),
    E("Skill moves beating a player", "dribble_skill_move_beat"),
    E("Players beaten without a skill move", "dribble_beat_without_skill_move"),
    E("Possession won", "possession_won"),
    E("Possession lost", "possession_lost"),
    E("Won · defence", "possession_won_defensive_third"),
    E("Won · midfield", "possession_won_middle_third"),
    E("Won · attack", "possession_won_attacking_third"),
    E("Lost · defence", "possession_lost_defensive_third"),
    E("Lost · midfield", "possession_lost_middle_third"),
    E("Lost · attack", "possession_lost_attacking_third"),
    E("Aerial wins", "aerial_duels_won"),
    E("Aerial wins · attacking", "aerial_duels_won_attacking"),
  ],
  Goalkeeping: [
    N("Saves", "saves"),
    N("Goals conceded", "goalsconceded"),
    N("Clean sheets", "cleansheetsgk"),
    N("Diving saves", "ballDiveSaves"),
    N("Cross saves", "crossSaves"),
    N("Good-direction saves", "goodDirectionSaves"),
    N("Parries", "parrySaves"),
    N("Punches", "punchSaves"),
    N("Reflex saves", "reflexSaves"),
  ],
  Discipline: [
    E("Yellow cards", "yellow_cards"),
    N("Red cards", "redcards"),
    E("Fouls committed", "fouls_conceded"),
    E("Fouls committed · defence", "fouls_conceded_defensive_third"),
    E("Fouls won", "fouls_won"),
    E("Penalties conceded", "penalties_conceded"),
    E("Corners conceded", "corners_conceded"),
    E("Corners taken", "corners_attempted"),
  ],
  Positioning: [
    E("Out of position", "out_of_position"),
    E("Out of position · level 1", "out_of_position_severity_1"),
    E("Out of position · level 2", "out_of_position_severity_2"),
    E("Out of position · level 3", "out_of_position_severity_3"),
    E("Out of position · level 4", "out_of_position_severity_4"),
    E("Out of position · level 5", "out_of_position_severity_5"),
    E("Good-position feedback", "good_position_feedback"),
  ],
  Mistakes: [
    E("Possession lost", "possession_lost"),
    E("Lost in defence", "possession_lost_defensive_third"),
    E("Lost in midfield", "possession_lost_middle_third"),
    E("Lost in attack", "possession_lost_attacking_third"),
    E("Passes failed", "passes_failed"),
    E("Offside passes", "offside_passes"),
    E("Tackles lost", "tackles_lost"),
    E("Dangerous tackles", "dangerous_tackles"),
    E("Fouls committed", "fouls_conceded"),
    E("Penalties conceded", "penalties_conceded"),
    E("Out of position", "out_of_position"),
    E("Yellow cards", "yellow_cards"),
    N("Red cards", "redcards"),
  ],
  Decisions: [
    E("Use the ball", "feedback_use_ball"),
    E("Pick your pass", "feedback_pick_pass"),
    E("No good option", "feedback_no_good_option"),
    E("Good option", "feedback_good_option"),
    E("Best option", "feedback_best_option"),
    E("Pass elsewhere", "feedback_pass_elsewhere"),
    E("Chose to pass", "feedback_chose_pass"),
  ],
};
function statNumber(p, field, perMatch = false) {
  let value =
    field.type === "named"
      ? p.named[field.key]
      : field.type === "events"
        ? p.event_games
          ? p.events[field.key]
          : null
        : p[field.key];
  return numeric(value)
    ? perMatch && field.type !== "ratio"
      ? value / (p.games || 1)
      : value
    : null;
}
function statValue(p, field, perMatch = average) {
  const value = statNumber(p, field, perMatch);
  if (value == null) return "—";
  if (field.type === "ratio") return num(value, 1) + "%";
  return num(value, perMatch ? 2 : 0);
}
const STAT_ICONS = {
  Attack:
    '<circle cx="12" cy="12" r="9"/><path d="m12 7 5 4-2 6H9l-2-6zM12 3v4m9 5-4-1m1 9-3-3M6 20l3-3M3 12l4-1"/>',
  Passing: '<path d="M4 7h14m-4-4 4 4-4 4M20 17H6m4-4-4 4 4 4"/>',
  Defence: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6"/>',
  "Ball control":
    '<circle cx="6" cy="18" r="3"/><path d="M7 5c12-5 18 8 5 10m3-4-3 4 5 1"/>',
  Goalkeeping:
    '<path d="M3 19V5h18v14M7 5v14m5-14v14m5-14v14M3 10h18M3 15h18"/>',
  Discipline:
    '<rect x="5" y="3" width="13" height="18" rx="2"/><path d="M10 7h3m-3 5h3m-3 5h3"/>',
  Positioning:
    '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/>',
  Mistakes: '<path d="m12 3 10 18H2zM12 9v5m0 3h.01"/>',
  Decisions: '<path d="M12 21V11m0 0L5 4m7 7 7-7M5 9V4h5m4 0h5v5"/>',
  Pitch:
    '<rect x="2" y="5" width="20" height="14" rx="1"/><path d="M12 5v14M2 9h4v6H2m20-6h-4v6h4"/><circle cx="12" cy="12" r="3"/>',
};
function categoryTabs(group, scope) {
  return `<div class="stat-tabs" role="group" aria-label="${esc(scope)} stat categories">${[...Object.keys(GROUPS), "Pitch"].map((g) => `<button class="stat-tab ${g === group ? "active" : ""}" data-stat-scope="${scope}" data-stat-group="${esc(g)}" aria-pressed="${g === group}"><svg viewBox="0 0 24 24" aria-hidden="true">${STAT_ICONS[g]}</svg><span>${esc(g)}</span></button>`).join("")}</div>`;
}
// Presentation relationships are shared by lists and comparisons; Trends stay flat.
const STAT_HIERARCHY = [
  {
    key: "goals",
    children: [
      ["goals_first_time", "First time"],
      ["goals_weak_foot", "Weak foot"],
      ["goals_off_post", "Off the post"],
    ],
  },
  { key: "assists", children: [["assists_through_ball", "Through ball"]] },
  {
    key: "shots",
    children: [
      ["shots_on_target", "On target"],
      ["shots_off_target", "Off target"],
    ],
  },
  ...["on", "off"].map((target) => ({
    key: `shots_${target}_target`,
    children: [
      [`shots_${target}_target_inside_box`, "Inside box"],
      [`shots_${target}_target_outside_box`, "Outside box"],
    ],
  })),
  ...[
    ["passesmade", "completed"],
    ["passes_failed", "failed"],
  ].map(([key, outcome]) => ({
    key,
    children: [
      ...["forward", "sideways", "backward"].map((direction) => [
        `passes_${direction}_${outcome}`,
        direction[0].toUpperCase() + direction.slice(1),
      ]),
      ...["short", "medium", "long"].map((distance) => [
        `passes_${distance}_${outcome}`,
        distance[0].toUpperCase() + distance.slice(1),
      ]),
    ],
  })),
  ...["won", "lost"].map((action) => ({
    key: `possession_${action}`,
    children: [
      ["defensive", "Defence"],
      ["middle", "Midfield"],
      ["attacking", "Attack"],
    ].map(([zone, label]) => [`possession_${action}_${zone}_third`, label]),
  })),
  {
    key: "aerial_duels_won",
    children: [
      ["aerial_duels_won_attacking", "Attacking"],
      ["aerial_duels_won_defending", "Defending"],
    ],
  },
  {
    key: "fouls_conceded",
    children: [["fouls_conceded_defensive_third", "In defence"]],
  },
  {
    key: "out_of_position",
    children: [1, 2, 3, 4, 5].map((level) => [
      `out_of_position_severity_${level}`,
      `Level ${level}`,
    ]),
  },
  {
    key: "saves",
    children: [
      ["ballDiveSaves", "Diving"],
      ["crossSaves", "Crosses"],
      ["goodDirectionSaves", "Good direction"],
      ["parrySaves", "Parries"],
      ["punchSaves", "Punches"],
      ["reflexSaves", "Reflex"],
    ],
  },
];
function statTree(fields) {
  const nodes = new Map(
      fields.map((field) => [field.key, { field, children: [] }]),
    ),
    nested = new Set();
  for (const spec of STAT_HIERARCHY) {
    const parent = nodes.get(spec.key);
    if (!parent) continue;
    for (const [key, label] of spec.children) {
      const child = nodes.get(key);
      if (!child) continue;
      child.field = { ...child.field, label };
      parent.children.push(child);
      nested.add(key);
    }
  }
  return fields
    .filter((field) => !nested.has(field.key))
    .map((field) => nodes.get(field.key));
}
function groupedStats(p, fields, perMatch) {
  const renderNode = (node, depth = 0) =>
    `<div class="stat-node"><div class="stat-row" data-stat-field="${esc(node.field.key)}" data-stat-depth="${depth}">${statHelpLabel(node.field.label, node.field.key, "stat-name", perMatch && node.field.type !== "ratio")}<strong>${statValue(p, node.field, perMatch)}</strong></div>${node.children.length ? `<div class="stat-children">${node.children.map((child) => renderNode(child, depth + 1)).join("")}</div>` : ""}</div>`;
  return `<div class="stat-list hierarchical-stats">${statTree(fields)
    .map((node) => renderNode(node))
    .join("")}</div>`;
}
function statCategory(p, group, scope, perMatch = average) {
  return `${categoryTabs(group, scope)}<div class="section-heading stat-heading"><h2>${esc(group)}</h2></div>${group === "Pitch" ? pitchPanel(p, scope, perMatch) : groupedStats(p, GROUPS[group], perMatch)}`;
}

function pitchControls(scope) {
  const mode = pitchModes[scope];
  return `<div class="segments small" role="group" aria-label="Pitch statistic"><button class="${mode === "possession" ? "active" : ""}" data-pitch-scope="${scope}" data-pitch-mode="possession">Possession</button><button class="${mode === "shots" ? "active" : ""}" data-pitch-scope="${scope}" data-pitch-mode="shots">Shots</button></div>`;
}
function pitchPanel(p, scope, perMatch = false, controls = true) {
  const mode = pitchModes[scope],
    e = p.events;
  const value = (k) =>
    p.event_games ? (e[k] || 0) / (perMatch ? p.games || 1 : 1) : null;
  const zones =
    mode === "possession"
      ? ["defensive", "middle", "attacking"].map((third, i) => ({
          label: ["Defence", "Midfield", "Attack"][i],
          a: value(`possession_won_${third}_third`),
          b: value(`possession_lost_${third}_third`),
        }))
      : [
          {
            label: "Outside box",
            a: value("shots_on_target_outside_box"),
            b: value("shots_off_target_outside_box"),
          },
          {
            label: "Inside box",
            a: value("shots_on_target_inside_box"),
            b: value("shots_off_target_inside_box"),
          },
        ];
  const labels =
    mode === "possession" ? ["Won", "Lost"] : ["On target", "Off target"];
  let field =
    '<rect class="pitch-grass" x="20" y="30" width="600" height="240" rx="3"/>';
  if (mode === "possession")
    zones.forEach((z, i) => {
      field += `<rect class="pitch-zone" x="${20 + i * 200}" y="30" width="200" height="240"/><path class="pitch-divider" d="M${20 + i * 200} 30V270"/>`;
    });
  else
    field +=
      '<path class="pitch-zone" fill-rule="evenodd" d="M20 30H620V270H20Z M510 90H620V210H510Z"/><rect class="pitch-box-zone" x="510" y="90" width="110" height="120"/>';
  field +=
    '<g class="pitch-lines"><rect x="20" y="30" width="600" height="240" rx="3"/><path d="M320 30V270M20 90H130V210H20M620 90H510V210H620M20 120H60V180H20M620 120H580V180H620"/><circle cx="320" cy="150" r="35"/><circle cx="320" cy="150" r="2"/><path d="M130 125a30 30 0 0 1 0 50M510 125a30 30 0 0 0 0 50M10 135H20V165H10Z M620 135H630V165H620Z"/></g>';
  field +=
    '<text class="pitch-direction" x="320" y="16" text-anchor="middle">Attacking →</text>';
  zones.forEach((z, i) => {
    const x = mode === "possession" ? 120 + i * 200 : [398, 565][i],
      y = 105;
    field += `<g class="pitch-zone-count" data-zone="${esc(z.label)}"><title>${esc(`${z.label}: ${labels[0]} ${num(z.a, 2)}, ${labels[1]} ${num(z.b, 2)}`)}</title><rect class="pitch-count-back" x="${x - 56}" y="${y}" width="112" height="90" rx="7"/><text class="pitch-zone-name" x="${x}" y="${y + 22}" text-anchor="middle">${esc(z.label)}</text><text class="pitch-won" x="${x}" y="${y + 53}" text-anchor="middle">${num(z.a, perMatch ? 2 : 0)}</text><text class="pitch-lost" x="${x}" y="${y + 80}" text-anchor="middle">${num(z.b, perMatch ? 2 : 0)}</text></g>`;
  });
  return `<div class="pitch-panel">${controls ? `<div class="pitch-toolbar">${pitchControls(scope)}<span class="small-text">${perMatch ? "Per match" : "Totals"}</span></div>` : ""}<div class="legend pitch-legend"><span class="key lime"></span>${labels[0]} <span class="key rose"></span>${labels[1]}</div><svg class="pitch" viewBox="0 0 640 290" role="img" aria-label="${esc(`${p.name || "Team"} ${mode === "possession" ? "possession won and lost by pitch third" : "shots on and off target inside and outside the box"}${perMatch ? " per match" : ""}`)}">${field}</svg><p class="pitch-caption">${mode === "possession" ? "By pitch third" : "Inside & outside the penalty area"}</p></div>`;
}
function renderTeamStats() {
  const a = data.archive,
    n = a.team_named,
    e = a.events;
  const stats = {
    games: a.games,
    named: { ...n, goalsconceded: a.outcomes.goalsAgainst },
    events: e,
    event_games: a.event_player_rows,
    pass_completion: pct(n.passesmade, n.passattempts),
    tackle_success: pct(n.tacklesmade, n.tackleattempts),
    shot_conversion: pct(n.goals, n.shots),
    shots_on_target_rate: pct(e.shots_on_target, e.shots),
  };
  $("teamStats").innerHTML = a.games
    ? statCategory(stats, teamCategory, "team", teamAverage)
    : empty();
}
function statList(rows) {
  return `<div class="stat-list">${rows.map(([label, value]) => `<div>${statHelpLabel(label)}<strong>${esc(value)}</strong></div>`).join("")}</div>`;
}
function playerSummary(p) {
  const rows = [
    ["Goals + assists / match", displayPlayer(p, "contributions_per_game")],
  ];
  if (p.cumulative) {
    const percentage = (v) => (v == null ? "—" : num(v, 1) + "%");
    rows.push(
      ["Win rate", percentage(p.winRate)],
      ["Pass accuracy", percentage(p.passSuccessRate)],
      ["Shot success", percentage(p.shotSuccessRate)],
      ["Tackle success", percentage(p.tackleSuccessRate)],
    );
  }
  if (p.cumulative)
    rows.push(
      ["Red cards", displayPlayer(p, "redCards")],
      ["Defender clean sheets", displayPlayer(p, "cleanSheetsDef")],
      ["Goalkeeper clean sheets", displayPlayer(p, "cleanSheetsGK")],
    );
  return `<section class="player-summary"><div class="section-heading"><h2>${p.cumulative ? "Club summary" : "Match summary"}</h2></div>${statList(rows)}</section>`;
}
function choosePlayersView(view) {
  playersView = view;
  $("playersRoster").hidden = view !== "roster";
  $("headToHead").hidden = view !== "compare";
  document.querySelectorAll("[data-players-view]").forEach((el) => {
    el.classList.toggle("active", el.dataset.playersView === view);
    el.setAttribute("aria-pressed", String(el.dataset.playersView === view));
  });
  if (view === "compare") renderHeadToHead();
}
function duelRows(left, right, fields) {
  const renderRow = (field) => {
    const count = field.type === "named" || field.type === "events";
    const a = statNumber(left, field, compareAverage && count),
      b = statNumber(right, field, compareAverage && count),
      max = Math.max(a || 0, b || 0, 1);
    const format = (v) =>
      v == null
        ? "—"
        : num(
            v,
            field.type === "ratio"
              ? 1
              : (field.decimals ?? (compareAverage && count ? 2 : 0)),
          ) + (field.type === "ratio" ? "%" : "");
    const side = (v, colour, align) =>
      `<div class="duel-value ${align}"><strong class="duel-number">${esc(format(v))}</strong><svg viewBox="0 0 100 5" preserveAspectRatio="none" aria-hidden="true"><rect x="${align === "left" ? 100 - ((v || 0) / max) * 100 : 0}" width="${((v || 0) / max) * 100}" height="5" rx="2" fill="${colour}"/></svg></div>`;
    return `<div class="duel-row" data-compare-field="${esc(field.key)}">${side(a, COLOURS.lime, "left")}<span>${statHelpLabel(field.label, field.key, "", compareAverage && count)}</span>${side(b, COLOURS.blue, "right")}</div>`;
  };
  const renderNode = (node, depth = 0) =>
    `<div class="duel-node" data-stat-depth="${depth}">${renderRow(node.field)}${node.children.length ? `<div class="duel-children">${node.children.map((child) => renderNode(child, depth + 1)).join("")}</div>` : ""}</div>`;
  return `<div class="duel-stats">${statTree(fields)
    .map((node) => renderNode(node))
    .join("")}</div>`;
}
function renderHeadToHead() {
  const players = [...data.archive.players].sort((a, b) =>
    a.name.localeCompare(b.name),
  );
  if (players.length < 2) {
    $("headToHead").innerHTML =
      `<div class="section-heading"><h2>Head to head</h2><span>${esc(windowLabel())}</span></div>${empty("Choose a period with at least two players.")}`;
    return;
  }
  if (!players.some((p) => p.id === compareLeft)) compareLeft = players[0].id;
  if (
    !players.some((p) => p.id === compareRight) ||
    compareRight === compareLeft
  )
    compareRight = players.find((p) => p.id !== compareLeft).id;
  const enrich = (p) => ({
    ...p,
    winRate: pct(p.W, p.games),
    contributions_per_game: p.games
      ? ((p.named.goals || 0) + (p.named.assists || 0)) / p.games
      : null,
  });
  const left = enrich(players.find((p) => p.id === compareLeft)),
    right = enrich(players.find((p) => p.id === compareRight));
  const selector = (selected, other, id) =>
    `<label><span class="sr-only">${id === "compareLeft" ? "First player" : "Second player"}</span><select id="${id}">${players.map((p) => `<option value="${esc(p.id)}" ${p.id === selected ? "selected" : ""} ${p.id === other ? "disabled" : ""}>${esc(p.name)}</option>`).join("")}</select><span class="small-text">${num(players.find((p) => p.id === selected).games)} matches</span></label>`;
  let body = `<div class="section-heading"><h2>Head to head</h2><span>${esc(windowLabel())}</span><div class="segments small" role="group" aria-label="Comparison count display"><button class="${!compareAverage ? "active" : ""}" data-compare-average="total">Totals</button><button class="${compareAverage ? "active" : ""}" data-compare-average="average">Per match</button></div></div><div class="duel-players">${selector(compareLeft, compareRight, "compareLeft")}<span class="duel-vs">vs</span>${selector(compareRight, compareLeft, "compareRight")}</div>`;
  body += duelRows(left, right, [
    { label: "Rating", key: "rating", type: "value", decimals: 2 },
    R("Win rate", "winRate"),
    {
      label: "Goals + assists / match",
      key: "contributions_per_game",
      type: "value",
      decimals: 2,
    },
  ]);
  body += categoryTabs(compareCategory, "compare");
  if (compareCategory === "Pitch")
    body += `<div class="pitch-toolbar"><h2>Pitch</h2>${pitchControls("compare")}</div><div class="duel-pitches"><div><h3>${esc(left.name)}</h3>${pitchPanel(left, "compare", compareAverage, false)}</div><div><h3>${esc(right.name)}</h3>${pitchPanel(right, "compare", compareAverage, false)}</div></div>`;
  else
    body += `<div class="section-heading stat-heading"><h2>${esc(compareCategory)}</h2></div>${duelRows(left, right, GROUPS[compareCategory])}`;
  $("headToHead").innerHTML = body;
}
function renderPlayerDetail(key) {
  const p = playerRows().find((p) => p.key === key);
  if (!p) {
    selectedPlayer = null;
    $("playerDetail").hidden = true;
    return;
  }
  selectedPlayer = key;
  const a = archivePlayer(p);
  $("playerDetail").hidden = false;
  const label = p.cumulative ? "Club totals" : `${p.games} captured matches`;
  let body = `<div class="detail-head"><div><p class="detail-caption">${esc(label)}</p><h2>${esc(p.name)}</h2></div><div class="detail-actions">${a ? `<button class="text-button" data-compare-player="${esc(a.id)}">Head to head ↔</button>` : ""}<button data-close-player class="text-button">Close ×</button></div></div><div class="player-count-toolbar"><div class="segments small" role="group" aria-label="Player detail count display"><button class="${!average ? "active" : ""}" aria-pressed="${!average}" data-detail-average="total">Totals</button><button class="${average ? "active" : ""}" aria-pressed="${average}" data-detail-average="average">Per match</button></div></div><div class="cards compact">${card("Games", num(p.games)) + card(average ? "Goals / match" : "Goals", displayPlayer(p, "goals")) + card(average ? "Assists / match" : "Assists", displayPlayer(p, "assists")) + card(average ? "MOTM / match" : "MOTM", displayPlayer(p, "manOfTheMatch"))}</div>`;
  body += playerSummary(p);
  const first = (data.initial_player_history || []).find(
    (i) =>
      (i.id && i.id === p.id) || i.name === p.name || a?.names.includes(i.name),
  );
  const missing = first?.missing_matches;
  const historical =
    missing > 0
      ? `Detailed stats exclude the first ${num(missing)} ${missing === 1 ? "match" : "matches"}. `
      : "";
  body += `<p class="player-history-note">${esc(historical)}${a ? `Showing ${num(a.games)} ${a.games === 1 ? "match" : "matches"}${query ? " in the selected period" : ""}.` : "No detailed matches in this period."}</p>`;
  if (a) {
    const history = [...a.history]
      .reverse()
      .map((p) => ({ ...p, id: p.match_id }));
    body += `<section class="stats-group"><div class="section-heading"><h2>Match stats</h2><span>${a.games} matches</span></div>${statCategory(a, category, "player")}</section>`;
    body += `<section class="player-record"><div class="section-heading"><h2>Match record</h2><span>${a.games} matches</span></div>${statList(
      [
        ["Wins", num(a.W)],
        ["Draws", num(a.D)],
        ["Losses", num(a.L)],
        ["Win rate", num(pct(a.W, a.games), 1) + (a.games ? "%" : "")],
        [
          "Goals + assists / match",
          num(
            a.games
              ? ((a.named.goals || 0) + (a.named.assists || 0)) / a.games
              : null,
            2,
          ),
        ],
      ],
    )}</section>`;
    body += `<div class="section-heading"><h2>Match performance</h2><span>${a.games} matches</span></div><div class="detail-grid"><div><div class="section-heading"><h2>Rating</h2><strong>${num(a.rating, 2)}</strong></div>${lineChart(history, [{ key: "rating", label: "Rating", colour: COLOURS.lime }], `${p.name} match ratings`, { bounds: [0, 10], compact: true })}</div><div><div class="section-heading"><h2>Goals & assists</h2><div class="legend"><span class="key lime"></span>Goals <span class="key blue"></span>Assists</div></div>${lineChart(
      history,
      [
        { key: "goals", label: "Goals", colour: COLOURS.lime },
        { key: "assists", label: "Assists", colour: COLOURS.blue },
      ],
      `${p.name} goals and assists`,
      { compact: true },
    )}</div></div>`;
  } else body += empty("No match performances yet.");
  body += `<section class="stats-group" id="playerTrend"></section>`;
  $("playerDetail").innerHTML = body;
  renderTrend("player");
}
function renderMatches() {
  const matches = data.archive.matches.filter((m) =>
    m.opponent.toLowerCase().includes($("matchSearch").value.toLowerCase()),
  );
  const pages = Math.max(1, Math.ceil(matches.length / 20));
  matchPage = Math.min(matchPage, pages - 1);
  $("matchCount").textContent = `${num(data.archive.games)} matches`;
  $("matchTable").innerHTML = table(
    ["Date", "Opponent", "Score", "Result", "Type", ""],
    matches.slice(matchPage * 20, (matchPage + 1) * 20).map((m) => [
      `${esc(date(m.timestamp))}<div class="small-text">${esc(time(m.timestamp))}</div>`,
      matchLink(m.id, m.opponent),
      `<span class="score">${m.goals}–${m.goalsAgainst}</span>`,
      resultBadge(m.result),
      esc(
        m.types
          .map(
            (t) =>
              ({
                league: "League",
                friendly: "Friendly",
                playoff: "Playoff",
              })[t] || t,
          )
          .join(", "),
      ),
      matchLink(m.id, "View ↗"),
    ]),
  );
  $("pagination").innerHTML =
    matches.length > 20
      ? `<span>${matchPage * 20 + 1}–${Math.min(matches.length, (matchPage + 1) * 20)} of ${num(matches.length)}</span><button data-page="-1" ${matchPage === 0 ? "disabled" : ""}>Previous</button><button data-page="1" ${matchPage === pages - 1 ? "disabled" : ""}>Next</button>`
      : "";
  $("opponents").innerHTML = table(
    ["Opponent", "Games", "Wins", "Draws", "Losses", "Goals"],
    [...data.archive.opponents]
      .sort((a, b) => b.matches - a.matches)
      .map((p) => [
        esc(p.name),
        p.matches,
        p.W,
        p.D,
        p.L,
        `${p.goals}–${p.goalsAgainst}`,
      ]),
  );
}
function matchStats(players) {
  const named = {},
    events = {};
  let ratingSum = 0,
    rated = 0,
    eventGames = 0;
  Object.values(players).forEach((p) => {
    if (Number(p.raw.rating) > 0) {
      ratingSum += Number(p.raw.rating);
      rated++;
    }
    Object.entries(p.raw).forEach(([k, v]) => {
      if (
        numeric(v) &&
        ![
          "rating",
          "namespace",
          "archetypeid",
          "gameTime",
          "secondsPlayed",
          "userResult",
          "SCORE",
          "realtimegame",
          "realtimeidle",
          "vprohackreason",
        ].includes(k)
      )
        named[k] = (named[k] || 0) + v;
    });
    Object.entries(p.decoded).forEach(
      ([k, v]) => (events[k] = (events[k] || 0) + v.value),
    );
    if (Object.keys(p.events).length) eventGames++;
  });
  return {
    games: 1,
    named,
    events,
    event_games: eventGames,
    rating: rated ? ratingSum / rated : null,
    pass_completion: pct(named.passesmade, named.passattempts),
    tackle_success: pct(named.tacklesmade, named.tackleattempts),
    shot_conversion: pct(named.goals, named.shots),
    shots_on_target_rate: eventGames
      ? pct(events.shots_on_target, events.shots)
      : null,
  };
}
function matchComparison(left, right) {
  const rows = [
    ["Shots", left.named.shots, right.named.shots],
    [
      "On target",
      left.event_games ? left.events.shots_on_target : null,
      right.event_games ? right.events.shots_on_target : null,
    ],
    ["Pass accuracy", left.pass_completion, right.pass_completion, "%"],
    ["Tackles", left.named.tacklesmade, right.named.tacklesmade],
    [
      "Interceptions",
      left.event_games ? left.events.interceptions : null,
      right.event_games ? right.events.interceptions : null,
    ],
    ["Saves", left.named.saves, right.named.saves],
    ["Rating", left.rating, right.rating],
  ];
  return `<div class="match-comparison">${rows
    .map(([label, a, b, suffix = ""]) => {
      const max = Math.max(a || 0, b || 0, 1),
        bar = (value, colour, align) =>
          `<span class="side-value">${num(value, label === "Rating" || suffix ? 1 : 0)}${value == null ? "" : suffix}<svg viewBox="0 0 100 5" preserveAspectRatio="none" aria-hidden="true"><rect x="${align === "right" ? 100 - ((value || 0) / max) * 100 : 0}" width="${((value || 0) / max) * 100}" height="5" rx="2" fill="${colour}"/></svg></span>`;
      return `<div class="comparison-row">${bar(a, COLOURS.lime, "right")}<span>${esc(label)}</span>${bar(b, COLOURS.rose, "left")}</div>`;
    })
    .join("")}</div>`;
}
async function showMatch(id) {
  const version = ++matchRequest;
  openMatchId = id;
  matchPayload = null;
  matchPlayer = null;
  matchCategory = "Attack";
  $("matchDate").textContent = "";
  $("matchDetail").innerHTML = empty("Loading match…");
  if (!$("matchDialog").open) $("matchDialog").showModal();
  try {
    const response = await fetch("/api/matches/" + encodeURIComponent(id));
    if (!response.ok) throw new Error("Could not load this match.");
    const payload = await response.json();
    if (version !== matchRequest || !$("matchDialog").open) return;
    matchPayload = payload;
    renderMatchDetail();
  } catch (error) {
    if (version === matchRequest) $("matchDetail").textContent = error.message;
  }
}
function renderMatchDetail() {
  const payload = matchPayload,
    ownId = String(data.club.id),
    otherId = Object.keys(payload.raw.clubs).find((id) => id !== ownId);
  const own = payload.raw.clubs[ownId],
    other = payload.raw.clubs[otherId] || {};
  const ownPlayers = payload.decoded_players[ownId] || {},
    otherPlayers = payload.decoded_players[otherId] || {};
  const stats = matchStats(ownPlayers),
    otherStats = matchStats(otherPlayers);
  // Every outfield player can repeat the conceded score; team goals conceded
  // comes from the club score rather than adding those player copies.
  stats.named.goalsconceded = Number(own.goalsAgainst);
  $("matchDate").textContent = stamp(payload.raw.timestamp);
  let body = `<div class="scoreboard"><span class="team-name">${esc(own.details?.name || data.club.name)}</span><strong class="big-score">${num(own.goals)}–${num(own.goalsAgainst)}</strong><span class="team-name">${esc(other.details?.name || "Opponent")}</span></div>${matchComparison(stats, otherStats)}`;
  for (const [teamId, players] of [
    [ownId, ownPlayers],
    [otherId, otherPlayers],
  ]) {
    body += `<div class="match-team-title"><h3>${esc(payload.raw.clubs[teamId]?.details?.name || "Players")}</h3></div><div class="table-wrap">${table(
      [
        "Player",
        "Rating",
        "Goals",
        "Assists",
        "Shots",
        "Pass %",
        "Tackles",
        "MOTM",
      ],
      Object.entries(players).map(([pid, p]) => [
        `<button class="player-link" data-match-player="${esc(teamId + ":" + pid)}">${esc(p.raw.playername)}</button>`,
        num(Number(p.raw.rating) > 0 ? Number(p.raw.rating) : null, 2),
        num(p.raw.goals),
        num(p.raw.assists),
        num(p.raw.shots),
        num(p.ratios.pass_completion, 1) +
          (p.ratios.pass_completion == null ? "" : "%"),
        num(p.raw.tacklesmade),
        p.raw.mom ? "★" : "—",
      ]),
    )}</div>`;
  }
  let chosen = stats,
    title = "Team stats";
  if (matchPlayer) {
    const [cid, pid] = matchPlayer.split(":"),
      p = payload.decoded_players[cid]?.[pid];
    if (p) {
      chosen = matchStats({ [pid]: p });
      title = p.raw.playername;
    }
  }
  body += `<section class="stats-group"><div class="section-heading"><h2>${esc(title)}</h2>${matchPlayer ? '<button data-match-team class="text-button">Team stats ↗</button>' : ""}</div>${statCategory(chosen, matchCategory, "match", false)}</section>`;
  $("matchDetail").innerHTML = body;
}
let trendData = null,
  trendError = false;
const trendSettings = {
  team: {
    group: "Attack",
    metric: "named:goals",
    period: "match",
    window: 5,
    mode: "average",
  },
  player: {
    group: "Passing",
    metric: "ratio:pass_completion",
    period: "match",
    window: 5,
    mode: "average",
  },
};
function trendFields(group, scope) {
  return group === "Results"
    ? [
        { label: "Rating", type: "rating", key: "rating" },
        R("Win rate", "win_rate"),
        N("Goals conceded", "goalsconceded"),
        {
          label: "Goals + assists",
          type: "contributions",
          key: "contributions",
        },
      ]
    : GROUPS[group].map((f) =>
        scope === "team" && f.type === "named" && f.key === "goals"
          ? { ...f, type: "score" }
          : f,
      );
}
function trendRatio(field, rows) {
  const pairs = {
    pass_completion: ["named", "passesmade", "passattempts"],
    tackle_success: ["named", "tacklesmade", "tackleattempts"],
    shot_conversion: ["named", "goals", "shots"],
    shots_on_target_rate: ["events", "shots_on_target", "shots"],
  };
  if (field.key === "win_rate")
    return { n: rows.filter((r) => r.result === "W").length, d: rows.length };
  const [type, n, d] = pairs[field.key],
    valid = rows.filter(
      (r) => r[type] != null && numeric(r[type][n]) && numeric(r[type][d]),
    );
  return {
    n: valid.reduce((s, r) => s + r[type][n], 0),
    d: valid.reduce((s, r) => s + r[type][d], 0),
  };
}
function trendValue(field, rows, mode = "average") {
  if (field.type === "ratio") {
    const { n, d } = trendRatio(field, rows);
    return pct(n, d);
  }
  if (field.type === "rating") {
    const valid = rows.filter((r) => numeric(r.rating) && r.rating > 0),
      weight = (r) => r.rated_games ?? 1;
    const total = valid.reduce((s, r) => s + weight(r), 0);
    return total
      ? valid.reduce((s, r) => s + r.rating * weight(r), 0) / total
      : null;
  }
  const values = rows
    .map((r) =>
      field.type === "score"
        ? r.goals
        : field.type === "contributions"
          ? numeric(r.named?.goals) && numeric(r.named?.assists)
            ? r.named.goals + r.named.assists
            : null
          : r[field.type]?.[field.key],
    )
    .filter(numeric);
  return values.length
    ? values.reduce((s, v) => s + v, 0) /
        (mode === "average" ? values.length : 1)
    : null;
}
function trendPeriodStart(timestamp, period) {
  const d = new Date(timestamp * 1000);
  d.setHours(0, 0, 0, 0);
  if (period === "week") d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  if (period === "month") d.setDate(1);
  return d.getTime() / 1000;
}
function trendBuckets(rows, period) {
  if (period === "match") return rows.map((r) => [r]);
  const groups = new Map();
  for (const row of rows) {
    const key = trendPeriodStart(row.timestamp, period);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  return [...groups.values()];
}
function trendDateRange(rows) {
  if (!rows.length) return "";
  const first = new Date(rows[0].timestamp * 1000);
  const last = new Date(rows.at(-1).timestamp * 1000);
  const format = (d) =>
    d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      ...(first.getFullYear() !== last.getFullYear()
        ? { year: "numeric" }
        : {}),
    });
  const start = format(first),
    end = format(last);
  return start === end ? start : `${start} – ${end}`;
}
function trendWindowValue(field, buckets, settings) {
  if (
    settings.mode === "total" &&
    settings.period !== "match" &&
    ["named", "events", "score", "contributions"].includes(field.type)
  ) {
    const values = buckets
      .map((b) => trendValue(field, b, "total"))
      .filter(numeric);
    return values.length
      ? values.reduce((s, v) => s + v, 0) / values.length
      : null;
  }
  return trendValue(field, buckets.flat(), "average");
}
function makeTrendPoints(rows, field, settings) {
  const buckets = trendBuckets(rows, settings.period);
  return buckets.map((bucket, i) => {
    const value = trendValue(field, bucket, settings.mode),
      window = settings.window;
    const recent = buckets.slice(Math.max(0, i - window + 1), i + 1);
    return {
      timestamp:
        settings.period === "match"
          ? bucket[0].timestamp
          : trendPeriodStart(bucket[0].timestamp, settings.period),
      id:
        settings.period === "match" ? bucket[0].id || bucket[0].match_id : null,
      opponent:
        settings.period === "match"
          ? bucket[0].opponent
          : `${bucket.length} matches`,
      value,
      rolling:
        window && i >= window - 1 && numeric(value)
          ? trendWindowValue(field, recent, settings)
          : null,
    };
  });
}
function renderTrend(scope) {
  const el = $(scope === "team" ? "teamTrend" : "playerTrend");
  if (!el) return;
  const settings = trendSettings[scope],
    player =
      scope === "player"
        ? playerRows().find((p) => p.key === selectedPlayer)
        : null;
  const archived = player ? archivePlayer(player) : null;
  const rows =
    (scope === "team"
      ? trendData?.team
      : trendData?.players.find((p) => p.id === archived?.id)?.history) || [];
  const groups = ["Results", ...Object.keys(GROUPS)];
  const fields = trendFields(settings.group, scope);
  let field =
    fields.find((f) => `${f.type}:${f.key}` === settings.metric) || fields[0];
  if (field) settings.metric = `${field.type}:${field.key}`;
  const select = (name, label, options) =>
    `<label>${label}<select data-trend-scope="${scope}" data-trend-setting="${name}" aria-label="${scope === "team" ? "Team" : "Player"} trend ${label.toLowerCase()}">${options.map(([value, text]) => `<option value="${value}" ${String(settings[name]) === String(value) ? "selected" : ""}>${esc(text)}</option>`).join("")}</select></label>`;
  let controls = select(
    "group",
    "Group",
    groups.map((g) => [g, g]),
  );
  controls += select(
    "metric",
    "Stat",
    fields.map((f) => [`${f.type}:${f.key}`, f.label]),
  );
  controls += select("period", "By", [
    ["match", "Match"],
    ["day", "Day"],
    ["week", "Week"],
    ["month", "Month"],
  ]);
  if (
    field &&
    ["named", "events", "contributions", "score"].includes(field.type) &&
    settings.period !== "match"
  )
    controls += select("mode", "Counts", [
      ["average", "Per match"],
      ["total", "Totals"],
    ]);
  controls += select("window", "Average", [
    [0, "Off"],
    [3, "Last 3"],
    [5, "Last 5"],
    [10, "Last 10"],
  ]);
  const points = field ? makeTrendPoints(rows, field, settings) : [],
    unit = field?.type === "ratio" ? "%" : "";
  const periods = {
    match: "matches",
    day: "days",
    week: "weeks",
    month: "months",
  };
  let delta = "";
  const buckets = trendBuckets(rows, settings.period),
    w = settings.window;
  if (field && w && buckets.length >= w * 2) {
    const recent = trendWindowValue(field, buckets.slice(-w), settings),
      previous = trendWindowValue(field, buckets.slice(-w * 2, -w), settings);
    if (numeric(recent) && numeric(previous))
      delta = `Last ${w} ${periods[settings.period]} vs previous ${w} · ${recent - previous > 0 ? "+" : ""}${num(recent - previous, 2)}${unit ? " pp" : ""}`;
  }
  const rolling = w > 0;
  const rollingLabel = `Last ${w} ${periods[settings.period]} · average`;
  const legend = `<div class="legend"><span class="key blue"></span>${field ? statHelpLabel(field.label, field.key, "") : esc("Stat")}${unit ? ` (${unit})` : ""}${rolling ? ` <span class="key lime"></span>${rollingLabel}` : ""}</div>`;
  const series = [
    { key: "value", label: field?.label || "Value", colour: COLOURS.blue },
    ...(rolling
      ? [{ key: "rolling", label: rollingLabel, colour: COLOURS.lime }]
      : []),
  ];
  const message = trendError
    ? "Could not load trends. Refresh to try again."
    : !trendData
      ? "Loading trends…"
      : !rows.length
        ? "No matches in this period."
        : "No values in this period.";
  const bounds =
    field?.type === "ratio"
      ? [0, 100]
      : field?.type === "rating"
        ? [0, 10]
        : null;
  el.innerHTML = `<div class="section-heading"><h2>Trends</h2><span>${esc(`${rows.length} matches${rows.length ? ` · ${trendDateRange(rows)}` : ""}`)}</span></div><div class="trend-controls">${controls}</div><div class="trend-caption">${legend}<span>${esc(delta)}</span></div>${!trendData ? empty(message) : lineChart(points, series, `${scope} ${field?.label || "stat"} over time`, { temporal: settings.period !== "match", bounds, emptyMessage: message })}`;
}
async function loadTrends(version, filter) {
  trendError = false;
  try {
    const response = await fetch("/api/trends" + filter);
    if (!response.ok) throw new Error();
    const payload = await response.json();
    if (version !== requestVersion) return;
    trendData = payload;
  } catch (error) {
    if (version !== requestVersion) return;
    trendError = true;
  }
  renderTrend("team");
  renderTrend("player");
}

function choosePlayer(key) {
  let p = playerRows().find((p) => p.key === key);
  if (!p) return;
  switchTab("players");
  choosePlayersView("roster");
  renderPlayerDetail(key);
  $("playerDetail").scrollIntoView({ behavior: "smooth", block: "start" });
}
document.addEventListener("click", (event) => {
  const target = event.target.closest("button, [data-player], [data-match]");
  if (!target) return;
  if (target.dataset.tab) switchTab(target.dataset.tab);
  if (target.dataset.go) switchTab(target.dataset.go);
  if (target.dataset.playersView) choosePlayersView(target.dataset.playersView);
  if (target.dataset.comparePlayer) {
    compareLeft = target.dataset.comparePlayer;
    switchTab("players");
    choosePlayersView("compare");
    $("headToHead").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  if (target.dataset.compareAverage) {
    compareAverage = target.dataset.compareAverage === "average";
    renderHeadToHead();
  }
  if (target.dataset.statGroup) {
    const scope = target.dataset.statScope;
    if (scope === "team") {
      teamCategory = target.dataset.statGroup;
      renderTeamStats();
    }
    if (scope === "player") {
      category = target.dataset.statGroup;
      renderPlayerDetail(selectedPlayer);
    }
    if (scope === "match") {
      matchCategory = target.dataset.statGroup;
      renderMatchDetail();
    }
    if (scope === "compare") {
      compareCategory = target.dataset.statGroup;
      renderHeadToHead();
    }
    document
      .querySelector(
        `[data-stat-scope="${scope}"][data-stat-group="${target.dataset.statGroup}"]`,
      )
      ?.focus({ preventScroll: true });
  }
  if (target.dataset.pitchMode) {
    const scope = target.dataset.pitchScope;
    pitchModes[scope] = target.dataset.pitchMode;
    if (scope === "team") renderTeamStats();
    if (scope === "player") renderPlayerDetail(selectedPlayer);
    if (scope === "match") renderMatchDetail();
    if (scope === "compare") renderHeadToHead();
    document
      .querySelector(
        `[data-pitch-scope="${scope}"][data-pitch-mode="${target.dataset.pitchMode}"]`,
      )
      ?.focus({ preventScroll: true });
  }
  if (target.dataset.overviewAverage) {
    overviewAverage = target.dataset.overviewAverage === "average";
    renderOverviewStats();
  }
  if (target.dataset.teamAverage) {
    teamAverage = target.dataset.teamAverage === "average";
    document
      .querySelectorAll("[data-team-average]")
      .forEach((el) => el.classList.toggle("active", el === target));
    renderTeamStats();
  }
  if (target.dataset.detailAverage) {
    average = target.dataset.detailAverage === "average";
    renderPlayers();
    document
      .querySelector(`[data-detail-average="${target.dataset.detailAverage}"]`)
      ?.focus({ preventScroll: true });
  }
  if (target.dataset.average) {
    average = target.dataset.average === "average";
    document
      .querySelectorAll("[data-average]")
      .forEach((el) => el.classList.toggle("active", el === target));
    renderPlayers();
  }
  if (target.dataset.player) choosePlayer(target.dataset.player);
  if (target.dataset.match) showMatch(target.dataset.match);
  if (target.dataset.sort) {
    if (sortKey === target.dataset.sort) sortDirection *= -1;
    else {
      sortKey = target.dataset.sort;
      sortDirection = -1;
    }
    renderPlayers();
  }
  if (target.hasAttribute("data-close-player")) {
    selectedPlayer = null;
    $("playerDetail").hidden = true;
  }
  if (target.dataset.page) {
    matchPage += Number(target.dataset.page);
    renderMatches();
  }
  if (target.dataset.matchPlayer) {
    matchPlayer = target.dataset.matchPlayer;
    renderMatchDetail();
  }
  if (target.hasAttribute("data-match-team")) {
    matchPlayer = null;
    renderMatchDetail();
  }
});
document.addEventListener("keydown", (event) => {
  if (
    ["Enter", " "].includes(event.key) &&
    event.target.matches("svg [data-player], svg [data-match]")
  ) {
    event.preventDefault();
    event.target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  }
});
document.addEventListener("change", (event) => {
  if (event.target.dataset.trendSetting) {
    const scope = event.target.dataset.trendScope,
      key = event.target.dataset.trendSetting;
    trendSettings[scope][key] =
      key === "window" ? Number(event.target.value) : event.target.value;
    renderTrend(scope);
    document
      .querySelector(
        `[data-trend-scope="${scope}"][data-trend-setting="${key}"]`,
      )
      ?.focus({ preventScroll: true });
  }
  if (event.target.id === "compareLeft") {
    compareLeft = event.target.value;
    renderHeadToHead();
  }
  if (event.target.id === "compareRight") {
    compareRight = event.target.value;
    renderHeadToHead();
  }
});
$("comparisonMetric").addEventListener("change", renderComparison);
$("playerSearch").addEventListener("input", renderPlayers);
$("matchSearch").addEventListener("input", () => {
  matchPage = 0;
  renderMatches();
});
$("closeDialog").addEventListener("click", () => $("matchDialog").close());
$("matchDialog").addEventListener("close", () => {
  matchRequest++;
  openMatchId = null;
});
async function load() {
  const version = ++requestVersion;
  try {
    const response = await fetch("/api/dashboard" + query);
    if (!response.ok) throw new Error();
    const next = await response.json();
    if (version !== requestVersion) return;
    data = next;
    trendData = null;
    $("error").hidden = true;
    render();
    renderTrend("team");
    loadTrends(version, query);
  } catch (error) {
    if (version === requestVersion) {
      $("error").textContent =
        "We couldn't load your stats. We'll try again shortly.";
      $("error").hidden = false;
    }
  }
}
$("applyFilters").addEventListener("click", () => {
  const params = new URLSearchParams();
  params.set("kind", $("matchKind").value);
  const start = $("startDate").value,
    end = $("endDate").value;
  if (start && end && start > end) {
    $("error").textContent = "Choose an end date on or after the start date.";
    $("error").hidden = false;
    return;
  }
  if (start)
    params.set(
      "start",
      Math.floor(new Date(start + "T00:00:00").getTime() / 1000),
    );
  if (end) {
    const boundary = new Date(end + "T00:00:00");
    boundary.setDate(boundary.getDate() + 1);
    params.set("end", Math.floor(boundary.getTime() / 1000));
  }
  query = "?" + params.toString();
  matchPage = 0;
  load();
});
$("resetFilters").addEventListener("click", () => {
  $("startDate").value = "";
  $("endDate").value = "";
  $("matchKind").value = "all";
  query = "";
  matchPage = 0;
  load();
});
load();
setInterval(load, 60000);
