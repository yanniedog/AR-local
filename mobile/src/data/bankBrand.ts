import { BUNDLED_BANK_LOGOS } from './bankLogoAssets';

/** Mirrors dashboard `ar-bank-brand.js` icon paths and aliases. */
const CDN_BANK_BASE = 'https://australianrates.com/assets/banks/';

type BrandEntry = {
  short: string;
  icon?: string;
  aliases?: string[];
};

const BRAND_MAP: Record<string, BrandEntry> = {
  'amp bank': { short: 'AMP', icon: 'amp-bank.png', aliases: ['amp', 'amp - my amp'] },
  'amp bank go': { short: 'AMP Go', icon: 'amp-bank.png', aliases: ['amp go'] },
  anz: { short: 'ANZ', icon: 'anz.png', aliases: ['australia and new zealand'] },
  'anz plus': { short: 'ANZ+', aliases: [] },
  'bank of melbourne': { short: 'BoM', icon: 'bank-of-melbourne.png', aliases: ['bom'] },
  'bank of queensland': { short: 'BOQ', icon: 'bank-of-queensland.png', aliases: ['boq'] },
  'boq specialist': { short: 'BOQS', aliases: [] },
  bankwest: { short: 'BW', icon: 'bankwest.png', aliases: ['bw'] },
  'bendigo and adelaide bank': {
    short: 'Bendigo',
    icon: 'bendigo-and-adelaide-bank.png',
    aliases: ['bendigo', 'bendigo bank'],
  },
  'commonwealth bank of australia': {
    short: 'CBA',
    icon: 'commonwealth-bank-of-australia.png',
    aliases: ['commonwealth bank', 'commbank'],
  },
  unloan: { short: 'Unloan', aliases: [] },
  'great southern bank': {
    short: 'GSB',
    icon: 'great-southern-bank.png',
    aliases: ['great southern'],
  },
  'great southern bank business+': {
    short: 'GSB+',
    icon: 'great-southern-bank.png',
    aliases: ['gsb business'],
  },
  'hsbc australia': { short: 'HSBC', icon: 'hsbc-australia.png', aliases: ['hsbc'] },
  'hsbc wholesale': {
    short: 'HSBCw',
    icon: 'hsbc-australia.png',
    aliases: ['hsbc wholesale banking'],
  },
  ing: { short: 'ING', icon: 'ing.png', aliases: [] },
  'macquarie bank': { short: 'Macq', icon: 'macquarie-bank.png', aliases: ['macquarie'] },
  'national australia bank': {
    short: 'NAB',
    icon: 'national-australia-bank.png',
    aliases: ['nab'],
  },
  'st. george bank': {
    short: 'StG',
    icon: 'st-george-bank.png',
    aliases: ['st george', 'stgeorge'],
  },
  banksa: { short: 'BSA', aliases: ['bank sa'] },
  'suncorp bank': { short: 'Sun', icon: 'suncorp-bank.png', aliases: ['suncorp'] },
  ubank: { short: 'ubank', icon: 'ubank.png', aliases: ['u bank', '86 400', '86400'] },
  'westpac banking corporation': {
    short: 'WBC',
    icon: 'westpac-banking-corporation.png',
    aliases: ['westpac', 'wbc'],
  },
  'alex bank': { short: 'Alex', aliases: ['alex.bank'] },
  'arab bank australia': { short: 'Arab', aliases: ['arab bank'] },
  'australian military bank': { short: 'AMB', aliases: [] },
  'auswide bank': { short: 'Auswide', aliases: [] },
  'bnk bank': { short: 'BNK', aliases: ['goldfields money'] },
  'bank australia': { short: 'BAus', aliases: ['mecu'] },
  'bank first': { short: 'BFirst', aliases: [] },
  'bank of china': { short: 'BoC', aliases: [] },
  'bank of sydney': { short: 'BoSyd', aliases: [] },
  'bank of us': { short: 'BoUs', aliases: [] },
  'border bank': { short: 'Border', aliases: [] },
  'cairns bank': { short: 'Cairns', aliases: [] },
  'credit union sa': { short: 'CUSA', aliases: [] },
  'darling downs bank': { short: 'DDB', aliases: [] },
  'defence bank': { short: 'Def', aliases: [] },
  'family first': { short: 'FFirst', aliases: [] },
  'greater bank': { short: 'Greater', aliases: [] },
  heartland: { short: 'Heart', aliases: ['heartland australia'] },
  'hume bank': { short: 'Hume', aliases: [] },
  'imb bank': { short: 'IMB', aliases: [] },
  in1bank: { short: 'in1', aliases: [] },
  'judo bank': { short: 'Judo', aliases: [] },
  'liberty financial': { short: 'Lib', aliases: ['liberty'] },
  'maitland mutual': { short: 'MML', aliases: [] },
  'me bank': { short: 'ME', aliases: [] },
  'me bank me go': { short: 'ME Go', aliases: ['me go'] },
  'mystate bank': { short: 'MyState', aliases: [] },
  'newcastle permanent': { short: 'NPBS', aliases: ['newcastle'] },
  'police bank': { short: 'Police', aliases: [] },
  'qudos bank': { short: 'Qudos', aliases: [] },
  'racq bank': { short: 'RACQ', aliases: [] },
  'rsl money': { short: 'RSL', aliases: [] },
  'southern cross credit union': { short: 'SCCU', aliases: [] },
  'the capricornian': { short: 'Capric', aliases: ['capricornian'] },
  'traditional credit union': { short: 'TCU', aliases: [] },
  tyro: { short: 'Tyro', aliases: ['tyro banking', 'tyro payments'] },
  up: { short: 'Up', aliases: ['up bank'] },
  'virgin money': { short: 'Virgin', aliases: ['virgin'] },
};

const ALIAS_TO_KEY = new Map<string, string>();
for (const [key, entry] of Object.entries(BRAND_MAP)) {
  ALIAS_TO_KEY.set(normalize(key), key);
  for (const alias of entry.aliases ?? []) {
    ALIAS_TO_KEY.set(normalize(alias), key);
  }
}

function normalize(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ');
}

/** Align CDR provider labels with dashboard `local-brand.js` canonical keys. */
export function lookupProvider(value: string): string {
  const raw = normalize(value);
  if (/great southern bank business/i.test(raw)) return 'great southern bank business+';
  if (raw.includes('great southern')) return 'great southern bank';
  if (raw.includes('86400') || raw.includes('86 400')) return 'ubank';
  if (raw.includes('amp bank go') || raw === 'amp go') return 'amp bank go';
  if (raw.includes('amp')) return 'amp bank';
  if (raw.includes('anz plus')) return 'anz plus';
  if (raw.includes('anz')) return 'anz';
  if (raw.includes('unloan')) return 'unloan';
  if (raw.includes('commonwealth') || raw.includes('commbank') || raw === 'cba') {
    return 'commonwealth bank of australia';
  }
  if (raw.includes('national australia') || raw === 'nab' || raw.startsWith('nab ')) {
    return 'national australia bank';
  }
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
  if (raw.includes('police bank')) return 'police bank';
  if (raw.includes('qudos')) return 'qudos bank';
  if (raw.includes('racq')) return 'racq bank';
  if (raw.includes('rsl money')) return 'rsl money';
  if (raw.includes('southern cross credit')) return 'southern cross credit union';
  if (raw.includes('capricornian')) return 'the capricornian';
  if (raw.includes('traditional credit union')) return 'traditional credit union';
  if (raw.includes('tyro')) return 'tyro';
  if (raw === 'up' || raw === 'up bank') return 'up';
  if (raw.includes('virgin')) return 'virgin money';
  return value;
}

function resolveBrandKey(provider: string): string | null {
  const candidates = [normalize(provider), normalize(lookupProvider(provider))];
  for (const candidate of candidates) {
    const key = ALIAS_TO_KEY.get(candidate);
    if (key) return key;
  }
  return null;
}

export function resolveBrandShort(provider: string, payloadShort?: string): string {
  const fromPayload = String(payloadShort ?? '').trim();
  if (fromPayload) return fromPayload;
  const key = resolveBrandKey(provider);
  if (key) return BRAND_MAP[key]?.short ?? fromPayload;
  const words = provider.replace(/[^A-Za-z0-9 ]+/g, ' ').split(/\s+/).filter(Boolean);
  if (!words.length) return provider.slice(0, 6) || '-';
  if (words.length === 1) return words[0].slice(0, 8);
  return words
    .slice(0, 3)
    .map((part) => part.charAt(0).toUpperCase())
    .join('');
}

function slugFromIcon(icon: string): string {
  return icon.replace(/\.png$/i, '');
}

function pushUnique(out: Array<string | number>, seen: Set<string>, value: string | number) {
  const key = typeof value === 'number' ? `n:${value}` : value;
  if (seen.has(key)) return;
  seen.add(key);
  out.push(value);
}

function pushIconFile(out: Array<string | number>, seen: Set<string>, iconFile: string) {
  const slug = slugFromIcon(iconFile);
  const bundled = BUNDLED_BANK_LOGOS[slug];
  if (bundled != null) pushUnique(out, seen, bundled);
  pushUnique(out, seen, `${CDN_BANK_BASE}${iconFile}`);
}

/** Ordered logo sources: payload embed, bundled pack, then CDN twin. */
export function resolveBankLogoSources(provider: string, embeddedLogo?: string): Array<string | number> {
  const out: Array<string | number> = [];
  const seen = new Set<string>();
  const embedded = String(embeddedLogo ?? '').trim();
  if (embedded) pushUnique(out, seen, embedded);

  const key = resolveBrandKey(provider);
  const icon = key ? BRAND_MAP[key]?.icon : undefined;
  if (icon) {
    pushIconFile(out, seen, icon);
    return out;
  }

  const slug = slugify(lookupProvider(provider));
  if (slug) {
    const bundled = BUNDLED_BANK_LOGOS[slug];
    if (bundled != null) pushUnique(out, seen, bundled);
    pushUnique(out, seen, `${CDN_BANK_BASE}${slug}.png`);
  }
  return out;
}

function slugify(value: string): string {
  return normalize(value)
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
