import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useMemo, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, View } from 'react-native';

import { RbaChart } from '../../src/components/charts';
import { OfflineBanner } from '../../src/components/feedback';
import { ProductCard } from '../../src/components/ProductCard';
import { Ribbon } from '../../src/components/Ribbon';
import { CompactToggle, SegmentedControl } from '../../src/components/controls';
import { AppText, Card, Chip, Divider, IconButton, Row } from '../../src/components/ui';
import { SECTIONS } from '../../src/constants';
import { formatRunDate, relativeDate } from '../../src/data/format';
import { bestRow } from '../../src/data/selectors';
import { childrenOf, rowsUnder, statsFor } from '../../src/data/taxonomy';
import { useStore } from '../../src/data/store';
import { openNode, openProduct, openRibbonProducts } from '../../src/lib/nav';
import type { SectionKey } from '../../src/types';
import { useTheme } from '../../src/theme/ThemeProvider';

const SECTION_SEG = [
  { value: 'Mortgage' as SectionKey, label: 'Loans' },
  { value: 'Savings' as SectionKey, label: 'Savings' },
  { value: 'TD' as SectionKey, label: 'Deposits' },
];

export default function Home() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const manifest = useStore((s) => s.manifest);
  const refreshing = useStore((s) => s.refreshing);
  const refresh = useStore((s) => s.refresh);
  const source = useStore((s) => s.source);
  const offline = useStore((s) => s.offline);
  const defaultSection = useStore((s) => s.prefs.defaultSection);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const setPref = useStore((s) => s.setPref);
  const [section, setSection] = useState<SectionKey>(defaultSection);

  const onRefresh = useCallback(() => void refresh({ manual: true, force: true }), [refresh]);

  const sectionRows = core?.sections[section]?.rates;
  // Restrict to rows in this section's hierarchy (drops alternate-root rows like
  // OVERDRAFT) so the hero, ribbon and categories all agree.
  const hierRows = useMemo(() => rowsUnder(sectionRows ?? [], section, []), [sectionRows, section]);
  const stats = useMemo(() => statsFor(hierRows, includeNonStandard), [hierRows, includeNonStandard]);
  const categories = useMemo(
    () => childrenOf(hierRows, section, [], includeNonStandard),
    [hierRows, section, includeNonStandard],
  );
  const best = useMemo(
    () => bestRow(hierRows, section, includeNonStandard),
    [hierRows, section, includeNonStandard],
  );

  if (!core) return null;
  const meta = SECTIONS[section];
  const rba = core.rba.at(-1);
  const accent = meta.lowerIsBetter ? theme.colors.success : theme.colors.primary;
  const heroRate = meta.lowerIsBetter ? stats.min : stats.max;

  return (
    <ScrollView
      contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.colors.primary} />
      }
    >
      <OfflineBanner source={source} offline={offline} />

      <Row style={{ justifyContent: 'space-between', marginBottom: 14 }}>
        <View style={{ flex: 1 }}>
          <AppText variant="h1">Australian rates</AppText>
          <AppText variant="small" color="textMuted" numberOfLines={1}>
            Updated {formatRunDate(core.run_date)} · {relativeDate(`${core.run_date}T00:00:00Z`)}
          </AppText>
        </View>
        <IconButton icon="refresh" onPress={onRefresh} accessibilityLabel="Refresh" />
      </Row>

      <SegmentedControl options={SECTION_SEG} value={section} onChange={setSection} />
      <View style={{ marginTop: 10 }}>
        <CompactToggle
          label="Include non-standard accounts"
          value={includeNonStandard}
          onChange={(value) => setPref('includeNonStandard', value)}
        />
      </View>

      {/* Hero: best rate + ribbon distribution for the section */}
      <Card style={{ marginTop: 14, marginBottom: 14 }}>
        <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
          <View style={{ flex: 1, paddingRight: 10 }}>
            <AppText variant="small" color="textMuted">
              {meta.lowerIsBetter ? 'Lowest' : 'Top'} {meta.title.toLowerCase()} rate
            </AppText>
            <AppText variant="h1" weight="800" style={{ color: accent }}>
              {heroRate !== null ? `${(heroRate * 100).toFixed(2)}%` : '—'}
            </AppText>
          </View>
          {section === 'Mortgage' && rba ? (
            <View style={{ alignItems: 'flex-end' }}>
              <AppText variant="tiny" color="textFaint">
                RBA cash rate
              </AppText>
              <AppText variant="h3" weight="800" style={{ color: theme.colors.primary }}>
                {rba.rate.toFixed(2)}%
              </AppText>
            </View>
          ) : null}
        </Row>
        <Ribbon stats={stats} section={section} rbaRate={section === 'Mortgage' ? rba?.rate ?? null : null} />
        <AppText variant="tiny" weight="700" color="textFaint" style={{ marginTop: 12, marginBottom: 7 }}>
          VIEW PRODUCTS
        </AppText>
        <Row gap={8} style={{ flexWrap: 'wrap' }}>
          <Chip
            label={meta.lowerIsBetter ? 'Lowest rates' : 'Top yields'}
            icon="trending-up"
            onPress={() => openRibbonProducts(section, 'rate')}
          />
          {section === 'Mortgage' ? (
            <Chip
              label="Comparison"
              icon="swap-vertical"
              onPress={() => openRibbonProducts(section, 'comparison')}
            />
          ) : null}
          <Chip label="Bank A-Z" icon="business" onPress={() => openRibbonProducts(section, 'bank')} />
        </Row>
      </Card>

      {section === 'Mortgage' ? (
        <Card style={{ marginBottom: 14 }}>
          <Row gap={8} style={{ marginBottom: 6 }}>
            <Ionicons name="trending-up" size={16} color={theme.colors.primary} />
            <AppText variant="h3">RBA cash rate</AppText>
          </Row>
          <RbaChart data={core.rba} height={140} />
        </Card>
      ) : null}

      {/* Browse by category (top of the AR-local drill-down hierarchy) */}
      <AppText variant="small" weight="700" color="textMuted" style={{ marginBottom: 10, marginLeft: 2 }}>
        BROWSE BY CATEGORY
      </AppText>
      {categories.map((node) => {
        const nodeBest = meta.lowerIsBetter ? node.stats.min : node.stats.max;
        return (
          <Pressable
            key={node.seg}
            onPress={() => openNode(section, [node.seg])}
            style={({ pressed }) => ({
              backgroundColor: theme.colors.card,
              borderRadius: theme.radius.lg,
              borderWidth: 1,
              borderColor: theme.colors.border,
              padding: 14,
              marginBottom: 10,
              opacity: pressed ? 0.85 : 1,
            })}
          >
            <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <View style={{ flex: 1, paddingRight: 10 }}>
                <AppText variant="body" weight="700" numberOfLines={2}>
                  {node.label}
                </AppText>
                <AppText variant="tiny" color="textFaint" style={{ marginTop: 2 }}>
                  {node.stats.products} products · {node.stats.providers} lenders
                </AppText>
              </View>
              <Row gap={4}>
                <AppText variant="h3" weight="800" style={{ color: accent }}>
                  {nodeBest !== null ? `${(nodeBest * 100).toFixed(2)}%` : '—'}
                </AppText>
                <Ionicons name="chevron-forward" size={18} color={theme.colors.textFaint} />
              </Row>
            </Row>
          </Pressable>
        );
      })}

      {best ? (
        <>
          <AppText variant="small" weight="700" color="textMuted" style={{ marginTop: 10, marginBottom: 10, marginLeft: 2 }}>
            BEST RATE TODAY
          </AppText>
          <ProductCard row={best} section={section} onPress={() => openProduct(best.product_key, best.rate_index)} />
        </>
      ) : null}

      <Card style={{ marginTop: 8 }}>
        <Row style={{ justifyContent: 'space-between' }}>
          <AppText variant="small" color="textMuted">
            Next update {manifest?.schedule?.label ?? 'daily'}
          </AppText>
          <AppText variant="small" color="textFaint">
            {Object.keys(core.brands).length} lenders
          </AppText>
        </Row>
        <Divider style={{ marginVertical: 10 }} />
        <AppText variant="tiny" color="textFaint">
          Live data published by the Raspberry Pi to GitHub · run {formatRunDate(core.run_date)}
        </AppText>
      </Card>
    </ScrollView>
  );
}
