import { Ionicons } from '@expo/vector-icons';
import React, { useCallback } from 'react';
import { RefreshControl, ScrollView, View } from 'react-native';

import { BankAvatar } from '../../src/components/BankAvatar';
import { RbaChart } from '../../src/components/charts';
import { OfflineBanner } from '../../src/components/feedback';
import { MetricCard } from '../../src/components/MetricCard';
import { ProductCard } from '../../src/components/ProductCard';
import { AppText, Card, Divider, IconButton, Row } from '../../src/components/ui';
import { SECTIONS, SECTION_ORDER } from '../../src/constants';
import { formatRate, formatRunDate, relativeDate } from '../../src/data/format';
import { bestRow } from '../../src/data/selectors';
import { useStore } from '../../src/data/store';
import { openBrowse, openProduct } from '../../src/lib/nav';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function Home() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const manifest = useStore((s) => s.manifest);
  const refreshing = useStore((s) => s.refreshing);
  const refresh = useStore((s) => s.refresh);
  const source = useStore((s) => s.source);
  const offline = useStore((s) => s.offline);
  const interests = useStore((s) => s.prefs.interests);

  const onRefresh = useCallback(() => void refresh({ manual: true, force: true }), [refresh]);

  if (!core) return null;
  const sections = interests.length ? interests : SECTION_ORDER;
  const currentRba = core.rba.at(-1);

  return (
    <ScrollView
      contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.colors.primary} />
      }
    >
      <OfflineBanner source={source} offline={offline} />

      <Row style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <View>
          <AppText variant="h1">Today&apos;s rates</AppText>
          <AppText variant="small" color="textMuted">
            Updated {formatRunDate(core.run_date)} · {relativeDate(`${core.run_date}T00:00:00Z`)}
          </AppText>
        </View>
        <IconButton icon="refresh" onPress={onRefresh} accessibilityLabel="Refresh" />
      </Row>

      {/* RBA cash rate */}
      <Card style={{ marginBottom: 16 }}>
        <Row style={{ justifyContent: 'space-between' }}>
          <Row gap={8}>
            <Ionicons name="business" size={18} color={theme.colors.primary} />
            <AppText variant="h3">RBA cash rate</AppText>
          </Row>
          <AppText variant="h2" weight="800" style={{ color: theme.colors.primary }}>
            {currentRba ? `${currentRba.rate.toFixed(2)}%` : '—'}
          </AppText>
        </Row>
        <View style={{ marginTop: 8 }}>
          <RbaChart data={core.rba} height={150} />
        </View>
      </Card>

      {/* Category metrics */}
      <Row gap={12} style={{ flexWrap: 'wrap', marginBottom: 4 }}>
        {sections.map((key) => {
          const meta = SECTIONS[key];
          const rows = core.sections[key]?.rates ?? [];
          const best = bestRow(rows, key);
          return (
            <View key={key} style={{ width: '47.5%', flexGrow: 1 }}>
              <MetricCard
                icon={meta.icon as keyof typeof Ionicons.glyphMap}
                title={meta.title}
                value={best ? formatRate(best.rate) : '—'}
                sub={`${meta.lowerIsBetter ? 'Lowest' : 'Top'} of ${core.sections[key]?.ribbon.counts.products ?? 0}`}
                accent={meta.lowerIsBetter ? theme.colors.success : theme.colors.primary}
                onPress={() => openBrowse(key)}
              />
            </View>
          );
        })}
      </Row>

      {/* Best rates today */}
      <AppText variant="h3" style={{ marginTop: 20, marginBottom: 10 }}>
        Best rates today
      </AppText>
      {sections.map((key) => {
        const rows = core.sections[key]?.rates ?? [];
        const best = bestRow(rows, key);
        if (!best) return null;
        return (
          <View key={key} style={{ marginBottom: 4 }}>
            <AppText variant="tiny" color="textFaint" style={{ marginBottom: 4, marginLeft: 4 }}>
              {SECTIONS[key].title.toUpperCase()}
            </AppText>
            <ProductCard row={best} section={key} onPress={() => openProduct(best.product_key)} />
          </View>
        );
      })}

      <Card style={{ marginTop: 8 }}>
        <Row style={{ justifyContent: 'space-between' }}>
          <Row gap={10}>
            <BankAvatar provider={Object.keys(core.brands)[0] ?? 'AR'} size={36} />
            <View>
              <AppText variant="body" weight="700">
                {manifest?.counts?.products ?? core.sections.Mortgage.ribbon.counts.products} products
              </AppText>
              <AppText variant="small" color="textMuted">
                Across {Object.keys(core.brands).length} lenders
              </AppText>
            </View>
          </Row>
        </Row>
        <Divider style={{ marginVertical: 12 }} />
        <Row
          style={{ justifyContent: 'space-between' }}
        >
          <AppText variant="small" color="textMuted">
            Next update {manifest?.schedule?.label ?? 'daily'}
          </AppText>
          <AppText variant="small" color="textFaint">
            schema v{core.schema_version}
          </AppText>
        </Row>
      </Card>
    </ScrollView>
  );
}
