/**
 * Shared classifier for bot comment bodies that should NOT keep the merge
 * gates open. Two consumers:
 *
 *   - wait_for_bots.mjs ignores noise events when computing the quiet window,
 *     so a chatty bot looping on quota errors can't hold the cap timeout open.
 *   - scripts/lib/gh-pr-review-threads.mjs treats noise threads as low-signal
 *     in classifyThreads, so an "out of credits" review thread can't fail the
 *     feedback gate just because nobody resolved it.
 *
 * Two categories:
 *
 *   - Quota / rate-limit notices ("we hit the API limit, try later").
 *   - Trivial inconsequential replies (ack-only / emoji-only / generic
 *     "useful?" footers) — these never carry actionable feedback.
 *
 * The bodies that prompted this filter were:
 *   - "Your <bot> trial has expired" / "subscription required" / "out of credits"
 *   - "Sorry, I couldn't review this PR — rate limit"
 *   - "Useful? React with 👍 / 👎" tail-only summary stubs
 *   - Single-emoji or "lgtm" replies
 */

const QUOTA_PATTERNS = [
  /\brate[\s-]?limit(?:ed)?\b/i,
  /\bapi (?:limit|quota)\b/i,
  /\bquota (?:exceeded|reached|exhausted)\b/i,
  /\bout of (?:credits?|tokens?|quota|usage)\b/i,
  /\binsufficient (?:credits?|tokens?|funds|balance|quota)\b/i,
  /\bsubscription (?:required|expired)\b/i,
  /\btrial (?:expired|ended|has expired)\b/i,
  /\b(?:monthly|daily) (?:limit|quota)\b/i,
  /\bfree[\s-]tier (?:limit|quota)\b/i,
  /\bservice (?:temporarily )?unavailable\b/i,
  /\btoo many requests\b/i,
  /\b429\b/,
  /\bplease (?:try|come back) (?:again )?later\b/i,
  /couldn'?t (?:review|process|complete)/i,
  /unable to (?:review|process|complete)/i,
];

const TRIVIAL_PATTERNS = [
  // Ack/no-op replies (the whole body, modulo whitespace and trailing puncts).
  /^[\s]*(?:lgtm|looks good(?:\stome)?|ok|okay|got it|thanks?|thx|noted|nothing to (?:report|add)|no (?:comments?|issues?|concerns?)|all good|approved)[\s.!]*$/i,
  // Emoji-only / reaction-only.
  /^[\s\p{Emoji_Presentation}\p{Extended_Pictographic}‍👍👎❤️✅🚀]+$/u,
];

/**
 * @param {string} bodyRaw
 * @returns {boolean}
 */
export function isQuotaBotMessage(bodyRaw) {
  if (!bodyRaw) return false;
  const body = String(bodyRaw).trim();
  if (!body) return false;
  return QUOTA_PATTERNS.some((re) => re.test(body));
}

/**
 * @param {string} bodyRaw
 * @returns {boolean}
 */
export function isTrivialBotMessage(bodyRaw) {
  if (!bodyRaw) return true;
  const body = String(bodyRaw).trim();
  if (!body) return true;
  if (body.length < 40) return true;
  // "Useful? React with..." is a footer template. Strip it and re-check whether
  // anything substantive remains — bodies whose ONLY content is the footer get
  // dropped, but a real review with a footer tacked on stays.
  const withoutFooter = body.replace(/Useful\?\s*React with[\s\S]*$/i, '').trim();
  if (withoutFooter.length < 40) return true;
  return TRIVIAL_PATTERNS.some((re) => re.test(body));
}

/**
 * True when a bot comment body should not hold the merge gates open —
 * either it's a quota / API-limit notice, or a trivial inconsequential reply.
 *
 * @param {string} bodyRaw
 * @returns {boolean}
 */
export function isBotNoise(bodyRaw) {
  return isQuotaBotMessage(bodyRaw) || isTrivialBotMessage(bodyRaw);
}
