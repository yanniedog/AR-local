(function () {
    'use strict';
    window.AR = window.AR || {};

    function esc(value) {
        var raw = window._arEsc;
        return typeof raw === 'function'
            ? raw(value)
            : String(value == null ? '' : value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
    }

    var BRAND_MAP = {
        // Big logo-pack brands (CDN-backed icons)
        'amp bank': { short: 'AMP', icon: '/assets/banks/amp-bank.png', aliases: ['amp', 'amp - my amp'] },
        'amp bank go': { short: 'AMP Go', icon: '/assets/banks/amp-bank.png', aliases: ['amp go'] },
        'anz': { short: 'ANZ', icon: '/assets/banks/anz.png', aliases: ['australia and new zealand'] },
        'anz plus': { short: 'ANZ+', icon: '', aliases: [] },
        'bank of melbourne': { short: 'BoM', icon: '/assets/banks/bank-of-melbourne.png', aliases: ['bom'] },
        'bank of queensland': { short: 'BOQ', icon: '/assets/banks/bank-of-queensland.png', aliases: ['boq'] },
        'boq specialist': { short: 'BOQS', icon: '', aliases: [] },
        'bankwest': { short: 'BW', icon: '/assets/banks/bankwest.png', aliases: ['bw'] },
        'bendigo and adelaide bank': { short: 'Bendigo', icon: '/assets/banks/bendigo-and-adelaide-bank.png', aliases: ['bendigo', 'bendigo bank'] },
        'commonwealth bank of australia': { short: 'CBA', icon: '/assets/banks/commonwealth-bank-of-australia.png', aliases: ['commonwealth bank', 'commbank'] },
        'unloan': { short: 'Unloan', icon: '', aliases: [] },
        'great southern bank': { short: 'GSB', icon: '/assets/banks/great-southern-bank.png', aliases: ['great southern'] },
        'great southern bank business+': { short: 'GSB+', icon: '/assets/banks/great-southern-bank.png', aliases: ['gsb business'] },
        'hsbc australia': { short: 'HSBC', icon: '/assets/banks/hsbc-australia.png', aliases: ['hsbc'] },
        'hsbc wholesale': { short: 'HSBCw', icon: '/assets/banks/hsbc-australia.png', aliases: ['hsbc wholesale banking'] },
        'ing': { short: 'ING', icon: '/assets/banks/ing.png', aliases: [] },
        'macquarie bank': { short: 'Macq', icon: '/assets/banks/macquarie-bank.png', aliases: ['macquarie'] },
        'national australia bank': { short: 'NAB', icon: '/assets/banks/national-australia-bank.png', aliases: ['nab'] },
        'st. george bank': { short: 'StG', icon: '/assets/banks/st-george-bank.png', aliases: ['st george', 'stgeorge'] },
        'banksa': { short: 'BSA', icon: '', aliases: ['bank sa'] },
        'suncorp bank': { short: 'Sun', icon: '/assets/banks/suncorp-bank.png', aliases: ['suncorp'] },
        'ubank': { short: 'ubank', icon: '/assets/banks/ubank.png', aliases: ['u bank', '86 400', '86400'] },
        'westpac banking corporation': { short: 'WBC', icon: '/assets/banks/westpac-banking-corporation.png', aliases: ['westpac', 'wbc'] },
        // Smaller ADIs / mutuals (no logo pack — rely on slug + clearbit fallback)
        'alex bank': { short: 'Alex', icon: '', aliases: ['alex.bank'] },
        'arab bank australia': { short: 'Arab', icon: '', aliases: ['arab bank'] },
        'australian military bank': { short: 'AMB', icon: '', aliases: [] },
        'auswide bank': { short: 'Auswide', icon: '', aliases: [] },
        'bnk bank': { short: 'BNK', icon: '', aliases: ['goldfields money'] },
        'bank australia': { short: 'BAus', icon: '', aliases: ['mecu'] },
        'bank first': { short: 'BFirst', icon: '', aliases: [] },
        'bank of china': { short: 'BoC', icon: '', aliases: [] },
        'bank of sydney': { short: 'BoSyd', icon: '', aliases: [] },
        'bank of us': { short: 'BoUs', icon: '', aliases: [] },
        'border bank': { short: 'Border', icon: '', aliases: [] },
        'cairns bank': { short: 'Cairns', icon: '', aliases: [] },
        'credit union sa': { short: 'CUSA', icon: '', aliases: [] },
        'darling downs bank': { short: 'DDB', icon: '', aliases: [] },
        'defence bank': { short: 'Def', icon: '', aliases: [] },
        'family first': { short: 'FFirst', icon: '', aliases: [] },
        'greater bank': { short: 'Greater', icon: '', aliases: [] },
        'heartland': { short: 'Heart', icon: '', aliases: ['heartland australia'] },
        'hume bank': { short: 'Hume', icon: '', aliases: [] },
        'imb bank': { short: 'IMB', icon: '', aliases: [] },
        'in1bank': { short: 'in1', icon: '', aliases: [] },
        'judo bank': { short: 'Judo', icon: '', aliases: [] },
        'liberty financial': { short: 'Lib', icon: '', aliases: ['liberty'] },
        'maitland mutual': { short: 'MML', icon: '', aliases: [] },
        'me bank': { short: 'ME', icon: '', aliases: [] },
        'me bank me go': { short: 'ME Go', icon: '', aliases: ['me go'] },
        'mystate bank': { short: 'MyState', icon: '', aliases: [] },
        'newcastle permanent': { short: 'NPBS', icon: '', aliases: ['newcastle'] },
        'paypal australia': { short: 'PayPal', icon: '', aliases: ['paypal'] },
        'police bank': { short: 'Police', icon: '', aliases: [] },
        'qudos bank': { short: 'Qudos', icon: '', aliases: [] },
        'racq bank': { short: 'RACQ', icon: '', aliases: [] },
        'rsl money': { short: 'RSL', icon: '', aliases: [] },
        'solo by myob': { short: 'Solo', icon: '', aliases: ['solo', 'myob'] },
        'southern cross credit union': { short: 'SCCU', icon: '', aliases: [] },
        'the capricornian': { short: 'Capric', icon: '', aliases: ['capricornian'] },
        'traditional credit union': { short: 'TCU', icon: '', aliases: [] },
        'tyro': { short: 'Tyro', icon: '', aliases: ['tyro banking', 'tyro payments'] },
        'up': { short: 'Up', icon: '', aliases: ['up bank'] },
        'virgin money': { short: 'Virgin', icon: '', aliases: ['virgin'] },
    };
    var PRELOADED_ICONS = {};

    function normalize(value) {
        return String(value == null ? '' : value)
            .trim()
            .toLowerCase()
            .replace(/\s+/g, ' ');
    }

    function normalizeSearch(value) {
        return normalize(value).replace(/[^a-z0-9]+/g, ' ').trim();
    }

    function buildFallbackShort(value) {
        var raw = String(value == null ? '' : value).trim();
        if (!raw) return '-';
        var words = raw.replace(/[^A-Za-z0-9 ]+/g, ' ').split(/\s+/).filter(Boolean);
        if (!words.length) return raw.slice(0, 6);
        if (words.length === 1) return words[0].slice(0, 8);
        return words.slice(0, 3).map(function (part) { return part.charAt(0).toUpperCase(); }).join('');
    }

    function getMeta(value) {
        var name = String(value == null ? '' : value).trim();
        var normalized = normalize(name);
        var base = BRAND_MAP[normalized] || {};
        var short = base.short || buildFallbackShort(name);
        var aliases = Array.isArray(base.aliases) ? base.aliases.slice() : [];
        return {
            name: name || 'Unknown bank',
            normalized: normalized,
            short: short,
            icon: base.icon || '',
            search: normalizeSearch([name, short].concat(aliases).join(' ')),
        };
    }

    function shortLabel(value) {
        return getMeta(value).short;
    }

    function fullLabel(value) {
        return getMeta(value).name;
    }

    function tooltipLabel(value, metaIn) {
        var raw = String(value == null ? '' : value).trim();
        var meta = metaIn || getMeta(value);
        var displayName = raw || meta.name;
        var abbrev = String(meta.short || '').trim();
        if (!abbrev || abbrev === '-' || abbrev.toLowerCase() === displayName.toLowerCase()) {
            return displayName;
        }
        return displayName + ' (' + abbrev + ')';
    }

    function matchesQuery(value, query) {
        var needle = normalizeSearch(query);
        if (!needle) return true;
        return getMeta(value).search.indexOf(needle) >= 0;
    }

    function preloadIcon(icon) {
        var src = String(icon || '').trim();
        if (!src || PRELOADED_ICONS[src]) return;
        var img = new Image();
        img.decoding = 'sync';
        img.src = src;
        PRELOADED_ICONS[src] = img;
    }

    function preloadIcons(values) {
        (Array.isArray(values) ? values : []).forEach(function (value) {
            var meta = getMeta(value);
            preloadIcon(meta.icon);
        });
    }

    function badge(value, options) {
        var meta = getMeta(value);
        var opts = options || {};
        var classes = ['bank-badge'];
        if (opts.compact) classes.push('is-compact');
        if (opts.className) classes.push(String(opts.className));

        return '' +
            '<span class="' + classes.join(' ') + '" title="' + esc(tooltipLabel(value, meta)) + '">' +
                '<span class="bank-badge-logo-wrap" aria-hidden="true">' +
                    (meta.icon
                        ? '<img class="bank-badge-logo" src="' + esc(meta.icon) + '" alt="" width="32" height="32" loading="eager" fetchpriority="low" draggable="false">'
                        : '<span class="bank-badge-fallback">' + esc(meta.short.charAt(0) || '?') + '</span>') +
                '</span>' +
                '<span class="bank-badge-copy">' +
                    '<span class="bank-badge-label">' + esc(meta.short) + '</span>' +
                    (opts.showName ? '<span class="bank-badge-sub">' + esc(meta.name) + '</span>' : '') +
                '</span>' +
            '</span>';
    }

    window.AR.bankBrand = {
        badge: badge,
        fullLabel: fullLabel,
        getMeta: getMeta,
        matchesQuery: matchesQuery,
        preloadIcons: preloadIcons,
        shortLabel: shortLabel,
        tooltipLabel: tooltipLabel,
    };
})();
