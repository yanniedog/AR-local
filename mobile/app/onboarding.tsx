import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import React, { useMemo, useState } from 'react';
import { Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { BankAvatar } from '../src/components/BankAvatar';
import { Chip } from '../src/components/ui';
import { AppText, Button, Card, Row } from '../src/components/ui';
import { SECTIONS, SECTION_ORDER } from '../src/constants';
import { formatRate } from '../src/data/format';
import { resolveSectionRibbonStats } from '../src/data/ribbonStats';
import { bestRow } from '../src/data/selectors';
import { useStore } from '../src/data/store';
import { rowsUnder } from '../src/data/taxonomy';
import { ensurePermissions, registerBackgroundRefresh } from '../src/data/notifications';
import type { RateRow, SectionKey } from '../src/types';
import { useTheme } from '../src/theme/ThemeProvider';

type OnboardingStep = 1 | 2;

function primaryInterest(interests: SectionKey[]): SectionKey {
  return interests[0] ?? 'Mortgage';
}

function snapshotComparison(
  section: SectionKey,
  stats: { median: number | null },
  rbaRate: number | undefined,
): string | null {
  if (section === 'Mortgage' && rbaRate != null) {
    return `RBA cash ${rbaRate.toFixed(2)}%`;
  }
  if (stats.median != null) {
    return `Median ${(stats.median * 100).toFixed(2)}%`;
  }
  return null;
}

function NotificationPreview({
  section,
  best,
}: {
  section: SectionKey;
  best: RateRow | null;
}) {
  const theme = useTheme();
  const meta = SECTIONS[section];
  const rateLabel = best ? formatRate(best.rate) : '—';
  const lender = best?.provider ?? 'a lender';

  return (
    <View
      style={{
        backgroundColor: theme.colors.surface,
        borderRadius: theme.radius.md,
        borderWidth: 1,
        borderColor: theme.colors.border,
        padding: 12,
        marginTop: 16,
      }}
    >
      <AppText variant="tiny" color="textFaint" weight="700" style={{ marginBottom: 8, letterSpacing: 0.6 }}>
        PREVIEW
      </AppText>
      <Row gap={10} style={{ alignItems: 'flex-start' }}>
        <View
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            backgroundColor: theme.colors.primary,
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Ionicons name="trending-up" size={20} color={theme.colors.onPrimary} />
        </View>
        <View style={{ flex: 1 }}>
          <AppText variant="small" weight="700">
            Australian Rates
          </AppText>
          <AppText variant="tiny" color="textMuted">
            now
          </AppText>
          <AppText variant="body" style={{ marginTop: 4 }}>
            Best {meta.short.toLowerCase()} rate is {rateLabel} at {lender}
          </AppText>
        </View>
      </Row>
    </View>
  );
}

export default function Onboarding() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const core = useStore((s) => s.core);
  const completeOnboarding = useStore((s) => s.completeOnboarding);
  const [step, setStep] = useState<OnboardingStep>(1);
  const [interests, setInterests] = useState<SectionKey[]>(['Mortgage', 'Savings', 'TD']);
  const [notify, setNotify] = useState(false);

  const section = primaryInterest(interests);
  const meta = SECTIONS[section];
  const accent = meta.lowerIsBetter ? theme.colors.success : theme.colors.primary;

  const snapshot = useMemo(() => {
    if (!core) return null;
    const sectionRows = core.sections[section]?.rates;
    const sectionData = core.sections[section];
    const hierRows = rowsUnder(sectionRows ?? [], section, []);
    const stats = resolveSectionRibbonStats(sectionData, hierRows, false);
    const best = bestRow(hierRows, section, false);
    const heroRate = meta.lowerIsBetter ? stats.min : stats.max;
    const rba = section === 'Mortgage' ? core.rba?.at(-1)?.rate : undefined;
    return { best, heroRate, stats, rba, runDate: core.run_date };
  }, [core, section, meta.lowerIsBetter]);

  const toggle = (key: SectionKey) =>
    setInterests((prev) => {
      if (prev.includes(key)) {
        const next = prev.filter((k) => k !== key);
        return next.length ? next : prev;
      }
      return [...prev, key];
    });

  const start = async () => {
    if (notify) {
      const ok = await ensurePermissions();
      if (ok) void registerBackgroundRefresh();
      completeOnboarding(interests, ok);
    } else {
      completeOnboarding(interests, false);
    }
    router.replace('/(tabs)');
  };

  if (!core) return null;

  const comparison = snapshot
    ? snapshotComparison(section, snapshot.stats, snapshot.rba)
    : null;

  return (
    <View
      style={{
        flex: 1,
        paddingTop: insets.top + 24,
        paddingHorizontal: 24,
        backgroundColor: theme.colors.bg,
      }}
    >
      <Row style={{ justifyContent: 'space-between', marginBottom: 20 }}>
        <AppText variant="tiny" color="textFaint" weight="700">
          {step} / 2
        </AppText>
        {step === 2 ? (
          <Pressable onPress={() => setStep(1)} hitSlop={8}>
            <AppText variant="small" color="primary" weight="600">
              Back
            </AppText>
          </Pressable>
        ) : null}
      </Row>

      {step === 1 ? (
        <>
          <AppText variant="h1">See your market</AppText>
          <AppText variant="body" color="textMuted" style={{ marginTop: 8, lineHeight: 22 }}>
            Pick what you track — we&apos;ll show today&apos;s best rate from live Australian data.
          </AppText>

          <AppText variant="h3" style={{ marginTop: 28, marginBottom: 12 }}>
            What are you interested in?
          </AppText>
          <Row gap={10} style={{ flexWrap: 'wrap' }}>
            {SECTION_ORDER.map((key) => (
              <Chip
                key={key}
                label={SECTIONS[key].title}
                icon={SECTIONS[key].icon as keyof typeof Ionicons.glyphMap}
                selected={interests.includes(key)}
                onPress={() => toggle(key)}
              />
            ))}
          </Row>

          <Card
            style={{
              marginTop: 24,
              borderColor: `${accent}44`,
            }}
          >
            <AppText variant="tiny" color="textFaint" weight="700">
              {meta.title.toUpperCase()}
            </AppText>
            <AppText variant="small" color="textMuted" style={{ marginTop: 2 }}>
              Best rate today · {snapshot?.runDate ?? '—'}
            </AppText>
            <AppText variant="h1" weight="800" style={{ color: accent, marginTop: 6 }}>
              {snapshot?.heroRate != null ? `${(snapshot.heroRate * 100).toFixed(2)}%` : '—'}
            </AppText>
            {snapshot?.best ? (
              <Row gap={10} style={{ marginTop: 12, alignItems: 'center' }}>
                <BankAvatar provider={snapshot.best.provider} size={36} />
                <View style={{ flex: 1 }}>
                  <AppText variant="body" weight="700">
                    {snapshot.best.provider}
                  </AppText>
                  <AppText variant="tiny" color="textMuted">
                    {formatRate(snapshot.best.rate)}
                    {snapshot.best.comparison_rate
                      ? ` · cmp ${formatRate(snapshot.best.comparison_rate)}`
                      : ''}
                  </AppText>
                </View>
              </Row>
            ) : null}
            {snapshot ? (
              <AppText variant="small" color="textMuted" style={{ marginTop: 10 }}>
                {comparison ? `vs ${comparison}` : 'Updated daily from CDR data'}
              </AppText>
            ) : null}
          </Card>

          <View style={{ flex: 1 }} />
          <Button
            title="Continue"
            icon="arrow-forward"
            onPress={() => setStep(2)}
            style={{ marginBottom: insets.bottom + 20 }}
          />
        </>
      ) : (
        <>
          <AppText variant="h1">Stay ahead of moves</AppText>
          <AppText variant="body" color="textMuted" style={{ marginTop: 8, lineHeight: 22 }}>
            Get a local alert when the best {meta.short.toLowerCase()} rate changes or the RBA
            updates — only if you want it.
          </AppText>

          <Row gap={12} style={{ marginTop: 28, alignItems: 'flex-start' }}>
            <Ionicons name="notifications-outline" size={22} color={theme.colors.primary} />
            <View style={{ flex: 1 }}>
              <AppText variant="body" weight="700">
                Notify me when this rate moves
              </AppText>
              <AppText variant="small" color="textMuted" style={{ marginTop: 2 }}>
                Best-rate, RBA, and watchlist alerts — local only, no account.
              </AppText>
            </View>
            <Chip label={notify ? 'On' : 'Off'} selected={notify} onPress={() => setNotify((v) => !v)} />
          </Row>

          {notify ? <NotificationPreview section={section} best={snapshot?.best ?? null} /> : null}

          <View style={{ flex: 1 }} />
          <Button
            title={notify ? 'Enable alerts & start' : 'Start without alerts'}
            icon="arrow-forward"
            onPress={start}
            style={{ marginBottom: insets.bottom + 20 }}
          />
        </>
      )}
    </View>
  );
}
