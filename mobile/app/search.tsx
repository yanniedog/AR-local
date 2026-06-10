import { Ionicons } from '@expo/vector-icons';
import { FlashList } from '@shopify/flash-list';
import { Stack, useLocalSearchParams } from 'expo-router';
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Platform, Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { FilterSheet } from '../src/components/FilterSheet';
import { EmptyState, LoadingRows } from '../src/components/feedback';
import { ProPaywall } from '../src/components/ProPaywall';
import { ProductCard } from '../src/components/ProductCard';
import { Screen, screenEdgeStyle, screenScrollContentStyle } from '../src/components/Screen';
import { ToolbarIconButton } from '../src/components/ToolbarIconButton';
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
import { useProPaywall } from '../src/hooks/useProPaywall';
import { breadcrumb, rowsForSearchScope } from '../src/data/taxonomy';
import { hapticSelection } from '../src/lib/haptics';
import { openCompare, openProduct } from '../src/lib/nav';
import { canAddAlertSubscription, effectiveDeepSearch } from '../src/lib/proAccess';
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
  const insets = useSafeAreaInsets();
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
  const deepSearchActive = useStore((s) => effectiveDeepSearch(s.prefs));
  const subscriptions = useStore((s) => s.subscriptions);
  const ensureDetails = useStore((s) => s.ensureDetails);
  const ensureSearchIndex = useStore((s) => s.ensureSearchIndex);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const notificationsEnabled = useStore((s) => s.prefs.notificationsEnabled);
  const setPref = useStore((s) => s.setPref);
  const subscribeSearch = useStore((s) => s.subscribeSearch);
  const unsubscribeSearch = useStore((s) => s.unsubscribeSearch);
  const { paywallVisible, paywallIntent, requestPro, closePaywall } = useProPaywall();
  useEffect(() => {
    if (!deepSearchActive) return;
    void ensureSearchIndex();
    void ensureDetails();
  }, [deepSearchActive, ensureDetails, ensureSearchIndex]);

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
        deepSearchActive ? details?.products : null,
        deepSearchActive ? searchIndex : null,
      ),
    [baseRows, effectiveFilters, query, sortKey, section, deepSearchActive, details?.products, searchIndex],
  );

  const showDeepSearchHint =
    !!query.trim() && !deepSearchActive && rows.length === 0 && !activeFilterCount(effectiveFilters);

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
  const searchIndexLoading = deepSearchActive && !searchIndex;

  const onToggleSearchAlert = async () => {
    if (searchSub) {
      unsubscribeSearch(searchSub.id);
      return;
    }
    if (!canAddAlertSubscription(subscriptions, useStore.getState().prefs)) {
      requestPro('alert_limit');
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
  const filterCount = activeFilterCount(effectiveFilters);

  return (
    <Screen>
      <Stack.Screen options={{ title }} />
      <View style={screenEdgeStyle(theme)}>
        <Row gap={theme.spacing(3)}>
          <View style={{ flex: 1 }}>
            <SearchBar value={query} onChangeText={setQuery} />
          </View>
          <ToolbarIconButton
            icon="options"
            badge={filterCount || undefined}
            onPress={() => setFilterOpen(true)}
            accessibilityLabel="Filter products"
          />
          <ToolbarIconButton
            icon={selectMode ? 'git-compare' : 'git-compare-outline'}
            active={selectMode}
            onPress={() => {
              hapticSelection();
              setSelectMode((v) => !v);
              setSelected([]);
            }}
            accessibilityLabel="Select products to compare"
          />
        </Row>
        <Row gap={theme.spacing(2)} style={{ flexWrap: 'wrap' }}>
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
          <Pressable onPress={() => requestPro('deep_search')}>
            <AppText variant="tiny" color="primary" style={{ lineHeight: 16 }}>
              Deep product search (Pro) matches fees and features — tap to upgrade.
            </AppText>
          </Pressable>
        ) : null}
      </View>

      <View style={{ flex: 1 }}>
        <FlashList
          data={rows}
          keyExtractor={(item, i) => `${item.product_key}-${item.rate_index ?? i}`}
          contentContainerStyle={{
            ...screenScrollContentStyle(theme, insets.bottom),
            paddingBottom: theme.spacing(6) + insets.bottom + theme.spacing(8),
          }}
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
            searchIndexLoading ? (
              <LoadingRows />
            ) : (
              <EmptyState title="No matching products" subtitle="Try clearing filters or a different search." />
            )
          }
        />
      </View>

      {selectMode && selected.length >= 2 ? (
        <CompareFab
          count={selected.length}
          bottomInset={insets.bottom}
          onPress={() => openCompare(selected)}
        />
      ) : null}

      <FilterSheet
        visible={filterOpen}
        onClose={() => setFilterOpen(false)}
        rows={baseRows}
        section={section}
        filters={effectiveFilters}
        detailsProducts={details?.products}
        onApply={setFilters}
      />
      <ProPaywall
        visible={paywallVisible}
        intent={paywallIntent}
        onClose={closePaywall}
        onUpgraded={() => {
          if (paywallIntent === 'deep_search') setPref('enableDeepSearch', true);
        }}
      />
    </Screen>
  );
}

function CompareFab({
  count,
  bottomInset,
  onPress,
}: {
  count: number;
  bottomInset: number;
  onPress: () => void;
}) {
  const theme = useTheme();
  const label = `Compare ${count} product${count === 1 ? '' : 's'}`;
  const isAndroid = Platform.OS === 'android';
  const edge = theme.spacing(4);
  const bottom = theme.spacing(6) + bottomInset;

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => ({
        position: 'absolute',
        ...(isAndroid
          ? { right: edge, bottom }
          : { left: edge, right: edge, bottom: theme.spacing(6) }),
        backgroundColor: theme.colors.primary,
        borderRadius: theme.radius.pill,
        minHeight: isAndroid ? 56 : undefined,
        paddingVertical: isAndroid ? 0 : theme.spacing(4),
        paddingHorizontal: isAndroid ? theme.spacing(5) : 0,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: theme.spacing(2),
        opacity: pressed ? 0.85 : 1,
        elevation: isAndroid ? 6 : 4,
      })}
    >
      <Ionicons name="git-compare" size={isAndroid ? 24 : 18} color={theme.colors.onPrimary} />
      <AppText variant="body" weight="800" style={{ color: theme.colors.onPrimary }}>
        {isAndroid ? `Compare ${count}` : label}
      </AppText>
    </Pressable>
  );
}
