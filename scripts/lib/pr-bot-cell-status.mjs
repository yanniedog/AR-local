/**
 * Per-bot cell status for the PR bot spreadsheet matrix.
 *
 * Colors:
 *   green  — substantive feedback (or review/reaction) and addressed before merge
 *   yellow — feedback given but not addressed before merge
 *   grey   — no bot activity (no text, review, or thumbs)
 *   red    — bot limit/quota hit; no substantive feedback before merge
 */
import { isQuotaBotMessage } from './bot-noise.mjs';
import { classifyThreads } from './gh-pr-review-threads.mjs';
import { loginMatchesBotKey, SPREADSHEET_BOT_KEYS } from './pr-bot-roster.mjs';

export const CELL_STATUS = {
  GREEN: 'green',
  YELLOW: 'yellow',
  GREY: 'grey',
  RED: 'red',
};

export const CELL_LABELS = {
  [CELL_STATUS.GREEN]: 'OK',
  [CELL_STATUS.YELLOW]: 'Open',
  [CELL_STATUS.GREY]: '—',
  [CELL_STATUS.RED]: 'Limit',
};

/** Google Sheets background RGB (0–1). */
export const CELL_COLORS = {
  [CELL_STATUS.GREEN]: { red: 0.82, green: 0.94, blue: 0.82 },
  [CELL_STATUS.YELLOW]: { red: 1, green: 0.95, blue: 0.8 },
  [CELL_STATUS.GREY]: { red: 0.92, green: 0.92, blue: 0.92 },
  [CELL_STATUS.RED]: { red: 0.96, green: 0.8, blue: 0.8 },
};

/**
 * @param {import('./pr-bot-spreadsheet-fetch.mjs').BotEvent[]} events
 * @param {string} botKey
 */
function eventsForBot(events, botKey) {
  return (events || []).filter((e) => e.botKey === botKey || loginMatchesBotKey(e.login, botKey));
}

/**
 * Review submission or PR reaction counts as feedback even when the body is empty/trivial.
 *
 * @param {import('./pr-bot-spreadsheet-fetch.mjs').BotEvent[]} botEvents
 */
function hasNonNoiseFeedback(botEvents) {
  if (!botEvents.length) return false;
  if (botEvents.some((e) => e.kind === 'review' || e.kind === 'reaction')) return true;
  return botEvents.some((e) => !e.noise);
}

/**
 * @param {import('./pr-bot-spreadsheet-fetch.mjs').BotEvent[]} botEvents
 */
function onlyQuotaLimitActivity(botEvents) {
  if (!botEvents.length) return false;
  const textEvents = botEvents.filter((e) => e.kind !== 'reaction');
  if (!textEvents.length) return false;
  return textEvents.every((e) => isQuotaBotMessage(e.body));
}

/**
 * @param {object[]} threads
 * @param {string} botKey
 */
function violationsForBot(threads, botKey) {
  const violations = classifyThreads(threads, { mergedAudit: true });
  return violations.filter((v) => loginMatchesBotKey(v.starter, botKey));
}

/**
 * @param {string} botKey
 * @param {{ events: import('./pr-bot-spreadsheet-fetch.mjs').BotEvent[], threads: object[] }} payload
 * @returns {{ status: string, label: string, reason: string }}
 */
export function classifyBotCell(botKey, { events, threads }) {
  const botEvents = eventsForBot(events, botKey);

  if (!botEvents.length) {
    return {
      status: CELL_STATUS.GREY,
      label: CELL_LABELS[CELL_STATUS.GREY],
      reason: 'no bot activity',
    };
  }

  if (!hasNonNoiseFeedback(botEvents)) {
    if (onlyQuotaLimitActivity(botEvents)) {
      return {
        status: CELL_STATUS.RED,
        label: CELL_LABELS[CELL_STATUS.RED],
        reason: 'quota/limit notice only',
      };
    }
    return {
      status: CELL_STATUS.GREY,
      label: CELL_LABELS[CELL_STATUS.GREY],
      reason: 'only trivial/noise activity',
    };
  }

  const open = violationsForBot(threads, botKey);
  if (open.length > 0) {
    return {
      status: CELL_STATUS.YELLOW,
      label: CELL_LABELS[CELL_STATUS.YELLOW],
      reason: `${open.length} unaddressed thread(s) at merge`,
    };
  }

  return {
    status: CELL_STATUS.GREEN,
    label: CELL_LABELS[CELL_STATUS.GREEN],
    reason: 'feedback addressed or no actionable threads',
  };
}

/**
 * @param {{ events: import('./pr-bot-spreadsheet-fetch.mjs').BotEvent[], threads: object[] }} payload
 * @returns {Record<string, { status: string, label: string, reason: string }>}
 */
export function classifyAllBotCells(payload) {
  /** @type {Record<string, { status: string, label: string, reason: string }>} */
  const out = {};
  for (const key of SPREADSHEET_BOT_KEYS) {
    out[key] = classifyBotCell(key, payload);
  }
  return out;
}
