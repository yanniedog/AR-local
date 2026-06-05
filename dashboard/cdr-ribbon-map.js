(function () {
  'use strict';

  /** Maps flattened local CDR rate rows to ribbon tier rows matching AustralianRates public UI. */

  function lower(value) {
    return String(value == null ? '' : value).trim().toLowerCase();
  }

  /** Mirror cdr_ribbon_normalize.normalize_rate_structure_group for legacy export rows. */
  function rateStructureGroupFromText(raw) {
    var ribbon = window.AR && window.AR.ribbon;
    if (ribbon && typeof ribbon.ribbonRateStructureGroupValue === 'function') {
      var grouped = ribbon.ribbonRateStructureGroupValue(raw);
      if (grouped === 'variable' || grouped === 'fixed') return grouped;
    }
    var value = lower(raw);
    if (!value) return '';
    if (value === 'variable' || /^variable\b/.test(value) || /^bundle[_-]?discount[_-]?variable\b/.test(value)) {
      return 'variable';
    }
    if (value === 'fixed' || /^fixed\b/.test(value)) return 'fixed';
    if (fixedTermYearsFromText(raw)) return 'fixed';
    var head = value.split(/\s+/)[0] || '';
    if (head === 'variable' || head === 'var') return 'variable';
    if (head === 'fixed') return 'fixed';
    if (/\bvariable\b/.test(value.slice(0, 96)) && !/^fixed\b/.test(value)) return 'variable';
    return '';
  }

  function fixedTermYearsFromText(raw) {
    var ribbon = window.AR && window.AR.ribbon;
    if (ribbon && typeof ribbon.ribbonFixedRateTermValue === 'function') {
      return String(ribbon.ribbonFixedRateTermValue(raw) || '').trim();
    }
    var value = lower(raw);
    if (!value || value === 'variable') return '';
    var m = value.match(/^fixed_(\d+)yr$/) || value.match(/fixed[^0-9]*(\d+)/) || value.match(/\bp(\d+)y\b/);
    return m ? String(Number(m[1])) : '';
  }

  function tdRateStructureGroupFromText(raw, depositKind) {
    var kind = lower(depositKind);
    if (kind === 'base' || kind === 'bonus' || kind === 'introductory' || kind === 'bundle' || kind === 'total') {
      return kind;
    }
    var value = lower(raw);
    if (!value) return 'base';
    if (value.indexOf('intro') >= 0) return 'introductory';
    if (value.indexOf('bonus') >= 0) return 'bonus';
    if (value.indexOf('bundle') >= 0) return 'bundle';
    if (value.indexOf('total') >= 0) return 'total';
    var grouped = rateStructureGroupFromText(value);
    return grouped || kind || 'base';
  }

  function parseJson(str, fallback) {
    if (!str) return fallback;
    try {
      return JSON.parse(str);
    } catch (_err) {
      return fallback;
    }
  }

  function trimProduct(name) {
    var ribbon = window.AR && window.AR.ribbon;
    if (ribbon && ribbon.ribbonTrimProductName) return ribbon.ribbonTrimProductName(name);
    return String(name || '').trim();
  }

  function parseTermMonths(duration) {
    var t = String(duration == null ? '' : duration).trim().toUpperCase();
    var isoMatch = t.match(/^P(\d+)([DMYW])$/);
    if (isoMatch) {
      var n = Number(isoMatch[1]);
      var unit = isoMatch[2];
      if (unit === 'M') return n;
      if (unit === 'D') return Math.round(n / 30);
      if (unit === 'Y' || unit === 'W') return unit === 'Y' ? n * 12 : Math.round((n * 7) / 30);
    }
    var monthMatch = t.match(/(\d+)\s*(?:MONTH|MTH|MO)/i);
    if (monthMatch) return Number(monthMatch[1]);
    var dayMatch = t.match(/(\d+)\s*DAY/i);
    if (dayMatch) return Math.round(Number(dayMatch[1]) / 30);
    var yearMatch = t.match(/(\d+)\s*YEAR/i);
    if (yearMatch) return Number(yearMatch[1]) * 12;
    var num = Number(t);
    if (Number.isFinite(num) && num > 0 && num <= 1200) return num;
    return null;
  }

  function normalizeRepaymentType(text) {
    var t = lower(text);
    if (
      t.includes('interest only') ||
      t.includes('interest_only') ||
      t.includes('interestonly') ||
      /\binterest[_\s]*only[_\s]*(?:fixed|variable)?\b/.test(t)
    ) {
      return 'interest_only';
    }
    return 'principal_and_interest';
  }

  function tierForBoundary(percent) {
    var p = Number(percent);
    if (!Number.isFinite(p)) return 'lvr_unspecified';
    if (p > 0 && p <= 1) p = Number((p * 100).toFixed(4));
    if (p <= 60) return 'lvr_=60%';
    if (p <= 70) return 'lvr_60-70%';
    if (p <= 80) return 'lvr_70-80%';
    if (p <= 85) return 'lvr_80-85%';
    if (p <= 90) return 'lvr_85-90%';
    return 'lvr_90-95%';
  }

  // Mirror of cdr_ribbon_normalize.named_lvr_tier: LVR/LTV stated as a bare
  // number with plain or natural-language operators and no % sign — e.g.
  // "<60 LVR", ">90 LVR", "80 LVR", "LVR less than 70". Keep in sync with Python.
  var LVR_SIGNAL_RE = /\b(?:lvr|ltv|loan[\s_-]*to[\s_-]*value)\b/i;
  var LVR_NAME_RANGE = /(\d{1,3}(?:\.\d+)?)\s*(?:-|to)\s*(\d{1,3}(?:\.\d+)?)\s*%?\s*(?:lvr|ltv)|(?:lvr|ltv)\s*:?\s*(\d{1,3}(?:\.\d+)?)\s*(?:-|to)\s*(\d{1,3}(?:\.\d+)?)/i;
  var LVR_OP = '<=|>=|<|>|less[\\s_-]*than[\\s_-]*or[\\s_-]*equal[\\s_-]*to|greater[\\s_-]*than[\\s_-]*or[\\s_-]*equal[\\s_-]*to|less[\\s_-]*than|greater[\\s_-]*than|more[\\s_-]*than|no[\\s_-]*more[\\s_-]*than|at[\\s_-]*least|at[\\s_-]*most|under|below|over|above|from|max(?:imum)?|min(?:imum)?|up[\\s_-]*to';
  var LVR_NAME_OP = new RegExp('(?:(' + LVR_OP + ')\\s*)?(\\d{1,3}(?:\\.\\d+)?)\\s*%?\\s*(?:lvr|ltv)|(?:lvr|ltv)\\s*:?\\s*(?:(' + LVR_OP + ')\\s*)?(\\d{1,3}(?:\\.\\d+)?)', 'i');
  var LVR_TIER_ORDER = ['lvr_=60%', 'lvr_60-70%', 'lvr_70-80%', 'lvr_80-85%', 'lvr_85-90%', 'lvr_90-95%'];
  var LVR_LOWER_BOUND_OPS = {
    '>': 1, '>=': 1, 'over': 1, 'above': 1, 'greater than': 1,
    'greater than or equal to': 1, 'more than': 1, 'at least': 1, 'from': 1,
    'min': 1, 'minimum': 1,
  };

  function bumpTierUp(tier) {
    var i = LVR_TIER_ORDER.indexOf(tier);
    if (i < 0) return tier;
    return LVR_TIER_ORDER[Math.min(i + 1, LVR_TIER_ORDER.length - 1)];
  }

  function isLowerBoundOp(op) {
    var o = String(op || '').trim().toLowerCase().replace(/[\s_-]+/g, ' ');
    return !!LVR_LOWER_BOUND_OPS[o];
  }

  function namedLvrTier(text) {
    var t = lower(text);
    if (!t || !LVR_SIGNAL_RE.test(t)) return '';
    var r = t.match(LVR_NAME_RANGE);
    if (r) {
      var hi = r[2] != null ? r[2] : r[4];
      if (hi != null) return tierForBoundary(Number(hi));
    }
    var m = t.match(LVR_NAME_OP);
    if (m) {
      var op = m[1] != null ? m[1] : m[3];
      var num = m[2] != null ? m[2] : m[4];
      if (num != null) {
        var base = tierForBoundary(Number(num));
        return isLowerBoundOp(op) ? bumpTierUp(base) : base;
      }
    }
    return '';
  }

  function normalizeLvrTier(text, minLvr, maxLvr) {
    var hiFinite = Number.isFinite(Number(maxLvr));
    var loFinite = Number.isFinite(Number(minLvr));
    if (hiFinite || loFinite) {
      var hiRaw = hiFinite ? Number(maxLvr) : Number(minLvr);
      var hi = hiRaw;
      if (hi > 0 && hi <= 1) hi = Number((hi * 100).toFixed(4));
      return tierForBoundary(hi);
    }

    var t = lower(text);
    var range = t.match(/(\d{1,2}(?:\.\d+)?)\s*(?:-|to)\s*(\d{1,2}(?:\.\d+)?)\s*%/);
    if (range) {
      var hi2 = Number(range[2]);
      if (Number.isFinite(hi2)) return tierForBoundary(hi2);
    }

    var le = t.match(/(?:<=|under|up to|maximum|max)\s*(\d{1,2}(?:\.\d+)?)\s*%/);
    if (le) {
      var hi3 = Number(le[1]);
      if (Number.isFinite(hi3)) return tierForBoundary(hi3);
    }

    var anyPercent = t.match(/(\d{1,2}(?:\.\d+)?)\s*%/);
    if (anyPercent && (t.includes('lvr') || t.includes('loan to value') || t.includes('ltv'))) {
      var hi4 = Number(anyPercent[1]);
      if (Number.isFinite(hi4)) return tierForBoundary(hi4);
    }

    return 'lvr_unspecified';
  }

  function textHasLvrSignal(text) {
    var t = lower(text);
    return t.includes('lvr') || t.includes('loan to value') || t.includes('ltv');
  }

  function parseLvrBoundsFromTextBlob(text) {
    var t = lower(text);
    if (!t.trim() || !textHasLvrSignal(t)) return { min: null, max: null };
    var range = t.match(/(\d{1,3}(?:\.\d+)?)\s*(?:-|to)\s*(\d{1,3}(?:\.\d+)?)\s*%?/);
    if (range) {
      var lo = Number(range[1]);
      var hi = Number(range[2]);
      if (Number.isFinite(lo) && Number.isFinite(hi)) return { min: lo, max: hi };
    }
    var le2 = t.match(/(?:<=|under|up to|maximum|max|below)\s*(\d{1,3}(?:\.\d+)?)\s*%?/);
    if (le2) return { min: null, max: Number(le2[1]) };
    var ge = t.match(/(?:>=|over|above|from)\s*(\d{1,3}(?:\.\d+)?)\s*%?/);
    if (ge) return { min: Number(ge[1]), max: null };
    var single = t.match(/(\d{1,3}(?:\.\d+)?)\s*%/);
    if (single) return { min: null, max: Number(single[1]) };
    return { min: null, max: null };
  }

  function resolveLvrTier(contextText, item, productConstraints) {
    var bounds = parseLvrBoundsFromRateItem(item);
    var min = bounds.min;
    var max = bounds.max;
    var source = 'none';
    if (min != null || max != null) {
      source = 'rate_structured';
    } else if (productConstraints && productConstraints.length) {
      var pb = parseLvrBoundsFromConstraints(productConstraints);
      if (pb) {
        min = pb.min;
        max = pb.max;
        if (min != null || max != null) source = 'product_constraints';
      }
    }
    var tier = normalizeLvrTier(contextText, min, max);
    if (tier !== 'lvr_unspecified') {
      if (source === 'none') source = 'context_text';
      return { tier: tier, source: source };
    }
    if (textHasLvrSignal(contextText)) {
      var ctx = parseLvrBoundsFromTextBlob(contextText);
      if (ctx.min != null || ctx.max != null) {
        var tier2 = normalizeLvrTier('', ctx.min, ctx.max);
        if (tier2 !== 'lvr_unspecified') return { tier: tier2, source: 'context_text' };
      }
      // Bare-number LVR in the name (e.g. "<60 LVR", ">90 LVR") — mirror of Python.
      var named = namedLvrTier(contextText);
      if (named) return { tier: named, source: 'context_text' };
    }
    if (productConstraints && productConstraints.length) {
      return { tier: 'lvr_unspecified', source: 'product_unparsed' };
    }
    return { tier: 'lvr_unspecified', source: source };
  }

  function parseNumeric(value) {
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function parseLvrBoundsFromConstraints(constraints) {
    if (!Array.isArray(constraints)) return null;
    var min = null;
    var max = null;
    for (var i = 0; i < constraints.length; i += 1) {
      var c = constraints[i];
      var ctype = lower(c.constraintType || '');
      var info = lower(c.additionalInfo || '');
      if (
        !ctype.includes('lvr') &&
        !ctype.includes('loan to value') &&
        !ctype.includes('ltv') &&
        !info.includes('lvr') &&
        !info.includes('loan to value') &&
        !info.includes('ltv')
      ) {
        continue;
      }
      var additional = parseNumeric(c.additionalValue);
      var minValue = parseNumeric(c.minValue);
      var maxValue = parseNumeric(c.maxValue);
      if (ctype.includes('min')) {
        min = additional ?? minValue ?? min;
      } else if (ctype.includes('max')) {
        max = additional ?? maxValue ?? max;
      } else {
        min = minValue ?? min;
        max = maxValue ?? additional ?? max;
      }
    }
    return min != null || max != null ? { min: min, max: max } : null;
  }

  function parseLvrBoundsFromRateItem(item) {
    var fromConstraints = parseLvrBoundsFromConstraints(Array.isArray(item.constraints) ? item.constraints : []);
    if (fromConstraints) return fromConstraints;

    var tiers = Array.isArray(item.tiers) ? item.tiers : [];
    for (var j = 0; j < tiers.length; j += 1) {
      var tier = tiers[j];
      var tierName = lower([tier.name, tier.unitOfMeasure, tier.rateApplicationMethod].filter(Boolean).join(' '));
      if (!tierName.includes('lvr') && !tierName.includes('loan to value')) continue;
      var tmin = parseNumeric(tier.minimumValue);
      var tmax = parseNumeric(tier.maximumValue);
      if (tmin != null || tmax != null) return { min: tmin, max: tmax };
    }

    var extra = [item.additionalValue, item.additionalInfo].filter(Boolean).join(' ');
    if (!extra) return { min: null, max: null };

    var t = lower(extra);
    var range = t.match(/(\d{1,3}(?:\.\d+)?)\s*(?:-|to)\s*(\d{1,3}(?:\.\d+)?)\s*%?/);
    if (range) {
      var lo = Number(range[1]);
      var hi = Number(range[2]);
      if (Number.isFinite(lo) && Number.isFinite(hi)) return { min: lo, max: hi };
    }
    var le2 = t.match(/(?:<=|under|up to|maximum|max|below)\s*(\d{1,3}(?:\.\d+)?)\s*%?/);
    if (le2) return { min: null, max: Number(le2[1]) };
    var ge = t.match(/(?:>=|over|above|from)\s*(\d{1,3}(?:\.\d+)?)\s*%?/);
    if (ge) return { min: Number(ge[1]), max: null };
    var single = t.match(/(\d{1,3}(?:\.\d+)?)\s*%/);
    if (single) return { min: null, max: Number(single[1]) };

    return { min: null, max: null };
  }

  function normalizeFeatureSet(text, annualFee) {
    var t = lower(text);
    if (
      t.includes('package') ||
      t.includes('advantage') ||
      t.includes('premium') ||
      t.includes('offset') ||
      (annualFee != null && annualFee > 0)
    ) {
      return 'premium';
    }
    return 'basic';
  }

  function parseTierBounds(rateRec) {
    var tiers = Array.isArray(rateRec.tiers) ? rateRec.tiers : [];
    for (var i = 0; i < tiers.length; i += 1) {
      var tier = tiers[i];
      var unit = String(tier.unitOfMeasure || '').toUpperCase();
      if (unit && unit !== 'DOLLAR' && unit !== 'AMOUNT') continue;
      var min = Number.isFinite(Number(tier.minimumValue)) ? Number(tier.minimumValue) : null;
      var max = Number.isFinite(Number(tier.maximumValue)) ? Number(tier.maximumValue) : null;
      if (min != null || max != null) return { min: min, max: max };
    }
    return { min: null, max: null };
  }

  function normalizeAccountType(text) {
    var t = lower(text);
    if (t.includes('at call') || t.includes('at_call')) return 'at_call';
    if (t.includes('savings') || t.includes('saver') || t.includes('save account')) return 'savings';
    if (t.includes('transaction') || t.includes('everyday') || t.includes('spending')) return 'transaction';
    return 'savings';
  }

  function normalizeDepositRateType(raw) {
    var t = lower(raw);
    if (t.includes('bonus')) return 'bonus';
    if (t.includes('introductory') || t.includes('intro')) return 'introductory';
    if (t.includes('bundle') || t.includes('bundled')) return 'bundle';
    if (t.includes('total')) return 'total';
    return 'base';
  }

  function normalizeInterestPayment(text, applicationType, applicationFrequency, termMonths) {
    var t = lower([text, applicationType, applicationFrequency].join(' '));
    var appType = lower(applicationType);
    var frequencyMonths = parseTermMonths(applicationFrequency || '');
    if (appType.includes('maturity')) return 'at_maturity';
    if (frequencyMonths != null && termMonths != null && frequencyMonths >= termMonths) return 'at_maturity';
    if (t.includes('quarterly') || t.includes('quarter')) return 'quarterly';
    if (t.includes('annual') || t.includes('yearly')) return 'annually';
    if (frequencyMonths != null && frequencyMonths >= 12) return 'annually';
    // Semi-annual (P6M → 6) is grouped as monthly for ribbon parity (see cdr_ribbon_normalize.normalize_interest_payment).
    // If cadence facets split, update Python and this function together.
    if (t.includes('monthly') || (frequencyMonths != null && (frequencyMonths === 1 || frequencyMonths === 6))) return 'monthly';
    if (t.includes('at maturity')) return 'at_maturity';
    return 'at_maturity';
  }

  function mortgageRibbonRow(rateRow, item) {
    var structuredPurpose = lower([rateRow.loan_purpose, item.loanPurpose].filter(Boolean).join(' '));
    var securityPurpose = structuredPurpose.includes('invest') ? 'investment' : 'owner_occupied';
    var repaymentHints = [rateRow.repayment_type, item.repaymentType].filter(Boolean).join(' ');
    var repaymentType = normalizeRepaymentType(repaymentHints);
    var lendingRateType = String(item.lendingRateType || rateRow.rate_type || '').trim();
    var contextParts = [item.additionalInfo, item.additionalValue, item.name];
    var contextText = contextParts.filter(Boolean).join(' | ');
    var rateStructureText = [lendingRateType, item.name || '', rateRow.term || '', contextText].filter(Boolean).join(' ');
    var fullContext = [contextText, rateRow.product_name].join(' ');
    var productLvr = Array.isArray(item.productLvrConstraints) ? item.productLvrConstraints : [];
    var lvrResolved = resolveLvrTier(fullContext, item, productLvr);
    var lvrTier = lvrResolved.tier;
    var featureSet = normalizeFeatureSet(fullContext, null);
    var rateStructureGroup = rateStructureGroupFromText(rateStructureText);
    return {
      bank_name: String(rateRow.provider || '').trim(),
      security_purpose: securityPurpose,
      repayment_type: repaymentType,
      rate_structure: rateStructureGroup,
      ribbon_fixed_term:
        rateStructureGroup === 'fixed' ? fixedTermYearsFromText(rateStructureText) : '',
      lvr_tier: lvrTier,
      lvr_source: lvrResolved.source,
      feature_set: featureSet,
      product_name: trimProduct(rateRow.product_name),
      product_id: String(rateRow.product_id || ''),
    };
  }

  function savingsRibbonRow(rateRow, item) {
    var productHint = [rateRow.product_name, rateRow.category].join(' ');
    var accountType = normalizeAccountType(productHint);
    var rateType = normalizeDepositRateType(item.depositRateType || item.rateType || item.type || rateRow.rate_type);
    var bounds = parseTierBounds(item);
    var featureSet = normalizeFeatureSet(productHint + ' ' + String(item.additionalInfo || ''), null);
    return {
      bank_name: String(rateRow.provider || '').trim(),
      account_type: accountType,
      rate_type: rateType,
      min_balance: bounds.min,
      max_balance: bounds.max,
      feature_set: featureSet,
      product_name: trimProduct(rateRow.product_name),
      product_id: String(rateRow.product_id || ''),
    };
  }

  function tdRibbonRow(rateRow, item) {
    var termMonths =
      parseTermMonths(item.additionalValue || '') ||
      parseTermMonths(rateRow.term || '') ||
      parseTermMonths(item.name || '') ||
      parseTermMonths(rateRow.product_name || '');
    if (termMonths == null || !Number.isFinite(termMonths) || termMonths < 1) termMonths = 12;

    var bounds = parseTierBounds(item);
    var paymentText = [item.applicationFrequency, item.additionalInfo, item.applicationType].join(' ');
    var interestPayment = normalizeInterestPayment(paymentText, item.applicationType, item.applicationFrequency, termMonths);
    var depositRateType = String(item.depositRateType || item.rateType || rateRow.rate_type || '').trim();
    var rateStructureText = [depositRateType, item.name || ''].filter(Boolean).join(' ');
    var depositKind = normalizeDepositRateType(depositRateType);
    var featureSet = normalizeFeatureSet([rateRow.product_name, paymentText].join(' '), null);

    return {
      bank_name: String(rateRow.provider || '').trim(),
      term_months: termMonths,
      min_balance: bounds.min,
      max_balance: bounds.max,
      interest_payment: interestPayment,
      rate_structure: tdRateStructureGroupFromText(rateStructureText, depositKind),
      feature_set: featureSet,
      product_name: trimProduct(rateRow.product_name),
      product_id: String(rateRow.product_id || ''),
    };
  }

  function parseBalance(value) {
    if (value === undefined || value === null || value === '') return null;
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function isRibbonNormalized(rateRow) {
    return rateRow.ribbon_normalized === true || rateRow.ribbon_normalized === '1';
  }

  function normalizedRateStructureGroup(structureRaw) {
    var g = String(structureRaw || '').trim().toLowerCase();
    if (g === 'fixed' || g === 'variable') return g;
    return rateStructureGroupFromText(structureRaw);
  }

  function ribbonRowFromFlat(rateRow, section) {
    var bMin = parseBalance(rateRow.balance_min);
    var bMax = parseBalance(rateRow.balance_max);
    var bank = String(rateRow.provider || '').trim();
    if (section === 'Mortgage') {
      var structureRaw = rateRow.ribbon_rate_structure;
      var structureGroup = normalizedRateStructureGroup(structureRaw);
      return {
        bank_name: bank,
        security_purpose: rateRow.security_purpose,
        repayment_type: rateRow.ribbon_repayment_type,
        rate_structure: structureGroup,
        ribbon_fixed_term: String(rateRow.ribbon_fixed_term || '').trim(),
        lvr_tier: rateRow.lvr_tier,
        lvr_source: rateRow.lvr_source,
        feature_set: rateRow.feature_set,
        product_name: trimProduct(rateRow.product_name),
        product_id: String(rateRow.product_id || ''),
      };
    }
    if (section === 'Savings') {
      return {
        bank_name: bank,
        account_type: rateRow.account_type,
        rate_type: rateRow.ribbon_deposit_kind,
        min_balance: bMin,
        max_balance: bMax,
        feature_set: rateRow.feature_set,
        product_name: trimProduct(rateRow.product_name),
        product_id: String(rateRow.product_id || ''),
      };
    }
    var tm = Number(rateRow.term_months);
    if (!Number.isFinite(tm) || tm < 1) tm = 12;
    return {
      bank_name: bank,
      term_months: tm,
      min_balance: bMin,
      max_balance: bMax,
      interest_payment: rateRow.interest_payment,
      rate_structure: tdRateStructureGroupFromText(
        rateRow.ribbon_rate_structure,
        rateRow.ribbon_deposit_kind,
      ),
      feature_set: rateRow.feature_set,
      product_name: trimProduct(rateRow.product_name),
      product_id: String(rateRow.product_id || ''),
    };
  }

  function sectionSlug(section) {
    if (section === 'Savings') return 'savings';
    if (section === 'TD') return 'term-deposits';
    return 'home-loans';
  }

  /** Align section-row ribbon facets with history (cdr_dashboard_server.canonicalize_history_row). */
  function hydrateCanonicalRibbonFields(rateRow, section) {
    if (!rateRow || !section) return;
    var structureRaw = rateRow.ribbon_rate_structure;
    if (section === 'Mortgage') {
      var group = rateStructureGroupFromText(structureRaw);
      rateRow.ribbon_rate_structure = group || '';
      if (group === 'fixed' && !String(rateRow.ribbon_fixed_term || '').trim()) {
        var years = fixedTermYearsFromText(structureRaw);
        if (years) rateRow.ribbon_fixed_term = years;
      }
      return;
    }
    if (section === 'Savings' || section === 'TD') {
      rateRow.ribbon_rate_structure = tdRateStructureGroupFromText(structureRaw, rateRow.ribbon_deposit_kind);
    }
  }

  function productKeyFromRate(rateRow) {
    return (
      String(rateRow.product_key || '') +
      '\u0001' +
      String(rateRow.rate_family || '') +
      '\u0001' +
      String(rateRow.rate_index || '') +
      '\u0001' +
      String(rateRow.rate_type || '') +
      '\u0001' +
      String(rateRow.term || '')
    );
  }

  /**
   * @param {object[]} rateRows normalized visible rows (post LocalCdrUtils.normalizeRows)
   * @param {string} section Mortgage | Savings | TD
   */
  function toRibbonProducts(rateRows, section) {
    var out = [];
    for (var i = 0; i < rateRows.length; i += 1) {
      var rateRow = rateRows[i];
      var item = parseJson(rateRow.details_json, {});
      var ribbonRow = isRibbonNormalized(rateRow)
        ? ribbonRowFromFlat(rateRow, section)
        : section === 'Mortgage'
          ? mortgageRibbonRow(rateRow, item)
          : section === 'Savings'
            ? savingsRibbonRow(rateRow, item)
            : tdRibbonRow(rateRow, item);
      out.push({
        row: ribbonRow,
        key: productKeyFromRate(rateRow),
        __cdrRate: rateRow,
      });
    }
    return out;
  }

  window.LocalCdrRibbonMap = {
    sectionSlug: sectionSlug,
    hydrateCanonicalRibbonFields: hydrateCanonicalRibbonFields,
    toRibbonProducts: toRibbonProducts,
  };
})();
