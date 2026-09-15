import type { DetailItem, ProductDetail } from '../types';

/**
 * Public-availability assessment for a product. CDR lenders chronically
 * under-report eligibility: a "Staff Home Loan" with a market-leading rate often
 * carries only MIN_AGE/RESIDENCY in its structured eligibility, leaving the real
 * restriction in the product name/description. We therefore combine the structured
 * eligibilityType codes with name/description/free-text signals, and explicitly
 * flag the gap ("verify") when the name implies a restriction the data does not
 * encode — so a restricted product is never silently presented as open to all.
 *
 * Product-structure dimensions (LVR, deposit size, TD term, OO vs investor,
 * fixed vs variable, etc.) are NOT access restrictions — they describe the
 * product, not who may apply.
 */
export type AccessCategory =
  | 'staff'
  | 'occupation'
  | 'membership'
  | 'business'
  | 'student'
  | 'first-home'
  | 'youth'
  | 'pension'
  | 'geographic'
  | 'package';

export interface AccessAssessment {
  /** Any access-limiting signal (structured or textual) is present. */
  restricted: boolean;
  categories: AccessCategory[];
  /** Name/description implies a restriction the structured eligibility data does NOT encode. */
  verify: boolean;
  /** Short chip text, e.g. "Staff only" / "Members only" / "Check eligibility". */
  badge: string | null;
  /** One-line plain-English summary for the product page. */
  summary: string;
}

const CATEGORY_LABEL: Record<AccessCategory, string> = {
  staff: 'Staff only',
  occupation: 'Occupation-restricted',
  membership: 'Members only',
  business: 'Business / SMSF',
  student: 'Students',
  'first-home': 'First-home buyers',
  youth: 'Youth only',
  pension: 'Pensioners',
  geographic: 'Region-restricted',
  package: 'Package / existing customers',
};

// Structured CDR eligibilityType codes that genuinely limit who can apply.
// (MIN_AGE/RESIDENCY_STATUS/NATURAL_PERSON are near-universal and not restrictions.)
// EMPLOYMENT_STATUS is intentionally omitted: CDR lenders use it for ordinary
// "must be employed / self-employed" credit checks (Westpac, UBank, …), not for
// occupation-gated products. Occupation still comes from name/provider/text.
const RESTRICTING_TYPES: Record<string, AccessCategory> = {
  STAFF: 'staff',
  BUSINESS: 'business',
  STUDENT: 'student',
  PENSION_RECIPIENT: 'pension',
  // MAX_AGE is handled separately: only low caps (youth products) count, not
  // ordinary mortgage maximum-borrower-age values like 70–75.
};

const OCCUPATION_RE =
  /\b(police|nurs(?:e|es|ing)|midwi(?:fe|ves)|teacher|educator(?:s)?|doctor|dentist|dental|veterinar(?:y|ian|ians)|health\s*(?:care|sector|worker|professional)s?|medical|defence|defense|military|navy|army|veteran|firefighter|fire\s*service|ambulance|paramedic|emergency\s*services|first\s*responder|essential\s*workers?)\b/i;
const STAFF_RE = /\b(staff|employees?|employers?|colleagues?)\b/i;
const MEMBERSHIP_RE = /\bmembers?\s+of\b|\bassociation\b|\bunion\b|\balumni\b|\bdiocese\b|\bparish\b/i;
const BUSINESS_RE = /\b(business|commercial|corporate|company|smsf|self[-\s]?managed\s+super|trust)\b/i;
const STUDENT_RE = /\bstudent[s]?\b/i;
const FIRST_HOME_RE = /\bfirst[-\s]?home\s+(?:buyers?|owners?)\b/i;
const FIRST_HOME_NEGATED_NAME_RE =
  /\bnot\s+(?:available\s+)?(?:to|for)\s+first[-\s]?home\s+(?:buyers?|owners?)\b/i;
const FIRST_HOME_MARKETING_NAME_RE =
  /\b(?:ideal|perfect|great|designed)\s+for\s+first[-\s]?home\s+(?:buyers?|owners?)\b/i;
const FIRST_HOME_RESTRICTIVE_RE =
  /\b(?:only\s+available|available\s+only|exclusively\s+available|restricted|limited)\s+(?:to|for)\s+(?:eligible\s+)?first[-\s]?home\s+(?:buyers?|owners?)\b|\bmust\s+be\s+(?:an?\s+)?first[-\s]?home\s+(?:buyer|owner)\b|\bfirst[-\s]?home\s+(?:buyers?|owners?)\s+only\b/i;
// Name/description youth products. Deliberately omit bare "under 18/19" — that
// phrasing usually means guardian rules on otherwise adult-open accounts.
const YOUTH_RE =
  /\b(youth|junior|juniors|kids?|children|child|teen(?:ager)?s?|minors?|under\s*2[0-5])\b/i;
// Eligibility/constraint copy must gate to pensioners, not merely name a linked
// "Pensioner Advantage" account option.
const PENSION_RE =
  /\b(?:pensioners?|pension\s+recipients?|centrelink\s+pension)\s+only\b|\b(?:available\s+(?:only\s+)?to|for)\s+(?:pensioners?|pension\s+recipients?)\b|\bpensioner\s+(?:saver|account|product)\b/i;
const PENSION_NAME_RE = /\b(pensioners?|pension\s+recipients?)\b/i;
// Region / residency gates beyond the near-universal "Australian resident" check.
// Match state-qualified "residents of NSW/Queensland/..." but not Australia-wide residency.
const GEO_RE =
  /\bonly\s+available\s+in\b|\bavailable\s+(?:only\s+)?(?:to|in)\s+(?:customers?\s+in\s+)?(?:NSW|QLD|VIC|WA|SA|TAS|NT|Queensland|Victoria|Tasmania|New\s+South\s+Wales|Western\s+Australia|South\s+Australia|Northern\s+Territory|Australian\s+Capital\s+Territory)\b|\bresidents?\s+of\s+(?!Australia\b)(?:NSW|QLD|VIC|WA|SA|TAS|NT|ACT|Queensland|Victoria|Tasmania|New\s+South\s+Wales|Western\s+Australia|South\s+Australia|Northern\s+Territory|Australian\s+Capital\s+Territory)\b|\b(?:NSW|QLD|VIC|WA|SA|TAS|ACT|NT)\s+residents?\b|\b(?:Queensland|Victoria|Tasmania|New\s+South\s+Wales|Western\s+Australia|South\s+Australia)\s+residents?\b|\bpostcode[s]?\s+(?:only|restricted|limited)\b|\bgeographic(?:ally)?\s+restricted\b|\blocal\s+(?:residents?|customers?)\s+only\b/i;
// ACT is matched case-sensitively so "available to act" (verb) is not a region gate.
const GEO_ACT_CANDIDATE_RE =
  /\bavailable\s+(?:only\s+)?(?:to|in)\s+(?:customers?\s+in\s+)?(ACT|act)\b/i;
// Package / existing-customer gates that limit who can open (not LVR/deposit/term
// structure, and not ordinary "linked transaction account" bonus-rate rules).
const PACKAGE_RE =
  /\b(?:existing|current)\s+customers?\s+only\b|\bmust\s+already\s+(?:be\s+an?\s+existing\s+customer|hold\s+an?\s+(?:everyday|transaction|offset|package)\s+account)\b|\brequires?\s+(?:an?\s+)?(?:existing|package)\s+account\b|\bpackage\s+(?:customers?|members?)\s+only\b|\bonly\s+available\s+(?:as\s+part\s+of|with)\s+a?\s*package\b|\b(?:only|exclusively)\s+bundled\s+with\b|\bhome\s+loan\s+package\s+customers?\s+only\b/i;

/** True when MAX_AGE encodes a youth/child upper bound (≤25), not a senior lending cap. */
function maxAgeImpliesYouth(detail: ProductDetail | null | undefined): boolean {
  for (const it of detail?.eligibility ?? []) {
    if ((it.label ?? '').trim().toUpperCase() !== 'MAX_AGE') continue;
    const raw = it.value;
    const n = typeof raw === 'number' ? raw : Number(String(raw ?? '').replace(/[^\d.]/g, ''));
    if (Number.isFinite(n) && n > 0 && n <= 25) return true;
    const info = `${it.name ?? ''} ${it.info ?? ''} ${raw ?? ''}`;
    const m = info.match(/\b(?:max(?:imum)?(?:\s+age)?|under|up\s+to|aged?\s+up\s+to)\s*:?\s*(\d{1,2})\b/i);
    if (m) {
      const age = Number(m[1]);
      if (Number.isFinite(age) && age <= 25) return true;
    }
  }
  return false;
}

function geoRestricts(text: string): boolean {
  if (GEO_RE.test(text)) return true;
  const m = text.match(GEO_ACT_CANDIDATE_RE);
  return !!m && m[1] === 'ACT';
}

function firstHomeNameRestricts(text: string): boolean {
  return FIRST_HOME_RE.test(text) &&
    !FIRST_HOME_NEGATED_NAME_RE.test(text) &&
    !FIRST_HOME_MARKETING_NAME_RE.test(text);
}

function textOf(name: string, detail: ProductDetail | null | undefined): string {
  const parts: string[] = [name || '', detail?.description || ''];
  const push = (items?: DetailItem[]) => {
    for (const it of items ?? []) {
      if (it.name) parts.push(String(it.name));
      if (it.info) parts.push(String(it.info));
      if (it.value) parts.push(String(it.value));
    }
  };
  push(detail?.eligibility);
  push(detail?.constraints);
  return parts.join(' • ');
}

function eligibilityCodes(detail: ProductDetail | null | undefined): Set<string> {
  const out = new Set<string>();
  for (const it of detail?.eligibility ?? []) {
    const code = (it.label ?? '').trim().toUpperCase();
    if (code) out.add(code);
  }
  return out;
}

/**
 * Classify a product's public availability from its name + details.
 * `name` is the product name (from the rate row); `detail` is the cached
 * ProductDetail (may be null while details load — then only the name/provider
 * are used). Pass `provider` so occupation lenders with generic product titles
 * (e.g. Australian Military Bank "RateSaver Home Loan") are still classified.
 */
export function assessAccess(
  name: string,
  detail: ProductDetail | null | undefined,
  provider?: string | null,
): AccessAssessment {
  const codes = eligibilityCodes(detail);
  const text = textOf(name, detail);
  const nameText = name || '';
  const providerText = provider || '';

  const cats = new Set<AccessCategory>();
  // Structured codes are authoritative (MAX_AGE handled via maxAgeImpliesYouth).
  for (const [code, cat] of Object.entries(RESTRICTING_TYPES)) {
    if (codes.has(code)) cats.add(cat);
  }
  // Textual signals from product name + detail copy.
  if (STAFF_RE.test(text)) cats.add('staff');
  if (OCCUPATION_RE.test(text)) cats.add('occupation');
  // Membership: name + eligibility/constraints only — descriptions often repeat lender brands.
  {
    const membershipParts: string[] = [nameText];
    for (const it of detail?.eligibility ?? []) {
      if (it.name) membershipParts.push(String(it.name));
      if (it.info) membershipParts.push(String(it.info));
      if (it.value) membershipParts.push(String(it.value));
    }
    for (const it of detail?.constraints ?? []) {
      if (it.name) membershipParts.push(String(it.name));
      if (it.info) membershipParts.push(String(it.info));
      if (it.value) membershipParts.push(String(it.value));
    }
    if (MEMBERSHIP_RE.test(membershipParts.join(" "))) cats.add("membership");
  }
  if (STUDENT_RE.test(text)) cats.add('student');
  // Product names are allowed to classify an explicitly first-home product.
  // Detail copy must actually gate access: lenders also mention first-home
  // buyers as a target audience or as one optional high-LVR pathway.
  if (
    firstHomeNameRestricts(nameText) ||
    FIRST_HOME_RESTRICTIVE_RE.test(textOf('', detail))
  ) cats.add('first-home');
  // Youth: product name/description or a low MAX_AGE cap — not guardian copy in
  // eligibility ("customers under 18 need a parent").
  const youthSurface = `${nameText} ${detail?.description || ''}`;
  if (YOUTH_RE.test(youthSurface) || maxAgeImpliesYouth(detail)) cats.add('youth');
  if (PENSION_NAME_RE.test(nameText) || PENSION_RE.test(text)) cats.add('pension');
  if (geoRestricts(text)) cats.add('geographic');
  if (PACKAGE_RE.test(text)) cats.add('package');
  // Provider brand: occupation/staff only. Do not run membership `\bunion\b`
  // against provider names or every "* Credit Union" becomes members-only.
  if (STAFF_RE.test(providerText)) cats.add('staff');
  if (OCCUPATION_RE.test(providerText)) cats.add('occupation');
  // Business: ONLY from the structured BUSINESS code (handled above) or the
  // product NAME. Free-text "company/trust/commercial" mentions in eligibility
  // are almost always EXCLUSIONS ("not available to companies or trusts") and
  // would wrongly flag popular retail products (Unloan, Virgin Money Lite).
  // Do not match provider names here (many "X Business Bank" style brands).
  if (BUSINESS_RE.test(nameText)) cats.add('business');

  // "Verify": product NAME implies a who-can-open gate but no structured
  // eligibility code corroborates it (Coastline/People-First failure mode).
  // Provider-brand signals do not set verify — those are intentional occupation
  // lenders, not under-reported CDR gaps. Detail text that already classified a
  // category also does not need the "?" badge.
  const nameOnlyImpliesRestriction =
    STAFF_RE.test(nameText) ||
    OCCUPATION_RE.test(nameText) ||
    MEMBERSHIP_RE.test(nameText) ||
    YOUTH_RE.test(nameText) ||
    STUDENT_RE.test(nameText) ||
    firstHomeNameRestricts(nameText) ||
    geoRestricts(nameText) ||
    PACKAGE_RE.test(nameText) ||
    PENSION_NAME_RE.test(nameText);
  const structurallyConfirmed =
    codes.has('STAFF') ||
    codes.has('BUSINESS') ||
    codes.has('STUDENT') ||
    codes.has('PENSION_RECIPIENT') ||
    maxAgeImpliesYouth(detail);
  const verify = nameOnlyImpliesRestriction && !structurallyConfirmed;

  const categories = Array.from(cats);
  const restricted = categories.length > 0;

  let badge: string | null = null;
  if (categories.length) badge = CATEGORY_LABEL[categories[0]];
  else if (verify) badge = 'Check eligibility';

  let summary: string;
  if (restricted) {
    const human = categories.map((c) => CATEGORY_LABEL[c].toLowerCase()).join(', ');
    summary = `Not open to everyone — eligibility applies (${human}).`;
    if (verify) {
      summary += ' The lender hasn’t encoded this in their eligibility data, so confirm the exact criteria directly.';
    }
  } else if (verify) {
    summary =
      'The product name suggests restricted eligibility, but the lender’s eligibility data doesn’t confirm it. Verify directly before relying on this rate.';
  } else {
    summary = 'Appears open to the general public based on the lender’s eligibility data.';
  }

  return { restricted, categories, verify, badge, summary };
}

/**
 * True when the product should be hidden under standard-only / broadly-applicable
 * mode. Same predicate the orange access badge uses — never show a restricted
 * badge for a product that this gate would still allow.
 */
export function accessExcludesFromStandard(assessment: AccessAssessment): boolean {
  return assessment.restricted || !!assessment.badge;
}

/**
 * Row-level access restriction derived from the product NAME alone (no details
 * and no provider). Use {@link rowRestrictsAccess} when the lender brand should
 * also gate listings (occupation lenders with generic product titles).
 */
export function nameRestrictsAccess(name: string | null | undefined): boolean {
  const text = name ?? '';
  if (!text) return false;
  return (
    STAFF_RE.test(text) ||
    OCCUPATION_RE.test(text) ||
    MEMBERSHIP_RE.test(text) ||
    STUDENT_RE.test(text) ||
    firstHomeNameRestricts(text) ||
    YOUTH_RE.test(text) ||
    PENSION_NAME_RE.test(text) ||
    geoRestricts(text) ||
    PACKAGE_RE.test(text) ||
    BUSINESS_RE.test(text)
  );
}

/** True when the lender brand itself implies an occupation/staff gate. */
export function providerRestrictsAccess(provider: string | null | undefined): boolean {
  const text = provider ?? '';
  if (!text) return false;
  // Occupation/staff only — do NOT apply membership `\bunion\b` here, or every
  // "* Credit Union" lender would be treated as members-only.
  return STAFF_RE.test(text) || OCCUPATION_RE.test(text);
}

/**
 * Cheap row gate used by list/search/ranking before details are loaded.
 * Combines product name and provider checks. Provider is included because
 * occupation lenders often publish generic titles ("RateSaver Home Loan") under
 * an occupation-gated brand ("Australian Military Bank", "Police Bank").
 */
export function rowRestrictsAccess(
  row: { product_name?: string | null; provider?: string | null } | null | undefined,
): boolean {
  if (!row) return false;
  return nameRestrictsAccess(row.product_name) || providerRestrictsAccess(row.provider);
}

/** Which name-signal categories fire for a product name (may be empty). */
export function nameRestrictionCategories(name: string | null | undefined): AccessCategory[] {
  const text = name ?? '';
  if (!text) return [];
  const cats: AccessCategory[] = [];
  if (STAFF_RE.test(text)) cats.push('staff');
  if (OCCUPATION_RE.test(text)) cats.push('occupation');
  if (MEMBERSHIP_RE.test(text)) cats.push('membership');
  if (BUSINESS_RE.test(text)) cats.push('business');
  if (STUDENT_RE.test(text)) cats.push('student');
  if (firstHomeNameRestricts(text)) cats.push('first-home');
  if (YOUTH_RE.test(text)) cats.push('youth');
  if (PENSION_NAME_RE.test(text)) cats.push('pension');
  if (geoRestricts(text)) cats.push('geographic');
  if (PACKAGE_RE.test(text)) cats.push('package');
  return cats;
}

export type SuitabilityExclusionCounts = {
  total: number;
  nonStandard: number;
  byAccess: Partial<Record<AccessCategory, number>>;
};

/**
 * Count rows the default suitability filter would hide, split by non-standard
 * account class vs name-access category. Used for diagnostics / false-positive
 * watch (Phase 1.1) — not for filtering itself.
 */
export function countSuitabilityExclusions(
  rows: Iterable<{ account_class?: string | null; product_name?: string | null }>,
): SuitabilityExclusionCounts {
  const byAccess: Partial<Record<AccessCategory, number>> = {};
  let total = 0;
  let nonStandard = 0;
  for (const row of rows) {
    const ns = row.account_class === 'non_standard';
    const cats = nameRestrictionCategories(row.product_name);
    if (!ns && !cats.length) continue;
    total += 1;
    if (ns) nonStandard += 1;
    for (const cat of cats) {
      byAccess[cat] = (byAccess[cat] ?? 0) + 1;
    }
  }
  return { total, nonStandard, byAccess };
}
