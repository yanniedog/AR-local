import { Ionicons } from '@expo/vector-icons';
import { FlashList } from '@shopify/flash-list';
import { Stack, useLocalSearchParams } from 'expo-router';
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Pressable, View } from 'react-native';

import { FilterSheet } from '../src/components/FilterSheet';
import { EmptyState, LoadingRows } from '../src/components/feedback';
import { ProductCard } from '../src/components/ProductCard';
import { Screen } from '../src/components/Screen';
import { SearchBar } from '../src/components/controls';
import { AppText, Chip, Row } from '../src/components/ui';
import { SECTIONS, SECTION_ORDER } from '../src/constants';
import {
  activeFilterCount,
  EMPTY_FILTERS,
  normalizeSortKey,
  queryAndSort,
  type Filters,
  type SortKey,
} from '../src/data/selectors';
import { ensurePermissions, registerBackgroundRefresh } from '../src/data/notifications';
import { findSearchSubscription } from '../src/data/subscriptions';
import { useStore } from '../src/data/store';
import { breadcrumb, rowsForSearchScope } from '../src/data/taxonomy';
import { openCompare, openProduct } from '../src/lib/nav';
import type { SectionKey } from '../src/types';
import { useTheme } from '../src/theme/ThemeProvider';

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: 'rate', label: 'Best rate' },
  { key: 'comparison', label: 'Comparison' },
  { key: 'bank', label: 'Bank A-Z' },
];

const rowToken = (r: { rate_index?: number | string; product_key: string }) =>
  `${r.rate_index ?? ''}#${r.product_key}`;

export default function Search() {
  const theme = useTheme();
  const { section: secRaw, path: pathRaw, sort: sortRaw, scope: scopeRaw } = useLocalSearchParams<{
    section: string;
    path?: string;
    sort?: string;
    scope?: string;
  }>();
  const section = (SECTION_ORDER.includes(secRaw as SectionKey) ? secRaw : 'Mortgage') as SectionKey;
  const path = useMemo(() => (pathRaw ?? '').split('.').filter(Boolean), [pathRaw]);
  const hierarchyScoped = scopeRaw === 'hierarchy';
  const core = useStore((s) => s.core);
  const details = useStore((s) => s.details);
  const searchIndex = useStore((s) => s.searchIndex);
  const enableDeepSearch = useStore((s) => s.prefs.enableDeepSearch);
  const ensureDetails = useStore((s) => s.ensureDetails);
  const ensureSearchIndex = useStore((s) => s.ensureSearchIndex);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const notificationsEnabled = useStore((s) => s.prefs.notificationsEnabled);
  const setPref = useStore((s) => s.setPref);
  const subscribeSearch = useStore((s) => s.subscribeSearch);
  const unsubscribeSearch = useStore((s) => s.unsubscribeSearch);
  useEffect(() => {
    if (!enableDeepSearch) return;
    void ensureSearchIndex();
    void ensureDetails();
  }, [enableDeepSearch, ensureDetails, ensureSearchIndex]);

  const [query, setQuery] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>(() => normalizeSortKey(sortRaw));
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [filterOpen, setFilterOpen] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => setSortKey(normalizeSortKey(sortRaw)), [sortRaw]);

  const baseRows = useMemo(() => {
    const all = core?.sections[section]?.rates ?? [];
    return rowsForSearchScope(all, section, path, hierarchyScoped);
  }, [core, section, path, hierarchyScoped]);

  const effectiveFilters = useMemo(
    () => ({ ...filters, includeNonStandard }),
    [filters, includeNonStandard],
  );

  const rows = useMemo(
    () =>
      queryAndSort(
        baseRows,
        { ...effectiveFilters, query },
        sortKey,
        section,
        enableDeepSearch ? details?.products : null,
        enableDeepSearch ? searchIndex : null,
      ),
    [baseRows, effectiveFilters, query, sortKey, section, enableDeepSearch, details?.products, searchIndex],
  );

  const showDeepSearchHint =
    !!query.trim() && !enableDeepSearch && rows.length === 0 && !activeFilterCount(effectiveFilters);

  const searchSnapshot = useMemo(
    () => ({
      section,
      path,
      hierarchyScoped,
      query,
      filters: {
        providers: effectiveFilters.providers,
        rateTypes: effectiveFilters.rateTypes,
        lvrTiers: effectiveFilters.lvrTiers,
        repaymentTypes: effectiveFilters.repaymentTypes,
        depositKinds: effectiveFilters.depositKinds,
        interestPayments: effectiveFilters.interestPayments,
        accountFeatures: effectiveFilters.accountFeatures,
        eligibilityCriteria: effectiveFilters.eligibilityCriteria,
        includeNonStandard: effectiveFilters.includeNonStandard,
      },
    }),
    [section, path, hierarchyScoped, query, effectiveFilters],
  );

  const searchSub = useStore((s) => findSearchSubscription(s.subscriptions, searchSnapshot));
  const searchIndexLoading = enableDeepSearch && !searchIndex;

  const onToggleSearchAlert = async () => {
    if (searchSub) {
      unsubscribeSearch(searchSub.id);
      return;
    }
    const ok = await ensurePermissions();
    if (!ok) {
      Alert.alert('Notifications disabled', 'Enable notifications for Australian Rates in system settings.');
      return;
    }
    if (!notificationsEnabled) {
      setPref('notificationsEnabled', true);
      void registerBackgroundRefresh();
    }
    const added = subscribeSearch(searchSnapshot);
    if (!added) Alert.alert('Already subscribed', 'This search already has a rate alert.');
  };

  const toggleSelect = (key: string) =>
    setSelected((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key].slice(-4)));

  if (!core) return null;
  const title = path.length ? breadcrumb(section, path).at(-1)! : `${SECTIONS[section].title}`;

  return (
    <Screen>
      <Stack.Screen options={{ title }} />
      <View style={{ paddingHorizontal: 16, paddingTop: 12, gap: 10 }}>
        <Row gap={10}>
          <View style={{ flex: 1 }}>
            <SearchBar value={query} onChangeText={setQuery} />
          </View>
          <IconBtn icon="options" count={activeFilterCount(effectiveFilters)} onPress={() => setFilterOpen(true)} />
          <IconBtn
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
            <Chip key={o.key} label={o.label} selected={sortKey === o.key} onPress={() => setSortKey(o.key)} />
          ))}
          <Chip
            icon={searchSub ? 'notifications' : 'notifications-outline'}
            label={searchSub ? 'Search alert on' : 'Alert this search'}
            selected={!!searchSub}
            onPress={() => void onToggleSearchAlert()}
          />
        </Row>
        {searchSub ? (
          <AppText variant="tiny" color="textFaint">
            {rows.length} products · {searchSub.label}
          </AppText>
        ) : null}
        {showDeepSearchHint ? (
          <AppText variant="tiny" color="textFaint">
            Enable Deep product search in Settings for fees and features.
          </AppText>
        ) : null}
      </View>

      <View style={{ flex: 1 }}>
        {searchIndexLoading ? (
          <View style={{ paddingHorizontal: 16, paddingTop: 12 }}>
            <LoadingRows count={8} />
          </View>
        ) : (
          <FlashList
            data={rows}
            keyExtractor={(item, i) => `${item.product_key}-${item.rate_index ?? i}`}
            contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 12, paddingBottom: 120 }}
            renderItem={({ item }) => (
              <ProductCard
                row={item}
                section={section}
                selectMode={selectMode}
                selected={selected.includes(rowToken(item))}
                onPress={() =>
                  selectMode ? toggleSelect(rowToken(item)) : openProduct(item.product_key, item.rate_index)
                }
              />
            )}
            ListEmptyComponent={
              <EmptyState title="No matching products" subtitle="Try clearing filters or a different search." />
            }
          />
        )}
      </View>

      {selectMode && selected.length >= 2 ? (
        <Pressable
          onPress={() => openCompare(selected)}
          style={({ pressed }) => ({
            position: 'absolute',
            left: 16,
            right: 16,
            bottom: 24,
            backgroundColor: theme.colors.primary,
            borderRadius: theme.radius.pill,
            paddingVertical: 14,
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            opacity: pressed ? 0.85 : 1,
            elevation: 4,
          })}
        >
          <Ionicons name="git-compare" size={18} color={theme.colors.onPrimary} />
          <AppText variant="body" weight="800" style={{ color: theme.colors.onPrimary }}>
            Compare {selected.length} products
          </AppText>
        </Pressable>
      ) : null}

      <FilterSheet
        visible={filterOpen}
        onClose={() => setFilterOpen(false)}
        rows={baseRows}
        section={section}
        filters={effectiveFilters}
        detailsProducts={details?.products}
        onApply={(next) => {
          setPref('includeNonStandard', next.includeNonStandard);
          setFilters(next);
        }}
      />
    </Screen>
  );
}

function IconBtn({
  icon,
  count,
  active,
  onPress,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  count?: number;
  active?: boolean;
  onPress: () => void;
}) {
  const theme = useTheme();
  return (
    <View>
      <Pressable
        onPress={onPress}
        style={{
          backgroundColor: active ? theme.colors.primaryMuted : theme.colors.surfaceAlt,
          borderRadius: theme.radius.md,
          paddingHorizontal: 12,
          height: 44,
          justifyContent: 'center',
        }}
      >
        <Ionicons name={icon} size={20} color={active ? theme.colors.primary : theme.colors.text} />
      </Pressable>
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
