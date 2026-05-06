(function () {
  'use strict';

  /** Matches filenames under AustralianRates `site/assets/banks/` (png/webp/svg). */
  const ICON_EXTENSIONS = ['.png', '.webp', '.svg'];
  const LOCAL_BANK_BASE = '/assets/banks/';
  const CDN_BANK_BASE = 'https://www.australianrates.com.au/assets/banks/';

  /** Extra slug basenames tried before generic slugify (Westpac group shares pack assets). */
  const GROUP_SLUG_HINTS = [
    { re: /banksa|bank\s+sa\b/i, slugs: ['westpac-banking-corporation'] },
    { re: /\brams\b/i, slugs: ['westpac-banking-corporation'] },
  ];

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
    if (/banksa|bank\s+sa\b/i.test(raw)) return 'westpac banking corporation';
    if (/\brams\b/i.test(raw)) return 'westpac banking corporation';
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
      groupSlugHints(name).forEach((s) => pushSlug(out, seen, s));
      iconSlugCandidates(name).forEach((s) => pushSlug(out, seen, s));
    });
    return out;
  }

  function groupSlugHints(label) {
    const raw = String(label || '');
    const out = [];
    GROUP_SLUG_HINTS.forEach((rule) => {
      if (rule.re.test(raw)) rule.slugs.forEach((s) => out.push(s));
    });
    return out;
  }

  function orderedSlugBasenames(provider, row, extraSlugs) {
    const seen = new Set();
    const out = [];
    const push = (s) => {
      if (!s || seen.has(s)) return;
      seen.add(s);
      out.push(s);
    };
    groupSlugHints(provider).forEach(push);
    (extraSlugs || []).forEach(push);
    if (row && typeof row === 'object') {
      iconSlugCandidatesForRate(row).forEach(push);
    } else {
      iconSlugCandidates(provider).forEach(push);
    }
    return out;
  }

  /** Same filename under CDN when local `/assets/banks/*` is missing or server misconfigured. */
  function cdnTwinForLocalBankUrl(localUrl) {
    const u = String(localUrl || '').trim();
    if (!u.startsWith(LOCAL_BANK_BASE)) return '';
    return CDN_BANK_BASE + u.slice(LOCAL_BANK_BASE.length);
  }

  /** Basename without extension, e.g. `/assets/banks/anz.png` -> `anz`. */
  function slugFromBankIconUrl(url) {
    const u = String(url || '').trim();
    if (!u) return '';
    const seg = u.split('?')[0].split('/').pop() || '';
    return seg.replace(/\.(png|webp|svg)$/i, '');
  }

  function logoUrlsFromSlugs(slugs) {
    const urls = [];
    const seen = new Set();
    let remoteFirst = false;
    try {
      const h = window.location.hostname || '';
      remoteFirst = h === '127.0.0.1' || h === 'localhost' || h === '[::1]';
    } catch (_e) {
      remoteFirst = false;
    }
    slugs.forEach((slug) => {
      ICON_EXTENSIONS.forEach((ext) => {
        const local = LOCAL_BANK_BASE + slug + ext;
        const remote = CDN_BANK_BASE + slug + ext;
        const order = remoteFirst ? [remote, local] : [local, remote];
        order.forEach((u) => {
          if (!seen.has(u)) {
            seen.add(u);
            urls.push(u);
          }
        });
      });
    });
    return urls;
  }

  function abbrevFallback(meta, provider) {
    const short = String(meta.short || '').replace(/[^A-Za-z0-9]/g, '').trim();
    if (short.length >= 2) return short.slice(0, 3).toUpperCase();
    const words = String(provider || '')
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (!words.length) return '?';
    if (words.length === 1) return words[0].slice(0, 3).toUpperCase();
    return words
      .slice(0, 3)
      .map((w) => w.charAt(0))
      .join('')
      .toUpperCase();
  }

  function mountLogoIntoWrap(logoWrap, metaIcon, slugBasenames, meta, provider) {
    while (logoWrap.firstChild) logoWrap.removeChild(logoWrap.firstChild);
    const urls = [];
    const seen = new Set();
    const pushUrl = (u) => {
      if (!u || seen.has(u)) return;
      seen.add(u);
      urls.push(u);
    };
    let remoteFirst = false;
    try {
      const h = window.location.hostname || '';
      remoteFirst = h === '127.0.0.1' || h === 'localhost' || h === '[::1]';
    } catch (_e) {
      remoteFirst = false;
    }
    if (remoteFirst && metaIcon) {
      pushUrl(cdnTwinForLocalBankUrl(metaIcon));
      pushUrl(metaIcon);
    } else {
      pushUrl(metaIcon);
      pushUrl(cdnTwinForLocalBankUrl(metaIcon));
    }
    logoUrlsFromSlugs(slugBasenames).forEach(pushUrl);

    if (!urls.length) {
      child(logoWrap, 'span', 'bank-badge-fallback local-bank-fallback-neutral', abbrevFallback(meta, provider));
      return;
    }

    const img = document.createElement('img');
    img.className = 'bank-badge-logo';
    img.alt = '';
    img.width = 32;
    img.height = 32;
    img.loading = 'eager';
    img.draggable = false;
    const finishNeutral = () => {
      img.onload = null;
      img.onerror = null;
      img.remove();
      child(logoWrap, 'span', 'bank-badge-fallback local-bank-fallback-neutral', abbrevFallback(meta, provider));
    };
    function attempt(index) {
      if (index >= urls.length) {
        finishNeutral();
        return;
      }
      img.onload = () => {
        img.onload = null;
        img.onerror = null;
        if (!logoWrap.contains(img)) logoWrap.appendChild(img);
      };
      img.onerror = () => {
        attempt(index + 1);
      };
      img.src = urls[index];
    }
    attempt(0);
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
   * @param {{ slugCandidates?: string[], logoOnly?: boolean, rateRow?: object } | undefined} options
   */
  function appendProviderBadge(parent, provider, showName, options) {
    const opts = options || {};
    const meta = providerMeta(provider);
    let slugBasenames = orderedSlugBasenames(provider, opts.rateRow, opts.slugCandidates || []);
    const iconSlug = slugFromBankIconUrl(meta.icon || '');
    if (iconSlug) {
      const seen = new Set(slugBasenames);
      if (!seen.has(iconSlug)) slugBasenames = [iconSlug].concat(slugBasenames);
    }
    const classes = ['bank-badge', 'local-bank-badge'];
    if (opts.logoOnly) classes.push('local-bank-badge--logo-only');
    const badge = child(parent, 'span', classes.join(' '));
    badge.title = provider || meta.name;
    const logo = child(badge, 'span', 'bank-badge-logo-wrap');
    logo.setAttribute('aria-hidden', 'true');
    mountLogoIntoWrap(logo, meta.icon || '', slugBasenames, meta, provider);
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
    logoUrlsFromSlugs,
    orderedSlugBasenames,
    providerMeta,
  };
})();
