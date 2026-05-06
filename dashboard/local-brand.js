(function () {
  'use strict';

  function child(parent, tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text != null) element.textContent = String(text);
    parent.appendChild(element);
    return element;
  }

  function lookupProvider(value) {
    const raw = String(value || '').toLowerCase();
    if (raw.includes('amp')) return 'amp bank';
    if (raw.includes('anz')) return 'anz';
    if (raw.includes('commonwealth') || raw.includes('commbank')) return 'commonwealth bank of australia';
    if (raw.includes('national australia') || raw.includes('nab')) return 'national australia bank';
    if (raw.includes('westpac')) return 'westpac banking corporation';
    if (raw.includes('macquarie')) return 'macquarie bank';
    if (raw.includes('bankwest')) return 'bankwest';
    if (raw.includes('ing')) return 'ing';
    if (raw.includes('hsbc')) return 'hsbc australia';
    if (raw.includes('ubank')) return 'ubank';
    if (raw.includes('suncorp')) return 'suncorp bank';
    if (raw.includes('st george') || raw.includes('st. george')) return 'st. george bank';
    if (raw.includes('bendigo')) return 'bendigo and adelaide bank';
    if (raw.includes('queensland') || raw.includes('boq')) return 'bank of queensland';
    if (raw.includes('melbourne')) return 'bank of melbourne';
    return value;
  }

  function providerMeta(value) {
    const brand = window.AR && window.AR.bankBrand;
    return brand && brand.getMeta ? brand.getMeta(lookupProvider(value)) : { name: value || 'Provider', short: value || '-', icon: '' };
  }

  function appendProviderBadge(parent, provider, showName) {
    const meta = providerMeta(provider);
    const badge = child(parent, 'span', 'bank-badge local-bank-badge');
    badge.title = provider || meta.name;
    const logo = child(badge, 'span', 'bank-badge-logo-wrap');
    logo.setAttribute('aria-hidden', 'true');
    if (meta.icon) {
      const img = child(logo, 'img', 'bank-badge-logo');
      img.src = meta.icon;
      img.alt = '';
      img.width = 32;
      img.height = 32;
      img.loading = 'lazy';
      img.draggable = false;
    } else {
      child(logo, 'span', 'bank-badge-fallback', (meta.short || '?').charAt(0));
    }
    const copy = child(badge, 'span', 'bank-badge-copy');
    child(copy, 'span', 'bank-badge-label', meta.short || provider || '-');
    if (showName) child(copy, 'span', 'bank-badge-sub', provider || meta.name);
    return badge;
  }

  window.LocalCdrBrand = { appendProviderBadge, providerMeta };
})();
