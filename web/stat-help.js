"use strict";
// Definitions follow the counters already decoded by this project. No inferred scores.
const STAT_EXPLANATIONS = {
  goals:
    "Goals scored. Goal types can overlap: one goal can be both first time and weak foot.",
  assists: "Assists credited for setting up a goal.",
  second_assists:
    "The pass before the assist in a scoring move. Kept separate from assists.",
  shots: "Shots attempted.",
  shots_on_target:
    "Shots recorded as on target, including goals and saved attempts.",
  shots_off_target: "Shots recorded as off target.",
  shot_conversion:
    "Goals divided by shots, multiplied by 100. This measures finishing, rather than how often shots are on target.",
  shots_on_target_rate:
    "On-target shots divided by all recorded shots, multiplied by 100.",
  shots_saved: "Your shots that were saved by the opposing goalkeeper.",
  goals_first_time: "Goals scored with a first-time strike.",
  goals_weak_foot: "Goals scored using the player’s weak foot.",
  goals_off_post: "Goals recorded as going in off the post.",
  assists_through_ball: "Assists recorded from a through ball.",
  mom: "Player of the match awards.",
  passesmade:
    "Completed passes. Direction and distance are two ways of describing the same passes, so those breakdowns should not be added together.",
  passattempts: "Passes attempted, whether completed or unsuccessful.",
  pass_completion:
    "Completed passes divided by attempted passes, multiplied by 100. Combined match rates use all attempts, rather than averaging each match’s percentage.",
  passes_failed:
    "Unsuccessful passes. Direction and distance describe the same attempts from different angles; do not add those breakdowns together.",
  crosses_completed: "Crosses recorded as completed.",
  crosses_failed_open_play: "Unsuccessful crosses in open play.",
  cross_accuracy:
    "Completed crosses divided by completed plus unsuccessful open-play crosses, multiplied by 100.",
  first_time_passes: "Passes played with the first touch.",
  switch_of_play_passes:
    "Passes recorded as switches of play across the pitch.",
  flair_passes: "Passes recorded as flair passes.",
  through_balls_completed: "Completed through balls.",
  offside_passes: "Passes recorded as finding a player offside.",
  tacklesmade: "Successful tackles in the match’s tackle summary.",
  tackleattempts:
    "Tackle attempts in the match summary, including attempts that were not successful.",
  tackle_success:
    "Successful tackles divided by tackle attempts, multiplied by 100. This uses the tackle summary, not the separately recorded Tackles lost counter.",
  tackles_lost:
    "Tackles recorded as lost. This is a separate counter from tackle attempts minus successful tackles.",
  clean_tackles: "Tackles recorded as clean.",
  dangerous_tackles: "Tackles recorded as dangerous.",
  interceptions:
    "Interceptions recorded when a player cuts out an opponent’s ball.",
  opponent_dispossessed: "Actions recorded as dispossessing an opponent.",
  crosses_blocked: "Opponent crosses recorded as blocked.",
  cleansheetsdef: "Clean sheets credited while playing as a defender.",
  cleansheetsany: "Clean sheets credited while playing as ANY.",
  dribbles_completed:
    "Dribbles recorded as completed. This is distinct from the Dribble carries counter.",
  dribbles_carried: "Actions recorded as carrying the ball while dribbling.",
  dribble_skill_move_beat:
    "Times a skill move was recorded as beating a player.",
  dribble_beat_without_skill_move:
    "Players beaten without a skill move. Calculated from all recorded players beaten minus skill-move beats.",
  possession_won:
    "Possession wins across the defensive, middle and attacking thirds.",
  possession_lost:
    "Possession losses across the defensive, middle and attacking thirds. This is broader than failed passes alone.",
  aerial_duels_won:
    "Recorded aerial wins in attacking and defending situations combined.",
  aerial_duels_won_attacking: "Aerial wins recorded in attacking situations.",
  aerial_duels_won_defending: "Aerial wins recorded in defending situations.",
  saves:
    "Goalkeeper saves. Save types can overlap and should not be summed to recreate this total.",
  goalsconceded:
    "Goals conceded. The team total counts the club’s score against once, rather than summing copies from player rows.",
  cleansheetsgk: "Clean sheets credited while playing as goalkeeper.",
  ballDiveSaves: "Goalkeeper saves recorded as diving saves.",
  crossSaves: "Goalkeeper saves recorded from crosses.",
  goodDirectionSaves: "Goalkeeper saves marked as good direction.",
  parrySaves: "Goalkeeper saves recorded as parries.",
  punchSaves: "Goalkeeper actions recorded as punches.",
  reflexSaves: "Goalkeeper saves recorded as reflex saves.",
  yellow_cards: "Yellow cards recorded during matches.",
  redcards: "Red cards credited in the match summary.",
  fouls_conceded:
    "Fouls committed, including those recorded in the defensive third.",
  fouls_conceded_defensive_third:
    "Fouls committed in the defensive third of the pitch.",
  fouls_won: "Fouls won from opponents.",
  penalties_conceded: "Penalties conceded.",
  corners_conceded: "Corners conceded to opponents.",
  corners_attempted: "Corners taken.",
  out_of_position:
    "Out-of-position feedback recorded by the game. The numbered levels are separate feedback counters, not a breakdown to sum into this total.",
  good_position_feedback: "Positive positioning feedback recorded by the game.",
  feedback_use_ball: "Game feedback labelled Use the ball.",
  feedback_pick_pass: "Game feedback labelled Pick your pass.",
  feedback_no_good_option:
    "Game feedback labelled No good option. It is not counted as a failed pass or an individual mistake.",
  feedback_good_option: "Game feedback labelled Good option.",
  feedback_best_option: "Game feedback labelled Best option.",
  feedback_pass_elsewhere: "Game feedback labelled Pass elsewhere.",
  feedback_chose_pass: "Game feedback labelled Chose to pass.",
  rating:
    "Match rating on a 0–10 scale. Detailed averages include rated player appearances.",
  win_rate:
    "Wins divided by matches played, multiplied by 100. Draws are included in matches played.",
  contributions: "Goals and assists combined. Second assists are separate.",
  contributions_per_game: "Goals plus assists divided by matches played.",
  wins: "Matches won.",
  draws: "Matches drawn.",
  losses: "Matches lost.",
  not_won:
    "Tackle attempts minus successful tackles. This is not the separate Tackles lost counter.",
  division:
    "Current division from the club leaderboard. The graph shows saved observations, with Elite above Divisions 1–5.",
  goal_difference: "Goals scored minus goals conceded.",
  matches: "Matches played, including wins, draws and losses.",
  skill_rating:
    "The club’s skill rating reported by the game. The graph follows its saved values over time.",
};
for (const direction of ["forward", "sideways", "backward"])
  for (const outcome of ["completed", "failed"])
    STAT_EXPLANATIONS[`passes_${direction}_${outcome}`] =
      `${outcome === "completed" ? "Completed" : "Unsuccessful"} passes tagged as ${direction}. Direction and distance can describe the same pass.`;
for (const distance of ["short", "medium", "long"])
  for (const outcome of ["completed", "failed"])
    STAT_EXPLANATIONS[`passes_${distance}_${outcome}`] =
      `${outcome === "completed" ? "Completed" : "Unsuccessful"} passes tagged as ${distance} distance. This category does not include the separate cross counter.`;
for (const outcome of ["on", "off"])
  for (const area of ["inside", "outside"])
    STAT_EXPLANATIONS[`shots_${outcome}_target_${area}_box`] =
      `Shots ${outcome === "on" ? "on" : "off"} target taken ${area} the penalty area.`;
for (const action of ["won", "lost"])
  for (const [zone, name] of [
    ["defensive", "defensive"],
    ["middle", "middle"],
    ["attacking", "attacking"],
  ])
    STAT_EXPLANATIONS[`possession_${action}_${zone}_third`] =
      `Possession ${action === "won" ? "wins" : "losses"} recorded in the ${name} third of the pitch.`;
for (const type of ["standing", "sliding"])
  STAT_EXPLANATIONS[`${type}_tackles_won`] =
    `Successful ${type} tackles recorded by the game.`;
for (let level = 1; level <= 5; level++)
  STAT_EXPLANATIONS[`out_of_position_severity_${level}`] =
    `Out-of-position feedback tagged as level ${level}. These levels are game feedback, not a count of goals or chances conceded.`;
STAT_EXPLANATIONS.winRate = STAT_EXPLANATIONS.win_rate;
const STAT_HELP_ALIASES = {
  Goals: "goals",
  Assists: "assists",
  Shots: "shots",
  "On target": "shots_on_target_rate",
  "Off target": "shots_off_target",
  Conversion: "shot_conversion",
  Accuracy: "pass_completion",
  "Pass accuracy": "pass_completion",
  "Shot success": "shot_conversion",
  Completed: "passesmade",
  Attempted: "passattempts",
  "Cross accuracy": "cross_accuracy",
  "Through balls": "through_balls_completed",
  "Switches of play": "switch_of_play_passes",
  "First-time passes": "first_time_passes",
  Conceded: "goalsconceded",
  "Tackle success": "tackle_success",
  Tackles: "tackleattempts",
  "Tackles won": "tacklesmade",
  "Not won": "not_won",
  "Standing tackles won": "standing_tackles_won",
  "Sliding tackles won": "sliding_tackles_won",
  "Defending aerial wins": "aerial_duels_won_defending",
  Dispossessions: "opponent_dispossessed",
  Fouls: "fouls_conceded",
  "Red cards": "redcards",
  "Defender clean sheets": "cleansheetsdef",
  "Goalkeeper clean sheets": "cleansheetsgk",
  Dribbles: "dribbles_completed",
  "Dribble carries": "dribbles_carried",
  "Skill moves": "dribble_skill_move_beat",
  "Players beaten": "dribble_beat_without_skill_move",
  "Goals + assists / match": "contributions_per_game",
  "Win rate": "win_rate",
  Wins: "wins",
  Draws: "draws",
  Losses: "losses",
  "Skill rating": "skill_rating",
  Division: "division",
  Games: "matches",
  Matches: "matches",
  MOTM: "mom",
  Scored: "goals",
  "Goal difference": "goal_difference",
  Forward: "passing_forward",
  Sideways: "passing_sideways",
  Backward: "passing_backward",
  Short: "passing_short",
  Medium: "passing_medium",
  Long: "passing_long",
  Defence: "possession_defence",
  Midfield: "possession_midfield",
  Attack: "possession_attack",
};
for (const direction of ["forward", "sideways", "backward"])
  STAT_EXPLANATIONS[`passing_${direction}`] =
    `Passes tagged as ${direction}. The chart separates completed and unsuccessful passes.`;
for (const distance of ["short", "medium", "long"])
  STAT_EXPLANATIONS[`passing_${distance}`] =
    `Passes tagged as ${distance} distance. The chart separates completed and unsuccessful passes; crosses are counted separately.`;
for (const [zone, name] of [
  ["defence", "defensive"],
  ["midfield", "middle"],
  ["attack", "attacking"],
])
  STAT_EXPLANATIONS[`possession_${zone}`] =
    `Possession wins and losses in the ${name} third of the pitch.`;
function statHelpKey(label) {
  if (STAT_HELP_ALIASES[label]) return STAT_HELP_ALIASES[label];
  if (typeof GROUPS !== "undefined")
    return Object.values(GROUPS)
      .flat()
      .find((field) => field.label === label)?.key;
  return null;
}
function statHelpLabel(
  label,
  key = statHelpKey(label),
  className = "stat-name",
  perMatch = false,
) {
  return STAT_EXPLANATIONS[key]
    ? `<button type="button" class="stat-help ${className}" data-stat-help="${esc(key)}" ${perMatch ? 'data-help-average="true"' : ""} aria-label="Explain ${esc(label)}">${esc(label)}</button>`
    : `<span class="${className}">${esc(label)}</span>`;
}
let explanationAnchor = null,
  explanationPinned = false,
  explanationTimer = null;
const explanation = document.createElement("div");
explanation.id = "statExplanation";
explanation.className = "stat-explanation";
explanation.setAttribute("popover", "manual");
explanation.setAttribute("role", "tooltip");
function closeExplanation() {
  clearTimeout(explanationTimer);
  explanationAnchor?.removeAttribute("aria-describedby");
  if (explanation.matches(":popover-open")) explanation.hidePopover();
  explanationAnchor = null;
  explanationPinned = false;
}
function openExplanation(anchor, pinned = false) {
  clearTimeout(explanationTimer);
  if (explanationAnchor !== anchor) closeExplanation();
  explanationAnchor = anchor;
  explanationPinned = pinned;
  const key = anchor.dataset.statHelp;
  const fullLabel =
    typeof GROUPS !== "undefined"
      ? Object.values(GROUPS)
          .flat()
          .find((f) => f.key === key)?.label
      : null;
  explanation.innerHTML = `<strong>${esc(fullLabel || anchor.textContent)}</strong><p>${esc(STAT_EXPLANATIONS[key])}${anchor.dataset.helpAverage ? " Per match divides this count by the matches included for this team or player." : ""}</p>`;
  const host = anchor.closest("dialog") || document.body;
  if (explanation.parentElement !== host) host.append(explanation);
  anchor.setAttribute("aria-describedby", explanation.id);
  if (!explanation.matches(":popover-open")) explanation.showPopover();
  positionExplanation();
}
function positionExplanation() {
  const rect = explanationAnchor.getBoundingClientRect(),
    width = Math.min(320, innerWidth - 24);
  explanation.style.width = width + "px";
  explanation.style.left =
    Math.max(12, Math.min(rect.left, innerWidth - width - 12)) + "px";
  const height = explanation.getBoundingClientRect().height;
  explanation.style.top =
    Math.max(
      12,
      rect.bottom + 8 + height <= innerHeight - 12
        ? rect.bottom + 8
        : rect.top - height - 8,
    ) + "px";
}
document.addEventListener("pointerover", (event) => {
  if (event.pointerType === "touch" || explanationPinned) return;
  const anchor = event.target.closest("[data-stat-help]");
  if (anchor) openExplanation(anchor);
});
document.addEventListener("pointerout", (event) => {
  if (explanationPinned || !event.target.closest("[data-stat-help]")) return;
  explanationTimer = setTimeout(() => {
    if (!explanation.matches(":hover")) closeExplanation();
  }, 180);
});
explanation.addEventListener("pointerenter", () =>
  clearTimeout(explanationTimer),
);
explanation.addEventListener("pointerleave", () => {
  if (!explanationPinned) closeExplanation();
});
document.addEventListener("focusin", (event) => {
  const anchor = event.target.closest("[data-stat-help]");
  if (anchor) openExplanation(anchor);
});
document.addEventListener("focusout", (event) => {
  if (!explanationPinned && event.target.closest("[data-stat-help]"))
    closeExplanation();
});
document.addEventListener(
  "click",
  (event) => {
    const anchor = event.target.closest("[data-stat-help]");
    if (!anchor) return;
    event.stopPropagation();
    if (explanationAnchor === anchor && explanationPinned) closeExplanation();
    else openExplanation(anchor, true);
  },
  true,
);
document.addEventListener("pointerdown", (event) => {
  if (
    explanationAnchor &&
    !event.target.closest("[data-stat-help]") &&
    !explanation.contains(event.target)
  )
    closeExplanation();
});
document.addEventListener(
  "keydown",
  (event) => {
    if (event.key === "Escape" && explanationAnchor) {
      event.preventDefault();
      event.stopPropagation();
      closeExplanation();
    }
    if (
      ["Enter", " "].includes(event.key) &&
      event.target.matches("svg [data-stat-help]")
    ) {
      event.preventDefault();
      event.target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    }
  },
  true,
);
window.addEventListener(
  "scroll",
  () => {
    if (!explanationAnchor) return;
    const rect = explanationAnchor.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > innerHeight) closeExplanation();
    else positionExplanation();
  },
  true,
);
window.addEventListener("resize", closeExplanation);
new MutationObserver(() => {
  if (explanationAnchor && !explanationAnchor.isConnected) closeExplanation();
}).observe(document.documentElement, { childList: true, subtree: true });
