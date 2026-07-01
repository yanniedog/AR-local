import type { DetailItem, ProductDetail } from '../types';

/**
 * Public-availability assessment for a product. CDR lenders chronically
 * under-report eligibility: a "Staff Home Loan" with a market-leading rate often
 * carries only MIN_AGE/RESIDENCY in its structured eligibility, leaving the real
 * restriction in the product name/description. We therefore combine the structured
 * eligibilityType codes with name/description/free-text signals, and explicitly
 * flag the gap ("verify") when the name implies a restriction the data does not
 * encode — so a restricted product is never silently presented as open to all.
 */
export type AccessCategory =
  | 'staff'
  | 'occupation'
  | 'membership'
  | 'business'
  | 'student'
  | 'pension'
  | 'geographic';

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
  pension: 'Pensioners',
  geographic: 'Region-restricted',
};

// Structured CDR eligibilityType codes that genuinely limit who can apply.
// (MIN_AGE/RESIDENCY_STATUS/NATURAL_PERSON are near-universal and not restrictions.)
const RESTRICTING_TYPES: Record<string, AccessCategory> = {
  STAFF: 'staff',
  EMPLOYMENT_STATUS: 'occupation',
  BUSINESS: 'business',
  STUDENT: 'student',
  PENSION_RECIPIENT: 'pension',
};

const OCCUPATION_RE =
  /\b(police|nurs(?:e|es|ing)|teacher|education(?:\s|al)|doctor|health\s*(?:care|sector|worker)|medical|defence|defense|military|navy|army|veteran|firefighter|ambulance|paramedic|emergency\s*services|first\s*responder)\b/i;
const STAFF_RE = /\b(staff|employe[er]|colleague)\b/i;
const MEMBERSHIP_RE = /\bmembers?\s+of\b|\bassociation\b|\bunion\b|\balumni\b|\bdiocese\b|\bparish\b/i;
const BUSINESS_RE = /\b(business|commercial|corporate|company|smsf|self[-\s]?managed\s+super|trust)\b/i;
const STUDENT_RE = /\bstudent[s]?\b/i;
const GEO_RE = /\bresidents?\s+of\b|\bonly\s+available\s+in\b/i;

function textOf(name: string, detail: ProductDetail | null | undefined): string {
  const parts: string[] = [name || '', detail?.description || ''];
  const push = (items?: DetailItem[]) => {
    for (const it of items ?? []) {
      if (it.name) parts.push(String(it.name));
      if (it.info) parts.push(String(it.info));
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
 * ProductDetail (may be null while details load — then only the name is used).
 */
export function assessAccess(name: string, detail: ProductDetail | null | undefined): AccessAssessment {
  const codes = eligibilityCodes(detail);
  const text = textOf(name, detail);
  const nameText = name || '';

  const cats = new Set<AccessCategory>();
  // Structured codes are authoritative.
  for (const [code, cat] of Object.entries(RESTRICTING_TYPES)) {
    if (codes.has(code)) cats.add(cat);
  }
  // Textual signals.
  if (STAFF_RE.test(text)) cats.add('staff');
  if (OCCUPATION_RE.test(text)) cats.add('occupation');
  if (MEMBERSHIP_RE.test(text)) cats.add('membership');
  if (STUDENT_RE.test(text)) cats.add('student');
  if (GEO_RE.test(text)) cats.add('geographic');
  // Business: ONLY from the structured BUSINESS code (handled above) or the
  // product NAME. Free-text "company/trust/commercial" mentions in eligibility
  // are almost always EXCLUSIONS ("not available to companies or trusts") and
  // would wrongly flag popular retail products (Unloan, Virgin Money Lite).
  if (BUSINESS_RE.test(nameText)) cats.add('business');

  // "Verify": the NAME implies staff/occupation/membership but no structured
  // eligibility code corroborates it (the Coastline/People-First failure mode).
  const nameImpliesRestriction =
    STAFF_RE.test(nameText) || OCCUPATION_RE.test(nameText) || MEMBERSHIP_RE.test(nameText);
  const structurallyConfirmed =
    codes.has('STAFF') || codes.has('EMPLOYMENT_STATUS') || codes.has('BUSINESS') || codes.has('STUDENT');
  const verify = nameImpliesRestriction && !structurallyConfirmed;

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
 * Row-level access restriction derived from the product NAME alone (no details
 * required). This is the name-signal half of {@link assessAccess}, exposed as a
 * cheap predicate the default suitability filter can run over every rate row so
 * staff-only, occupation/union, membership, business/SMSF, student and
 * region-restricted products are not surfaced as headline/search/ranking results
 * to ordinary users. Structured eligibility codes (from loaded details) add more
 * signal via {@link assessAccess}; the name check makes the leak impossible even
 * before details download.
 */
export function nameRestrictsAccess(name: string | null | undefined): boolean {
  const text = name ?? '';
  if (!text) return false;
  return (
    STAFF_RE.test(text) ||
    OCCUPATION_RE.test(text) ||
    MEMBERSHIP_RE.test(text) ||
    STUDENT_RE.test(text) ||
    GEO_RE.test(text) ||
    BUSINESS_RE.test(text)
  );
}
