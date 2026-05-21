(function () {
  'use strict';

  /** Matches filenames under AustralianRates `site/assets/banks/` (png/webp/svg). */
  const ICON_EXTENSIONS = ['.png', '.webp', '.svg'];
  const ICON_EXTENSION_RE = new RegExp(
    '(' + ICON_EXTENSIONS.map((ext) => ext.replace('.', '\\.')).join('|') + ')$',
    'i',
  );
  const LOCAL_BANK_BASE = '/assets/banks/';
  const CDN_BANK_BASE = 'https://australianrates.com/assets/banks/';

  /** Extra slug basenames tried before generic slugify (Westpac group shares pack assets). */
  const GROUP_SLUG_HINTS = [
    { re: /\brams\b/i, slugs: ['westpac-banking-corporation'] },
  ];

  /**
   * Additional domain lookup for bank providers that aren't covered by the
   * australianrates CDN logo pack. Clearbit is tried as a final fallback.
   */
  const BANK_DOMAINS = {
    'afg home loans': 'afgonline.com.au',
    'alex.bank': 'alex.bank',
    'alex bank': 'alex.bank',
    'amp - my amp': 'amp.com.au',
    'amp bank': 'amp.com.au',
    'amp bank go': 'amp.com.au',
    'anz': 'anz.com.au',
    'anz plus': 'anz.com.au/plus/',
    'arab bank australia': 'www.arabbank.com.au',
    'auswide bank': 'auswidebank.com.au',
    'aussie': 'aussie.com.au',
    'aussie elevate': 'aussie.com.au',
    'aussie home loans': 'aussie.com.au',
    'australian military bank': 'australianmilitarybank.com.au',
    'australian mutual bank': 'australianmutual.bank',
    'bank australia': 'bankaust.com.au',
    'bank first': 'bankfirst.com.au',
    'bank of china': 'www.bankofchina.com/au/',
    'bank of melbourne': 'bankofmelbourne.com.au',
    'bank of queensland': 'boq.com.au',
    'bank of sydney': 'bankofsydney.com.au',
    'bank of us': 'bankofus.com.au',
    'banksa': 'banksa.com.au',
    'bankwest': 'bankwest.com.au',
    'bendigo and adelaide bank': 'bendigobank.com.au',
    'bendigo bank': 'bendigobank.com.au',
    'bnk bank': 'bnk.com.au',
    'boq specialist': 'boqspecialist.com.au',
    'border bank': 'borderbank.com.au',
    'cairns bank': 'cairnsbank.com.au',
    'commbank': 'commbank.com.au',
    'commonwealth bank of australia': 'commbank.com.au',
    'credit union sa': 'creditunionsa.com.au',
    'darling downs bank': 'ddbank.com.au',
    'defence bank': 'defencebank.com.au',
    'family first': 'familyfirst.com.au',
    'firstmac': 'firstmac.com.au',
    'greater bank': 'greater.com.au',
    'great southern bank': 'greatsouthernbank.com.au',
    'great southern bank business+': 'greatsouthernbank.com.au',
    'heartland': 'heartlandbank.com.au',
    'heartland australia': 'heartlandbank.com.au',
    'hsbc australia': 'hsbc.com.au',
    'hsbc wholesale': 'hsbc.com.au',
    'hume bank': 'humebank.com.au',
    'imb bank': 'imb.com.au',
    'in1bank': 'in1bank.com.au',
    'in1bank ltd': 'in1bank.com.au',
    'ing': 'ing.com.au',
    'judo bank': 'judo.bank',
    'liberty financial': 'liberty.com.au',
    'macquarie bank': 'macquarie.com.au',
    'maitland mutual': 'www.themutual.com.au',
    'maitland mutual limited': 'www.themutual.com.au',
    'me bank': 'mebank.com.au',
    'me bank me go': 'mebank.com.au',
    'me go': 'mebank.com.au',
    'mecu': 'bankaust.com.au',
    'move bank': 'movebank.com.au',
    'mystate bank': 'mystate.com.au',
    'national australia bank': 'nab.com.au',
    'newcastle permanent': 'newcastlepermanent.com.au',
    'newcastle permanent building society': 'newcastlepermanent.com.au',
    'paypal australia': 'paypal.com',
    'people first bank': 'peoplefirstbank.com.au',
    'pepper money': 'peppermoney.com.au',
    'police bank': 'policebank.com.au',
    'qudos bank': 'qudosbank.com.au',
    'racq bank': 'racq.com.au',
    'rsl money': 'rslmoney.com.au',
    'solo by myob': 'myob.com',
    'south west credit union': 'swcu.com.au',
    'southern cross credit union': 'sccu.com.au',
    'st. george bank': 'stgeorge.com.au',
    'suncorp bank': 'suncorpbank.com.au',
    'the capricornian': 'capricornian.com.au',
    'traditional credit union': 'tcu.com.au',
    'transport mutual credit union': 'tmcu.com.au',
    'tyro': 'tyro.com',
    'tyro banking': 'tyro.com',
    'tyro payments': 'tyro.com',
    'ubank': 'ubank.com.au',
    'unibank': 'unibank.com.au',
    'unloan': 'unloan.com.au',
    'up': 'up.com.au',
    'victoria teachers mutual bank': 'victeach.com.au',
    'virgin money': 'virginmoney.com.au',
    'westpac banking corporation': 'westpac.com.au',
  };

  /** Official exact-brand images for providers where group logos are misleading. */
  const OFFICIAL_LOGO_URLS = {
    'anz plus': [
      'https://www.anz.com.au/content/dam/anzplus/logos/anz-plus-logo.svg',
      'https://www.anz.com.au/etc.clientlibs/anzplus/web2/clientlibs/clientlib-anzplus-components/resources/icon-192x192.png',
    ],
    'arab bank australia': [
      'https://www.arabbank.com.au/themes/arabbank/images/abal-logo.svg',
    ],
    'banksa': [
      'https://www.banksa.com.au/etc/designs/sbgrp/bsa/clientlibs/css/favicons/apple-touch-icon-152x152.png',
      'https://www.banksa.com.au/etc/designs/sbgrp/bsa/clientlibs/css/favicons/favicon-32x32.png',
    ],
    'bank of china': [
      'https://www.bankofchina.com/images/boc2013_ovs_ft_logo.png',
    ],
    'bnk bank': [
      'https://www.bnk.com.au/wp-content/uploads/2025/02/Logo.svg',
      'https://www.bnk.com.au/wp-content/uploads/2025/02/cropped-Logo1-192x192.png',
    ],
    'boq specialist': [
      'https://www.boqspecialist.com.au/favicon.ico',
    ],
    'family first': [
      'https://familyfirst.com.au/wp-content/themes/familyfirst/images/logo.png',
      'https://familyfirst.com.au/wp-content/uploads/2019/11/cropped-Family-First-Favicon-192x192.png',
    ],
    'maitland mutual': [
      'https://www.themutual.com.au/favicon.ico',
    ],
    'traditional credit union': [
      'https://tcu.com.au/wp-content/uploads/2019/02/TCU-Logo-Transparent-e1549607267783.png',
      'https://tcu.com.au/wp-content/uploads/2019/01/cropped-TCU-Logo-1-e1548750375490-1-192x192.png',
    ],
    'unloan': [
      'https://cdn.prod.website-files.com/6213e151e80699c74710709e/67c11fa0f20ffc6e0d1d2e5e_unloan-icon-256x256.png',
      'https://cdn.prod.website-files.com/6213e151e80699c74710709e/67c11f9ab4f8226908b6dc20_unloan-icon-32x32.png',
    ],
  };

  /** Clearbit Logo API - used after official-domain favicons. */
  function clearbitUrl(domain) {
    const host = domainHost(domain);
    return host ? 'https://logo.clearbit.com/' + host + '?size=64' : '';
  }

  function canonicalProviderKey(label) {
    return String(lookupProvider(label) || '').trim().toLowerCase();
  }

  function providerDomain(label) {
    const raw = String(label || '').trim().toLowerCase();
    const canonical = canonicalProviderKey(label);
    return BANK_DOMAINS[raw] || BANK_DOMAINS[canonical] || '';
  }

  function domainUrl(domain) {
    const value = String(domain || '').trim();
    if (!value) return '';
    return /^https?:\/\//i.test(value) ? value : 'https://' + value;
  }

  function domainHost(domain) {
    const value = domainUrl(domain);
    if (!value) return '';
    try {
      return new URL(value).hostname.replace(/^www\./i, '');
    } catch (_e) {
      return String(domain || '').replace(/^https?:\/\//i, '').split('/')[0].replace(/^www\./i, '');
    }
  }

  function googleFaviconUrl(domain) {
    const value = domainUrl(domain);
    return value ? 'https://www.google.com/s2/favicons?domain_url=' + encodeURIComponent(value) + '&sz=64' : '';
  }

  function rootFaviconUrl(domain) {
    const value = domainUrl(domain);
    if (!value) return '';
    try {
      const url = new URL(value);
      return url.origin + '/favicon.ico';
    } catch (_e) {
      return '';
    }
  }

  function pushUnique(out, seen, value) {
    if (!value || seen.has(value)) return;
    seen.add(value);
    out.push(value);
  }

  function exactOfficialLogoUrlsForProvider(label) {
    const raw = String(label || '').trim().toLowerCase();
    const canonical = canonicalProviderKey(label);
    const out = [];
    const seen = new Set();
    (OFFICIAL_LOGO_URLS[raw] || []).forEach((value) => pushUnique(out, seen, value));
    (OFFICIAL_LOGO_URLS[canonical] || []).forEach((value) => pushUnique(out, seen, value));
    return out;
  }

  function officialLogoUrlsForProvider(label) {
    const out = [];
    const seen = new Set();
    exactOfficialLogoUrlsForProvider(label).forEach((value) => pushUnique(out, seen, value));
    const domain = providerDomain(label);
    pushUnique(out, seen, googleFaviconUrl(domain));
    pushUnique(out, seen, rootFaviconUrl(domain));
    pushUnique(out, seen, clearbitUrl(domain));
    return out;
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

  /** True when same-origin /assets/banks/ is often incomplete: try CDN before local slugs. */
  function preferBankCdnFirst() {
    try {
      const h = String(window.location.hostname || '').trim().toLowerCase();
      if (!h || h === '127.0.0.1' || h === 'localhost' || h === '[::1]') return true;
      // Pi / LAN / Tailscale (100.64.0.0/10): mirror may lack full site/assets/banks set.
      if (/^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(h)) return true;
      if (/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h)) return true;
      if (h.endsWith('.local')) return true;
      return false;
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

  /** url -> 'ok' | 'fail' | Promise — skip known-bad URLs; coalesce in-flight loads. */
  const LOGO_LOAD_CACHE = new Map();
  const LOGO_LOAD_CACHE_MAX = 512;

  function pruneLogoLoadCacheIfNeeded() {
    if (LOGO_LOAD_CACHE.size <= LOGO_LOAD_CACHE_MAX) return;
    const drop = LOGO_LOAD_CACHE.size - Math.floor(LOGO_LOAD_CACHE_MAX / 2);
    let n = 0;
    for (const key of LOGO_LOAD_CACHE.keys()) {
      if (n >= drop) break;
      LOGO_LOAD_CACHE.delete(key);
      n += 1;
    }
  }

  function rememberLogoUrlResult(url, ok) {
    const src = String(url || '').trim();
    if (!src) return;
    LOGO_LOAD_CACHE.set(src, ok ? 'ok' : 'fail');
    pruneLogoLoadCacheIfNeeded();
  }

  function isLogoUrlKnownBad(url) {
    return LOGO_LOAD_CACHE.get(String(url || '').trim()) === 'fail';
  }

  /**
   * Fast paths first (exact brand map, meta/CDN, slug pack), slow fallbacks last (favicons, Clearbit).
   */
  function buildLogoUrlList(metaIcon, slugBasenames, provider) {
    const urls = [];
    const seen = new Set();
    const pushUrl = (u) => {
      const src = String(u || '').trim();
      if (!src || seen.has(src) || isLogoUrlKnownBad(src)) return;
      seen.add(src);
      urls.push(src);
    };
    exactOfficialLogoUrlsForProvider(provider).forEach(pushUrl);
    const remoteFirst = preferBankCdnFirst();
    const icon = String(metaIcon || '').trim();
    if (remoteFirst && icon) {
      pushUrl(cdnTwinForLocalBankUrl(icon));
      pushUrl(icon);
    } else if (icon) {
      pushUrl(icon);
      pushUrl(cdnTwinForLocalBankUrl(icon));
    }
    logoUrlsFromSlugs(slugBasenames).forEach(pushUrl);
    officialLogoUrlsForProvider(provider).forEach(pushUrl);
    return urls;
  }

  function preloadLogoUrl(url) {
    const src = String(url || '').trim();
    if (!src) return Promise.resolve(false);
    const cached = LOGO_LOAD_CACHE.get(src);
    if (cached === 'ok') return Promise.resolve(true);
    if (cached === 'fail') return Promise.resolve(false);
    if (cached && typeof cached.then === 'function') return cached;

    const p = new Promise((resolve) => {
      const img = new Image();
      img.decoding = 'async';
      img.onload = () => {
        rememberLogoUrlResult(src, true);
        resolve(true);
      };
      img.onerror = () => {
        rememberLogoUrlResult(src, false);
        resolve(false);
      };
      img.src = src;
    });
    LOGO_LOAD_CACHE.set(src, p);
    return p;
  }

  /**
   * Warm logo URLs for a provider rail (parallel per provider, sequential fallbacks per provider).
   * @param {string[]} providers
   * @param {Record<string, object>} [sampleByProvider]
   */
  function preloadRailProviders(providers, sampleByProvider) {
    const brand = window.AR && window.AR.bankBrand;
    if (brand && brand.preloadIcons) brand.preloadIcons(providers);
    const list = Array.isArray(providers) ? providers : [];
    return Promise.all(
      list.map(async (provider) => {
        const meta = providerMeta(provider);
        let slugBasenames = orderedSlugBasenames(
          provider,
          sampleByProvider && sampleByProvider[provider],
          [],
        );
        const iconSlug = slugFromBankIconUrl(meta.icon || '');
        if (iconSlug) {
          const seen = new Set(slugBasenames);
          if (!seen.has(iconSlug)) slugBasenames = [iconSlug].concat(slugBasenames);
        }
        const urls = buildLogoUrlList(meta.icon || '', slugBasenames, provider);
        for (let i = 0; i < urls.length; i += 1) {
          if (LOGO_LOAD_CACHE.get(urls[i]) === 'ok') return;
          const ok = await preloadLogoUrl(urls[i]);
          if (ok) return;
        }
      }),
    );
  }

  function mountLogoIntoWrap(logoWrap, metaIcon, slugBasenames, meta, provider, mountOpts) {
    while (logoWrap.firstChild) logoWrap.removeChild(logoWrap.firstChild);
    const urls = buildLogoUrlList(metaIcon, slugBasenames, provider);

    if (!urls.length) {
      child(logoWrap, 'span', 'bank-badge-fallback local-bank-fallback-neutral', abbrevFallback(meta, provider));
      return;
    }

    const fallbackEl = child(
      logoWrap,
      'span',
      'bank-badge-fallback local-bank-fallback-neutral',
      abbrevFallback(meta, provider),
    );
    const img = document.createElement('img');
    img.className = 'bank-badge-logo is-logo-loading';
    img.alt = '';
    img.width = 32;
    img.height = 32;
    img.loading = 'eager';
    img.decoding = 'async';
    img.draggable = false;
    const priority = mountOpts && mountOpts.logoFetchPriority;
    if (priority === 'high' || priority === 'low') img.fetchPriority = priority;
    logoWrap.appendChild(img);

    const finishNeutral = () => {
      img.onload = null;
      img.onerror = null;
      if (img.parentNode === logoWrap) img.remove();
      if (!logoWrap.contains(fallbackEl)) {
        child(logoWrap, 'span', 'bank-badge-fallback local-bank-fallback-neutral', abbrevFallback(meta, provider));
      }
    };

    function revealLoadedLogo(url) {
      rememberLogoUrlResult(url, true);
      img.onload = null;
      img.onerror = null;
      img.classList.remove('is-logo-loading');
      if (fallbackEl.parentNode === logoWrap) fallbackEl.remove();
    }

    function attempt(index) {
      if (index >= urls.length) {
        finishNeutral();
        return;
      }
      const url = urls[index];
      if (isLogoUrlKnownBad(url)) {
        attempt(index + 1);
        return;
      }
      img.onload = () => revealLoadedLogo(url);
      img.onerror = () => {
        rememberLogoUrlResult(url, false);
        attempt(index + 1);
      };
      img.src = url;
      if (LOGO_LOAD_CACHE.get(url) === 'ok' && img.complete && img.naturalWidth > 0) {
        revealLoadedLogo(url);
      }
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
    mountLogoIntoWrap(logo, meta.icon || '', slugBasenames, meta, provider, {
      logoFetchPriority: opts.logoFetchPriority,
    });
    const copy = child(badge, 'span', 'bank-badge-copy');
    child(copy, 'span', 'bank-badge-label', meta.short || provider || '-');
    if (showName) child(copy, 'span', 'bank-badge-sub', provider || meta.name);
    return badge;
  }

  window.LocalCdrBrand = {
    appendProviderBadge,
    buildLogoUrlList,
    iconSlugCandidates,
    iconSlugCandidatesForRate,
    lookupProvider,
    logoUrlsFromSlugs,
    orderedSlugBasenames,
    officialLogoUrlsForProvider,
    preloadRailProviders,
    providerDomain,
    providerMeta,
  };
})();
