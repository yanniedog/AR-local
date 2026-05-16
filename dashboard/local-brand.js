(function () {
  'use strict';

  /** Matches filenames under AustralianRates `site/assets/banks/` (png/webp/svg). */
  const ICON_EXTENSIONS = ['.png', '.webp', '.svg'];
  const ICON_EXTENSION_RE = new RegExp(
    '(' + ICON_EXTENSIONS.map((ext) => ext.replace('.', '\\.')).join('|') + ')$',
    'i',
  );
  const LOCAL_BANK_BASE = '/assets/banks/';
  const CDN_BANK_BASE = 'https://www.australianrates.com.au/assets/banks/';

  /** Extra slug basenames tried before generic slugify (Westpac group shares pack assets). */
  const GROUP_SLUG_HINTS = [
    { re: /banksa|bank\s+sa\b/i, slugs: ['westpac-banking-corporation'] },
    { re: /\brams\b/i, slugs: ['westpac-banking-corporation'] },
  ];

  /**
   * Domain lookup for Australian energy retailers. Used to fetch a Clearbit
   * logo when no local/CDN asset exists. Only populated for well-known
   * retailers to avoid spurious lookups for obscure providers.
   */
  const ENERGY_DOMAINS = {
    'agl': 'agl.com.au',
    'origin energy': 'originenergy.com.au',
    'energyaustralia': 'energyaustralia.com.au',
    'alinta energy': 'alintaenergy.com.au',
    'red energy': 'redenergy.com.au',
    'lumo energy': 'lumoenergy.com.au',
    'momentum energy': 'momentum.com.au',
    'dodo power & gas': 'dodo.com',
    'dodo': 'dodo.com',
    'engie': 'engie.com.au',
    'amber': 'amber.com.au',
    'powershop': 'powershop.com.au',
    'actewagl': 'actewagl.com.au',
    'aurora energy': 'auroraenergy.com.au',
    'ergon energy': 'ergon.com.au',
    'ergon energy retail': 'ergon.com.au',
    'simply energy': 'simplyenergy.com.au',
    'tango energy': 'tangoenergy.com',
    'sumo power': 'sumo.com.au',
    'diamond energy': 'diamondenergy.com.au',
    'nectr': 'nectr.com.au',
    'real utilities': 'realutilities.com.au',
    'kogan energy': 'kogan.com',
    'ovo energy': 'ovoenergy.com.au',
    'flow power': 'flowpower.com.au',
    'globird energy': 'globirdenergy.com.au',
    'zen energy': 'zenenergy.com.au',
    '1st energy': '1stenergy.com.au',
    'racv': 'racv.com.au',
    'arcline by racv': 'racv.com.au',
    'blue nrg': 'bluenrg.com.au',
    'covau': 'covau.com.au',
    'future x power': 'futurexpower.com.au',
    'energy locals': 'energylocals.com.au',
    'energy locals urban': 'energylocals.com.au',
    'solstice energy': 'solsticeenergy.com.au',
    'radian energy': 'radianenergy.com.au',
    'raa energy': 'raa.com.au',
    'flipped energy': 'flippedenergy.com.au',
    'gee energy': 'geeenergy.com.au',
    'next business energy': 'nextbusinessenergy.com.au',
    'myob powered by ovo': 'myob.com',
    'io energy': 'ioenergy.com.au',
    'perpetual energy': 'perpetualenergy.com.au',
    'erc energy': 'ercenergy.com.au',
  };

  /**
   * Additional domain lookup for bank providers that aren't covered by the
   * australianrates CDN logo pack. Clearbit is tried as a final fallback.
   */
  const BANK_DOMAINS = {
    'arab bank australia': 'arabbank.com.au',
    'alex.bank': 'alexbank.com',
    'alex bank': 'alexbank.com',
    'bank australia': 'bankaust.com.au',
    'bank first': 'bankfirst.com.au',
    'bank of china': 'boc.cn',
    'bank of sydney': 'bankofsydney.com.au',
    'bank of us': 'bankofus.com.au',
    'auswide bank': 'auswidebank.com.au',
    'border bank': 'borderbank.com.au',
    'cairns bank': 'cairnsbank.com.au',
    'credit union sa': 'creditunionsa.com.au',
    'darling downs bank': 'darlingsbank.com.au',
    'defence bank': 'defencebank.com.au',
    'family first': 'familyfirst.com.au',
    'greater bank': 'greater.com.au',
    'hume bank': 'humebank.com.au',
    'imb bank': 'imb.com.au',
    'judo bank': 'judo.bank',
    'liberty financial': 'liberty.com.au',
    'move bank': 'movebank.com.au',
    'mystate bank': 'mystate.com.au',
    'people first bank': 'peoplefirstbank.com.au',
    'police bank': 'policebank.com.au',
    'qudos bank': 'qudosbank.com.au',
    'racq bank': 'racq.com.au',
    'south west credit union': 'swcu.com.au',
    'southern cross credit union': 'southerncross.com.au',
    'the capricornian': 'capricornian.com.au',
    'transport mutual credit union': 'tmcu.com.au',
    'unity bank': 'unitybank.com.au',
    'up': 'up.com.au',
    'unibank': 'unibank.com.au',
    'victoria teachers mutual bank': 'victeach.com.au',
    'banksa': 'banksa.com.au',
    'boq specialist': 'boqspecialist.com.au',
    'bnk bank': 'bnkbank.com.au',
    'me bank': 'mebank.com.au',
    'me bank me go': 'mebank.com.au',
    'me go': 'mebank.com.au',
    'newcastle permanent': 'newcastlepermanent.com.au',
    'newcastle permanent building society': 'newcastlepermanent.com.au',
    'maitland mutual': 'maitlandmutual.com.au',
    'maitland mutual limited': 'maitlandmutual.com.au',
    'heartland': 'heartlandbank.com.au',
    'heartland australia': 'heartlandbank.com.au',
    'paypal australia': 'paypal.com',
    'tyro': 'tyro.com',
    'tyro banking': 'tyro.com',
    'tyro payments': 'tyro.com',
    'rsl money': 'rslmoney.com.au',
    'solo by myob': 'myob.com',
    'in1bank': 'in1bank.com.au',
    'in1bank ltd': 'in1bank.com.au',
    'virgin money': 'virginmoney.com.au',
    'unloan': 'unloan.com.au',
    'great southern bank business+': 'greatsouthernbank.com.au',
    'hsbc wholesale': 'hsbc.com.au',
    'traditional credit union': 'tcu.com.au',
    'anz plus': 'anz.com.au',
    'amp bank go': 'amp.com.au',
    'afg home loans': 'afgonline.com.au',
    'aussie home loans': 'aussie.com.au',
    'aussie elevate': 'aussie.com.au',
    'aussie': 'aussie.com.au',
    'amp - my amp': 'amp.com.au',
    'amp bank go': 'amp.com.au',
    'anz plus': 'anz.com.au',
    'australian military bank': 'australianmilitarybank.com.au',
    'australian mutual bank': 'australianmutual.bank',
    'bank of melbourne': 'bankofmelbourne.com.au',
    'pepper money': 'peppermoney.com.au',
    'firstmac': 'firstmac.com.au',
    'mecu': 'bankaust.com.au',
  };

  /** Clearbit Logo API — used as last resort when no local/CDN icon is found. */
  function clearbitUrl(domain) {
    return 'https://logo.clearbit.com/' + domain + '?size=64';
  }

  /** Look up the Clearbit URL for a given provider label (energy or bank). */
  function clearbitUrlForProvider(label) {
    const key = String(label || '').trim().toLowerCase();
    const domain = ENERGY_DOMAINS[key] || BANK_DOMAINS[key];
    if (domain) return clearbitUrl(domain);
    return '';
  }

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
    const raw = String(value || '').toLowerCase().trim();
    // Order matters — more-specific variants come before broader prefixes.
    if (/great southern bank business/i.test(raw)) return 'great southern bank business+';
    if (raw.includes('great southern')) return 'great southern bank';
    if (raw.includes('86400') || raw.includes('86 400')) return 'ubank';
    if (raw.includes('amp bank go') || raw === 'amp go') return 'amp bank go';
    if (raw.includes('amp')) return 'amp bank';
    if (raw.includes('anz plus')) return 'anz plus';
    if (raw.includes('anz')) return 'anz';
    if (raw.includes('unloan')) return 'unloan';
    if (raw.includes('commonwealth') || raw.includes('commbank') || raw === 'cba') return 'commonwealth bank of australia';
    if (raw.includes('national australia') || raw === 'nab' || raw.startsWith('nab ')) return 'national australia bank';
    if (raw.includes('westpac')) return 'westpac banking corporation';
    if (/banksa|bank\s+sa\b/i.test(raw)) return 'banksa';
    if (/\brams\b/i.test(raw)) return 'westpac banking corporation';
    if (raw.includes('macquarie')) return 'macquarie bank';
    if (raw.includes('bankwest')) return 'bankwest';
    if (/\bing\b/.test(raw)) return 'ing';
    if (/hsbc.*wholesale|wholesale.*hsbc/i.test(raw)) return 'hsbc wholesale';
    if (raw.includes('hsbc')) return 'hsbc australia';
    if (raw.includes('ubank') || raw.includes('u bank')) return 'ubank';
    if (raw.includes('suncorp')) return 'suncorp bank';
    if (/st\s*\.?\s*george/i.test(raw)) return 'st. george bank';
    if (raw.includes('bendigo')) return 'bendigo and adelaide bank';
    if (raw.includes('boq specialist')) return 'boq specialist';
    if (raw.includes('queensland') || /\bboq\b/.test(raw)) return 'bank of queensland';
    if (raw.includes('melbourne') && raw.includes('bank')) return 'bank of melbourne';
    if (raw.includes('alex')) return 'alex bank';
    if (raw.includes('arab bank')) return 'arab bank australia';
    if (raw.includes('australian military')) return 'australian military bank';
    if (raw.includes('auswide')) return 'auswide bank';
    if (raw.includes('bnk bank') || raw.includes('goldfields money')) return 'bnk bank';
    if (raw.includes('bank australia') || raw === 'mecu') return 'bank australia';
    if (raw.includes('bank first')) return 'bank first';
    if (raw.includes('bank of china')) return 'bank of china';
    if (raw.includes('bank of sydney')) return 'bank of sydney';
    if (raw.includes('bank of us')) return 'bank of us';
    if (raw.includes('border bank')) return 'border bank';
    if (raw.includes('cairns')) return 'cairns bank';
    if (raw.includes('credit union sa')) return 'credit union sa';
    if (raw.includes('darling downs')) return 'darling downs bank';
    if (raw.includes('defence bank')) return 'defence bank';
    if (raw.includes('family first')) return 'family first';
    if (raw.includes('greater bank')) return 'greater bank';
    if (raw.includes('heartland')) return 'heartland';
    if (raw.includes('hume bank')) return 'hume bank';
    if (raw.includes('imb')) return 'imb bank';
    if (raw.includes('in1')) return 'in1bank';
    if (raw.includes('judo')) return 'judo bank';
    if (raw.includes('liberty')) return 'liberty financial';
    if (raw.includes('maitland mutual')) return 'maitland mutual';
    if (/\bme\s*bank\b.*\bme\s*go\b/i.test(raw) || raw.includes('me go')) return 'me bank me go';
    if (raw.includes('me bank') || /^me$/.test(raw)) return 'me bank';
    if (raw.includes('mystate')) return 'mystate bank';
    if (raw.includes('newcastle permanent')) return 'newcastle permanent';
    if (raw.includes('paypal')) return 'paypal australia';
    if (raw.includes('police bank')) return 'police bank';
    if (raw.includes('qudos')) return 'qudos bank';
    if (raw.includes('racq')) return 'racq bank';
    if (raw.includes('rsl money')) return 'rsl money';
    if (raw.includes('solo by myob') || raw === 'solo' || raw === 'myob') return 'solo by myob';
    if (raw.includes('southern cross credit')) return 'southern cross credit union';
    if (raw.includes('capricornian')) return 'the capricornian';
    if (raw.includes('traditional credit union')) return 'traditional credit union';
    if (raw.includes('tyro')) return 'tyro';
    if (raw === 'up' || raw === 'up bank') return 'up';
    if (raw.includes('virgin')) return 'virgin money';
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
    return seg.replace(ICON_EXTENSION_RE, '');
  }

  /** True on typical local dashboard hosts: try CDN bank URLs before same-origin /assets/banks/. */
  function preferBankCdnFirst() {
    try {
      const h = window.location.hostname || '';
      return h === '127.0.0.1' || h === 'localhost' || h === '[::1]';
    } catch (_e) {
      return false;
    }
  }

  function logoUrlsFromSlugs(slugs) {
    const urls = [];
    const seen = new Set();
    const remoteFirst = preferBankCdnFirst();
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

  function mountLogoIntoWrap(logoWrap, metaIcon, slugBasenames, meta, provider, clearbitFallback) {
    while (logoWrap.firstChild) logoWrap.removeChild(logoWrap.firstChild);
    const urls = [];
    const seen = new Set();
    const pushUrl = (u) => {
      if (!u || seen.has(u)) return;
      seen.add(u);
      urls.push(u);
    };
    const remoteFirst = preferBankCdnFirst();
    if (remoteFirst && metaIcon) {
      pushUrl(cdnTwinForLocalBankUrl(metaIcon));
      pushUrl(metaIcon);
    } else {
      pushUrl(metaIcon);
      pushUrl(cdnTwinForLocalBankUrl(metaIcon));
    }
    logoUrlsFromSlugs(slugBasenames).forEach(pushUrl);
    if (clearbitFallback) pushUrl(clearbitFallback);

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
    const clearbitFallback = clearbitUrlForProvider(provider);
    const classes = ['bank-badge', 'local-bank-badge'];
    if (opts.logoOnly) classes.push('local-bank-badge--logo-only');
    const badge = child(parent, 'span', classes.join(' '));
    badge.title = provider || meta.name;
    const logo = child(badge, 'span', 'bank-badge-logo-wrap');
    logo.setAttribute('aria-hidden', 'true');
    mountLogoIntoWrap(logo, meta.icon || '', slugBasenames, meta, provider, clearbitFallback);
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
