import { Ionicons } from '@expo/vector-icons';
import { FlashList } from '@shopify/flash-list';
import { useLocalSearchParams } from 'expo-router';
import React, { useMemo, useState } from 'react';
import { Pressable, View } from 'react-native';

import { FilterSheet } from '../../src/components/FilterSheet';
import { EmptyState } from '../../src/components/feedback';
import { ProductCard } from '../../src/components/ProductCard';
import { RibbonBar } from '../../src/components/RibbonBar';
import { SearchBar, SegmentedControl } from '../../src/components/controls';
import { AppText, Card, Chip, Row } from '../../src/components/ui';
import { SECTIONS, sectionFromSlug } from '../../src/constants';
import {
  activeFilterCount,
  EMPTY_FILTERS,
  queryAndSort,
  type Filters,
  type SortKey,
} from '../../src/data/selectors';
import { useStore } from '../../src/data/store';
import { openCompare, openProduct } from '../../src/lib/nav';
import type { RateRow, SectionKey } from '../../src/types';
import { useTheme } from '../../src/theme/ThemeProvider';

// A product can have several rate rows; encode the exact selected row so Compare
// shows that row, not just the product's first one. '' can't occur in a key.
const rowToken = (r: RateRow) => `${r.rate_index ?? ''}#${r.product_key}`;

const SECTION_SEG = [
  { value: 'Mortgage' as SectionKey, label: 'Loans' },
  { value: 'Savings' as SectionKey, label: 'Savings' },
  { value: 'TD' as SectionKey, label: 'Deposits' },
];

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: 'rate', label: 'Best rate' },
  { key: 'comparison', label: 'Comparison' },
  { key: 'bank', label: 'Bank Aâ€“Z' },
];

export default function Browse() {
  const params = useLocalSearchParams<{ section?: string }>();
  const defaultSection = useStore((s) => s.prefs.defaultSection);
  const core = useStore((s) => s.core);
  const refreshing = useStore((s) => s.refreshing);
  const refresh = useStore((s) => s.refresh);

  const initial = (params.section && sectionFromSlug(params.section)) || defaultSection;
  const [section, setSection] = useState<SectionKey>(initial);
  const [query, setQuery] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('rate');
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [filterOpen, setFilterOpen] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);

  const sectionRows = core?.sections[section]?.rates;
  const ribbon = core?.sections[section]?.ribbon;

  const rows = useMemo(
    () => queryAndSort(sectionRows ?? [], { ...filters, query }, sortKey, section),
    [sectionRows, filters, query, sortKey, section],
  );

  const activeFilters = activeFilterCount(filters);

  const toggleSelect = (key: string) =>
    setSelected((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key].slice(-4)));

  if (!core) return null;

  return (
    <View style={{ flex: 1 }}>
      <View style={{ paddingHorizontal: 16, paddingTop: 12, gap: 10 }}>
        <SegmentedControl
          options={SECTION_SEG}
          value={section}
          onChange={(v) => {
            setSection(v);
            // Filters are section-specific (LVR tiers, deposit kinds, â€¦) â€” clear them
            // so the new category isn't filtered to empty by an incompatible facet.
            setFilters(EMPTY_FILTERS);
            setSelected([]);
          }}
        />
        <Row gap={10}>
          <View style={{ flex: 1 }}>
            <SearchBar value={query} onChangeText={setQuery} />
          </View>
          <FilterButton count={activeFilters} onPress={() => setFilterOpen(true)} />
          <FilterButton
            icon={selectMode ? 'git-compare' : 'git-compare-outline'}
            active={selectMode}
            onPress={() => {
              setSelectMode((v) => !v);
              setSelected([]);
            }}
          />
        </Row>
        <Row gap={8} style={{ flexWrap: 'wrap' }}>
          {SORT_OPTIONS.map((o) => (
            <Chip
              key={o.key}
              label={o.label}
              selected={sortKey === o.key}
              onPress={() => setSortKey(o.key)}
            />
          ))}
        </Row>
      </View>

      <FlashList
        data={rows}
        keyExtractor={(item, i) => `${item.product_key}-${item.rate_index ?? i}`}
        estimatedItemSize={98}
        refreshing={refreshing}
        onRefresh={() => void refresh({ manual: true, force: true })}
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 12, paddingBottom: 120 }}
        ListHeaderComponent={
          ribbon && ribbon.range.min !== null ? (
            <Card style={{ marginBottom: 12 }}>
              <AppText variant="small" color="textMuted" style={{ marginBottom: 10 }}>
                {SECTIONS[section].title} Â· rate distribution
              </AppText>
              <RibbonBar ribbon={ribbon} section={section} />
            </Card>
          ) : null
        }
        renderItem={({ item }) => (
          <ProductCard
            row={item}
            section={section}
            selectMode={selectMode}
            selected={selected.includes(rowToken(item))}
            onPress={() =>
              selectMode ? toggleSelect(rowToken(item)) : openProduct(item.product_key)
            }
          />
        )}
        ListEmptyComponent={
          <EmptyState
            title="No matching products"
            subtitle="Try clearing filters or a different search."
          />
        }
      />

      {selectMode && selected.length >= 2 ? (
        <View style={{ position: 'absolute', left: 16, right: 16, bottom: 24 }}>
          <CompareBtn count={selected.length} onPress={() => openCompare(selected)} />
        </View>
      ) : null}

      <FilterSheet
        visible={filterOpen}
        onClose={() => setFilterOpen(false)}
        rows={sectionRows ?? []}
        section={section}
        filters={filters}
        onApply={setFilters}
      />
    </View>
  );
}

function FilterButton({
  count,
  active,
  icon = 'options',
  onPress,
}: {
  count?: number;
  active?: boolean;
  icon?: keyof typeof Ionicons.glyphMap;
  onPress: () => void;
}) {
  const theme = useTheme();
  return (
    <View>
      <Ionicons.Button
        name={icon}
        onPress={onPress}
        backgroundColor={active ? theme.colors.primaryMuted : theme.colors.surfaceAlt}
        color={active ? theme.colors.primary : theme.colors.text}
        size={20}
        iconStyle={{ marginRight: 0 }}
        borderRadius={theme.radius.md}
        style={{ paddingHorizontal: 12, paddingVertical: 11 }}
      />
      {count ? (
        <View
          style={{
            position: 'absolute',
            top: -4,
            right: -4,
            backgroundColor: theme.colors.primary,
            borderRadius: 999,
            minWidth: 18,
            height: 18,
            alignItems: 'center',
            justifyContent: 'center',
            paddingHorizontal: 4,
          }}
        >
          <AppText variant="tiny" weight="800" style={{ color: theme.colors.onPrimary }}>
            {count}
          </AppText>
        </View>
      ) : null}
    </View>
  );
}

function CompareBtn({ count, onPress }: { count: number; onPress: () => void }) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        backgroundColor: theme.colors.primary,
        borderRadius: theme.radius.pill,
        paddingVertical: 14,
        alignItems: 'center',
        flexDirection: 'row',
        justifyContent: 'center',
        gap: 8,
        opacity: pressed ? 0.85 : 1,
        shadowColor: '#000',
        shadowOpacity: 0.25,
        shadowRadius: 8,
        shadowOffset: { width: 0, height: 3 },
        elevation: 4,
      })}
    >
      <Ionicons name="git-compare" size={18} color={theme.colors.onPrimary} />
      <AppText variant="body" weight="800" style={{ color: theme.colors.onPrimary }}>
        Compare {count} products
      </AppText>
    </Pressable>
  );
}
