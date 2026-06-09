import {
  computeEtaSeconds,
  computePercent,
  computeTransferRate,
  fileNameFromUrl,
  formatEta,
  formatTransferRate,
  phaseLabel,
} from '../src/data/downloadProgress';

describe('downloadProgress', () => {
  it('extracts file name from release URL', () => {
    expect(
      fileNameFromUrl(
        'https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/core-2026-06-08-abc.gz',
      ),
    ).toBe('core-2026-06-08-abc.gz');
  });

  it('computes transfer rate from elapsed time', () => {
    const startedAt = 1_000;
    expect(computeTransferRate(10_240, startedAt, startedAt + 1_000)).toBeCloseTo(10_240);
  });

  it('formats KB/s and MB/s', () => {
    expect(formatTransferRate(512)).toBe('512 B/s');
    expect(formatTransferRate(2048)).toBe('2.0 KB/s');
    expect(formatTransferRate(1.5 * 1024 * 1024)).toBe('1.5 MB/s');
    expect(formatTransferRate(0)).toBe('—');
  });

  it('computes percent and ETA', () => {
    expect(computePercent(50, 200)).toBe(25);
    expect(computePercent(50, null)).toBeNull();
    expect(computeEtaSeconds(50, 200, 25)).toBe(6);
    expect(computeEtaSeconds(50, 200, 0)).toBeNull();
  });

  it('formats ETA strings', () => {
    expect(formatEta(0.4)).toBe('<1s');
    expect(formatEta(45)).toBe('45s');
    expect(formatEta(125)).toBe('2m 5s');
    expect(formatEta(null)).toBe('—');
  });

  it('labels processing phases', () => {
    expect(phaseLabel('verify')).toBe('verify sha256');
    expect(phaseLabel('inflate')).toBe('decompress gzip');
  });
});
