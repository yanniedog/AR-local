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
        'amp bank': { short: 'AMP', icon: '/assets/banks/amp-bank.png', aliases: ['amp'] },
        'anz': { short: 'ANZ', icon: '/assets/banks/anz.png', aliases: ['australia and new zealand'] },
        'bank of melbourne': { short: 'BoM', icon: '/assets/banks/bank-of-melbourne.png', aliases: ['bom'] },
        'bank of queensland': { short: 'BOQ', icon: '/assets/banks/bank-of-queensland.png', aliases: ['boq'] },
        'bankwest': { short: 'Bankwest', icon: '/assets/banks/bankwest.png', aliases: ['bw'] },
        'bendigo and adelaide bank': { short: 'Bendigo', icon: '/assets/banks/bendigo-and-adelaide-bank.png', aliases: ['bendigo'] },
        'commonwealth bank of australia': { short: 'CBA', icon: '/assets/banks/commonwealth-bank-of-australia.png', aliases: ['commonwealth bank', 'commbank'] },
        'great southern bank': { short: 'GSB', icon: '/assets/banks/great-southern-bank.png', aliases: ['great southern'] },
        'hsbc australia': { short: 'HSBC', icon: '/assets/banks/hsbc-australia.png', aliases: ['hsbc'] },
        'ing': { short: 'ING', icon: '/assets/banks/ing.png', aliases: [] },
        'macquarie bank': { short: 'Macq', icon: '/assets/banks/macquarie-bank.png', aliases: ['macquarie'] },
        'national australia bank': { short: 'NAB', icon: '/assets/banks/national-australia-bank.png', aliases: ['nab'] },
        'st. george bank': { short: 'StG', icon: '/assets/banks/st-george-bank.png', aliases: ['st george'] },
        'suncorp bank': { short: 'Suncorp', icon: '/assets/banks/suncorp-bank.png', aliases: ['sun'] },
        'ubank': { short: 'ubank', icon: '/assets/banks/ubank.png', aliases: ['u bank'] },
        'westpac banking corporation': { short: 'Westpac', icon: '/assets/banks/westpac-banking-corporation.png', aliases: ['westpac', 'wbc'] },
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
            '<span class="' + classes.join(' ') + '" title="' + esc(meta.name) + '">' +
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
    };
})();
