import { utf8ToBytes } from '@noble/hashes/utils';
/** Retained adopted JSON plus exact lazy decoded text; producer separately checks original snapshot bytes. */
export function mortgageSnapshotBudget(core: unknown, details: unknown) {
 let remaining = 24 * 1024 * 1024;
 function consume(text: string) {
  if (text.length > remaining) throw new Error('Mortgage adopted snapshot exceeds 24 MiB');
  remaining -= utf8ToBytes(text).length;
  if (remaining < 0) throw new Error('Mortgage adopted snapshot exceeds 24 MiB');
 }
 consume(JSON.stringify(core)); consume(JSON.stringify(details));
 return { consume, get remaining() { return remaining; } };
}
