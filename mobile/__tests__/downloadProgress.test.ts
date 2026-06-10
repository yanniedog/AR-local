import {
  buildPayloadProgressViewModel,
  computeEtaSeconds,
  computeOverallPercent,
  computePercent,
  computeTransferRate,
  fileNameFromUrl,
  formatEta,
  formatTransferRate,
  phaseLabel,
  type PayloadProgressSnapshot,
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

  it('computes overall percent across phases', () => {
    const downloadHalf: PayloadProgressSnapshot = {
      phase: 'download',
      fileName: 'core.gz',
      bytesReceived: 512,
      totalBytes: 1024,
      startedAt: 0,
    };
    expect(computeOverallPercent(downloadHalf)).toBeGreaterThan(8);
    expect(computeOverallPercent(downloadHalf)).toBeLessThan(88);

    const parseDone: PayloadProgressSnapshot = {
      phase: 'parse',
      fileName: 'core.json',
      bytesReceived: 100,
      totalBytes: 100,
      startedAt: 0,
    };
    expect(computeOverallPercent(parseDone)).toBe(100);
  });

  it('maps each phase band for overall percent', () => {
    const base = {
      fileName: 'core.gz',
      bytesReceived: 0,
      totalBytes: null as number | null,
      startedAt: 0,
    };
    expect(computeOverallPercent({ ...base, phase: 'manifest' })).toBe(3);
    expect(
      computeOverallPercent({ ...base, phase: 'download', bytesReceived: 0, totalBytes: 100 }),
    ).toBe(8);
    expect(
      computeOverallPercent({ ...base, phase: 'download', bytesReceived: 100, totalBytes: 100 }),
    ).toBe(88);
    expect(
      computeOverallPercent({ ...base, phase: 'verify', bytesReceived: 10, totalBytes: 10 }),
    ).toBe(92);
    expect(
      computeOverallPercent({ ...base, phase: 'inflate', bytesReceived: 10, totalBytes: 10 }),
    ).toBe(96);
    expect(
      computeOverallPercent({ ...base, phase: 'parse', bytesReceived: 10, totalBytes: 10 }),
    ).toBe(100);
  });

  it('builds progress view model with phase and ETA line', () => {
    const vm = buildPayloadProgressViewModel(
      {
        phase: 'download',
        fileName: 'core.gz',
        bytesReceived: 512_000,
        totalBytes: 1_024_000,
        startedAt: Date.now() - 1000,
      },
      Date.now(),
    );
    expect(vm.phaseText).toBe('download');
    expect(vm.overallPercent).toBeGreaterThan(0);
    expect(vm.detailLine).toContain('ETA');
  });
});
