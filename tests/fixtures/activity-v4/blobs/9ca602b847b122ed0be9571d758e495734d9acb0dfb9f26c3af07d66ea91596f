import type { Rounding } from './types';

const ZERO = BigInt(0);
const ONE = BigInt(1);
const TEN = BigInt(10);
function abs(value: bigint): bigint { return value < ZERO ? -value : value; }
function gcd(a: bigint, b: bigint): bigint {
  while (b !== ZERO) { const next = a % b; a = b; b = next; }
  return abs(a);
}
function power(scale: number): bigint {
  if (!Number.isInteger(scale) || scale < 0 || scale > 24) throw new Error('decimal_scale_unsupported');
  return TEN ** BigInt(scale);
}

/** Exact reduced rationals avoid rounding daily interest prematurely. No BigInt crosses JSON. */
export class Decimal {
  readonly n: bigint;
  readonly d: bigint;
  constructor(n: bigint, d = ONE) {
    if (d === ZERO) throw new Error('division_by_zero');
    if (d < ZERO) { n = -n; d = -d; }
    const divisor = gcd(n, d);
    this.n = n / divisor; this.d = d / divisor;
  }
  static parse(value: string): Decimal {
    if (typeof value !== 'string' || value.length > 72 || !/^-?(0|[1-9]\d*)(\.\d{1,24})?$/.test(value)) {
      throw new Error('invalid_decimal');
    }
    const [whole, fraction = ''] = value.split('.');
    return new Decimal(BigInt(whole + fraction), power(fraction.length));
  }
  add(other: Decimal): Decimal { return new Decimal(this.n * other.d + other.n * this.d, this.d * other.d); }
  sub(other: Decimal): Decimal { return new Decimal(this.n * other.d - other.n * this.d, this.d * other.d); }
  mul(other: Decimal): Decimal { return new Decimal(this.n * other.n, this.d * other.d); }
  div(other: Decimal): Decimal { return new Decimal(this.n * other.d, this.d * other.n); }
  compare(other: Decimal): number {
    const value = this.n * other.d - other.n * this.d;
    return value < ZERO ? -1 : value > ZERO ? 1 : 0;
  }
  rounded(scale: number, mode: Rounding): Decimal {
    if (!['half_up', 'half_even', 'toward_zero'].includes(mode)) throw new Error('rounding_unsupported');
    const factor = power(scale), value = this.n * factor;
    let integral = value / this.d;
    const remainder = abs(value % this.d);
    const twice = remainder * BigInt(2);
    const increment = mode === 'half_up' ? twice >= this.d :
      mode === 'half_even' && (twice > this.d || (twice === this.d && abs(integral) % BigInt(2) !== ZERO));
    if (increment && remainder !== ZERO) integral += value < ZERO ? -ONE : ONE;
    return new Decimal(integral, factor);
  }
  fixed(scale = 2, mode: Rounding = 'half_up'): string {
    const rounded = this.rounded(scale, mode), factor = power(scale);
    const integer = rounded.n * factor / rounded.d;
    const digits = abs(integer).toString().padStart(scale + 1, '0');
    return (integer < ZERO ? '-' : '') + (scale ? `${digits.slice(0, -scale)}.${digits.slice(-scale)}` : digits);
  }
}
export const decimalZero = (): Decimal => Decimal.parse('0');
