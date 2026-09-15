import { dayNumber } from '../../lib/productTermsEngine/calendar';
import { canonical } from '../../lib/productTermsEngine/validation';
import schemas, { mortgageSchemas } from './runtimeSchemas';
const external: Record<string, any> = Object.fromEntries(Object.values({ ...schemas, ...Object.fromEntries(Object.entries(mortgageSchemas).map(([k,v]) => [`mortgage_${k}`,v])) }).map(schema => [schema.$id, schema]));
type Schema = Record<string, any>;
/** Closed interpreter for checked-in frozen schemas only. No remote schema adoption. */
export function assertMonetaryWire(value: unknown, kind: keyof typeof schemas) {
  return assertMonetarySchema(value, schemas[kind]);
}
export function assertMonetarySchema(value: unknown, schema: Schema) {
  let nodes = 0;
  function valid(v: any, s: Schema, document: Schema, depth: number): boolean {
    if (++nodes > 250000 || depth > 128) return false;
    if (s.$ref) {
      const [uri, fragment] = s.$ref.split('#');
      const root = uri ? external[uri] : document;
      if (!root || fragment && !fragment.startsWith('/')) return false;
      const target = fragment ? fragment.slice(1).split('/').reduce((o: Schema, key: string) => o?.[key], root) : root;
      return !!target && valid(v, target, root, depth + 1);
    }
    if (s.not && valid(v, s.not, document, depth + 1)) return false;
    if (s.allOf && !s.allOf.every((item: Schema) => valid(v, item, document, depth + 1))) return false;
    if (s.if) { const branch = valid(v, s.if, document, depth + 1) ? s.then : s.else; if (branch && !valid(v, branch, document, depth + 1)) return false; }
    if (s.oneOf && s.oneOf.filter((item: Schema) => valid(v, item, document, depth + 1)).length !== 1) return false;
    if (s.anyOf && !s.anyOf.some((item: Schema) => valid(v, item, document, depth + 1))) return false;
    if ('const' in s && v !== s.const || s.enum && !s.enum.includes(v)) return false;
    const type = v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v;
    if (s.type && !(Array.isArray(s.type) ? s.type : [s.type]).some((t: string) => t === type || t === 'integer' && Number.isSafeInteger(v))) return false;
    if (typeof v === 'number' && (!Number.isFinite(v) || s.minimum !== undefined && v < s.minimum || s.maximum !== undefined && v > s.maximum)) return false;
    if (typeof v === 'string') {
      const size = [...v].length;
      if (s.minLength !== undefined && size < s.minLength || s.maxLength !== undefined && size > s.maxLength || s.pattern && !new RegExp(s.pattern).test(v)) return false;
      if (s.format === 'date') { try { dayNumber(v); } catch { return false; } }
      if (s.format === 'date-time') {
        if (!/^\d{4}-\d{2}-\d{2}[Tt](?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(v) || !Number.isFinite(Date.parse(v))) return false;
        try { dayNumber(v.slice(0, 10)); } catch { return false; }
      }
    }
    if (Array.isArray(v)) {
      if (s.minItems !== undefined && v.length < s.minItems || s.maxItems !== undefined && v.length > s.maxItems || s.uniqueItems && new Set(v.map(item => canonical(item))).size !== v.length) return false;
      if (s.items && !v.every(item => valid(item, s.items, document, depth + 1))) return false;
    } else if (v && typeof v === 'object') {
      const keys = Object.keys(v);
      if (s.minProperties !== undefined && keys.length < s.minProperties || s.maxProperties !== undefined && keys.length > s.maxProperties || s.required?.some((key: string) => !Object.hasOwn(v, key))) return false;
      for (const key of keys) {
        if (s.propertyNames && !valid(key, s.propertyNames, document, depth + 1)) return false;
        if (s.properties && Object.hasOwn(s.properties, key)) { if (!valid(v[key], s.properties[key], document, depth + 1)) return false; }
        else if (s.additionalProperties === false) return false;
        else if (typeof s.additionalProperties === 'object' && !valid(v[key], s.additionalProperties, document, depth + 1)) return false;
      }
    }
    return true;
  }
  if (!valid(value, schema, schema, 0)) throw new Error('Monetary wire is invalid or unsupported');
}
