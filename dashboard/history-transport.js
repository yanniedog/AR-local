(function (root) {
  'use strict';
  const FORMAT = 'ar-dashboard-history-dictionary-v1';
  const variableFields = ['run_date', 'carry_forward'];
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  function invalid() { throw new Error('Invalid or oversized dashboard history transport'); }
  function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
  function decode(payload, expectedSection) {
    if (!object(payload) || payload.format !== FORMAT || own(payload, 'rates')) invalid();
    if (!['Mortgage', 'Savings', 'TD'].includes(payload.section)
        || expectedSection !== undefined && payload.section !== expectedSection) invalid();
    const dates = payload.run_dates;
    if (!Array.isArray(dates) || dates.some((day, index) => typeof day !== 'string'
        || !/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(Date.parse(day))
        || new Date(day).toISOString().slice(0,10) !== day || index > 0 && day <= dates[index-1])) invalid();
    const knownDates = new Set(dates);
    if (!Number.isSafeInteger(payload.carry_forward_count) || payload.carry_forward_count < 0) invalid();
    const { columns, values, templates, observations, row_count: count } = payload;
    if (!Array.isArray(columns) || columns.length > 64 || new Set(columns).size !== columns.length
        || columns.some(key => typeof key !== 'string' || !key.length || key.length > 128 || variableFields.includes(key))) invalid();
    if (!Array.isArray(values) || values.length > 300000 || values.some(value =>
      value !== null && !['string', 'boolean', 'number'].includes(typeof value)
      || typeof value === 'number' && !Number.isFinite(value))) invalid();
    if (!Array.isArray(templates) || templates.length > 100000 || !Array.isArray(observations)
        || observations.length > 1000000 || !Number.isSafeInteger(count) || count !== observations.length) invalid();
    const validIndex = index => Number.isSafeInteger(index) && index >= -1 && index < values.length;
    const decodedTemplates = templates.map(template => {
      if (!Array.isArray(template) || template.length !== columns.length || !template.every(validIndex)) invalid();
      return Object.fromEntries(columns.flatMap((key, index) => template[index] === -1 ? [] : [[key, values[template[index]]]]));
    });
    let carried = 0;
    const rates = observations.map(observation => {
      if (!Array.isArray(observation) || observation.length !== 3 || !Number.isSafeInteger(observation[0])
          || observation[0] < 0 || observation[0] >= decodedTemplates.length
          || !validIndex(observation[1]) || !validIndex(observation[2])
          || observation[1] === -1 || !knownDates.has(values[observation[1]])) invalid();
      const row = { ...decodedTemplates[observation[0]] };
      variableFields.forEach((key, index) => { if (observation[index + 1] !== -1) row[key] = values[observation[index + 1]]; });
      if (row.carry_forward === '1') carried += 1;
      return row;
    });
    if (carried !== payload.carry_forward_count) invalid();
    const metadata = Object.fromEntries(Object.entries(payload).filter(([key]) =>
      !['format', 'columns', 'values', 'templates', 'observations', 'row_count'].includes(key)));
    return { ...metadata, rates };
  }
  const api = { decode };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.LocalCdrHistoryTransport = api;
})(typeof window === 'object' ? window : globalThis);
