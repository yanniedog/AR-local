(function () {
  'use strict';

  function child(parent, tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text != null) element.textContent = String(text);
    parent.appendChild(element);
    return element;
  }

  function slugify(value) {
    return String(value || '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
  }

  /** Strip tokens that rarely appear in `site/assets/banks/*.png` filenames. */
  function stripCorporateSuffixes(value) {
    return String(value || '')
      .replace(/\b(australia|australian)\b/gi, '')
      .replace(/\b(limited|ltd\.?|plc\.?|pty\.?\s*ltd\.?|inc\.?|a\.s\.?|n\.p\.?)\b/gi, '')
      .replace(/\b(credit\s+union|mutual|building\s+society)\b/gi, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  /** Align folder / register labels with AustralianRates `ar-bank-brand.js` canonical keys. */
  function lookupProvider(value) {
    const raw = String(value || '').toLowerCase();
    if (raw.includes('great southern')) return 'great southern bank';
    if (raw.includes('86400') || raw.includes('86 400')) return 'ubank';
    if (raw.includes('amp')) return 'amp bank';
    if (raw.includes('anz')) return 'anz';
    if (raw.includes('commonwealth') || raw.includes('commbank')) return 'commonwealth bank of australia';
    if (raw.includes('national australia') || raw === 'nab' || raw.startsWith('nab ')) return 'national australia bank';
    if (raw.includes('westpac')) return 'westpac banking corporation';
    if (raw.includes('macquarie')) return 'macquarie bank';
    if (raw.includes('bankwest')) return 'bankwest';
    if (/\bing\b/.test(raw)) return 'ing';
    if (raw.includes('hsbc')) return 'hsbc australia';
    if (raw.includes('ubank') || raw.includes('u bank')) return 'ubank';
    if (raw.includes('suncorp')) return 'suncorp bank';
    if (raw.includes('st george') || raw.includes('st.george') || raw.includes('st george')) return 'st. george bank';
    if (raw.includes('bendigo')) return 'bendigo and adelaide bank';
    if (raw.includes('queensland') || /\bboq\b/.test(raw)) return 'bank of queensland';
    if (raw.includes('melbourne') && raw.includes('bank')) return 'bank of melbourne';
    return value;
  }

  function pushSlug(out, seen, s) {
    if (!s || seen.has(s)) return;
    seen.add(s);
    out.push(s);
  }

  function iconSlugCandidates(provider) {
    const canonical = lookupProvider(provider);
    const rawVariants = [provider, canonical].filter(Boolean).flatMap((v) => [v, stripCorporateSuffixes(v)]);
    const seen = new Set();
    const out = [];
    rawVariants.forEach((v) => {
      const s = slugify(v);
      pushSlug(out, seen, s);
      if (s && s.endsWith('-bank')) pushSlug(out, seen, s.replace(/-bank$/u, ''));
      else if (s) pushSlug(out, seen, `${s}-bank`);
    });
    return out;
  }

  /**
   * Merge slug guesses from CDR folder provider plus register brand fields so filenames match.
   * @param {{ provider?: string, brand_name?: string, brand?: string }} row
   */
  function iconSlugCandidatesForRate(row) {
    const names = [row.provider, row.brand_name, row.brand, lookupProvider(row.provider)].filter(Boolean);
    const seen = new Set();
    const out = [];
    names.forEach((name) => {
      iconSlugCandidates(name).forEach((s) => pushSlug(out, seen, s));
    });
    return out;
  }

  function providerMeta(value) {
    const brand = window.AR && window.AR.bankBrand;
    const canonical = lookupProvider(value);
    return brand && brand.getMeta ? brand.getMeta(canonical) : { name: value || 'Provider', short: value || '-', icon: '' };
  }

  /**
   * @param {HTMLElement} parent
   * @param {string} provider
   * @param {boolean} showName
   * @param {{ slugCandidates?: string[], logoOnly?: boolean } | undefined} options
   */
  function appendProviderBadge(parent, provider, showName, options) {
    const opts = options || {};
    const slugCandidates = opts.slugCandidates && opts.slugCandidates.length ? opts.slugCandidates : iconSlugCandidates(provider);
    const meta = providerMeta(provider);
    const classes = ['bank-badge', 'local-bank-badge'];
    if (opts.logoOnly) classes.push('local-bank-badge--logo-only');
    const badge = child(parent, 'span', classes.join(' '));
    badge.title = provider || meta.name;
    const logo = child(badge, 'span', 'bank-badge-logo-wrap');
    logo.setAttribute('aria-hidden', 'true');
    const shortLetter = (meta.short || String(provider || '?').trim().charAt(0) || '?').charAt(0);
    if (meta.icon) {
      const img = child(logo, 'img', 'bank-badge-logo');
      img.src = meta.icon;
      img.alt = '';
      img.width = 32;
      img.height = 32;
      img.loading = 'lazy';
      img.draggable = false;
    } else if (!slugCandidates.length) {
      child(logo, 'span', 'bank-badge-fallback', shortLetter);
    } else {
      let index = 0;
      const img = child(logo, 'img', 'bank-badge-logo');
      img.alt = '';
      img.width = 32;
      img.height = 32;
      img.loading = 'lazy';
      img.draggable = false;
      const showFallback = () => {
        img.remove();
        child(logo, 'span', 'bank-badge-fallback', shortLetter);
      };
      img.onerror = () => {
        index += 1;
        if (index >= slugCandidates.length) showFallback();
        else img.src = '/assets/banks/' + slugCandidates[index] + '.png';
      };
      img.src = '/assets/banks/' + slugCandidates[0] + '.png';
    }
    const copy = child(badge, 'span', 'bank-badge-copy');
    child(copy, 'span', 'bank-badge-label', meta.short || provider || '-');
    if (showName) child(copy, 'span', 'bank-badge-sub', provider || meta.name);
    return badge;
  }

  window.LocalCdrBrand = {
    appendProviderBadge,
    iconSlugCandidates,
    iconSlugCandidatesForRate,
    lookupProvider,
    providerMeta,
  };
})();
