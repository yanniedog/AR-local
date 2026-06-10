import React, { useCallback, useMemo } from 'react';
import { View } from 'react-native';

import { EmptyState } from '../../src/components/feedback';
import { ProductCard } from '../../src/components/ProductCard';
import { Screen, ScreenScrollView } from '../../src/components/Screen';
import { UndoSnackbar } from '../../src/components/Snackbar';
import { SwipeableRow } from '../../src/components/SwipeableRow';
import { AppText, Button } from '../../src/components/ui';
import { findByKey } from '../../src/data/selectors';
import { useStore } from '../../src/data/store';
import { useUndoSnackbar } from '../../src/hooks/useUndoSnackbar';
import { openCompare, openProduct } from '../../src/lib/nav';
import type { RateRow, SectionKey } from '../../src/types';

export default function Watchlist() {
  const core = useStore((s) => s.core);
  const favorites = useStore((s) => s.favorites);
  const toggleFavorite = useStore((s) => s.toggleFavorite);
  const { snack, showUndo, undo } = useUndoSnackbar();

  const items = useMemo(() => {
    if (!core) return [] as { row: RateRow; section: SectionKey }[];
    return favorites
      .map((key) => findByKey(core.sections, key))
      .filter((x): x is { row: RateRow; section: SectionKey; siblings: RateRow[] } => x !== null)
      .map(({ row, section }) => ({ row, section }));
  }, [core, favorites]);

  const removeFavorite = useCallback(
    (productKey: string, productName: string) => {
      if (!favorites.includes(productKey)) return;
      toggleFavorite(productKey);
      showUndo(`Removed ${productName}`, () => {
        const current = useStore.getState().favorites;
        if (!current.includes(productKey)) {
          useStore.getState().toggleFavorite(productKey);
        }
      });
    },
    [favorites, showUndo, toggleFavorite],
  );

  if (!core) return null;

  if (!items.length) {
    return (
      <EmptyState
        icon="star-outline"
        title="No saved products yet"
        subtitle="Tap the star on any product to add it to your watchlist and get rate-change alerts."
        fill
      />
    );
  }

  return (
    <Screen>
      <ScreenScrollView contentContainerStyle={{ padding: 16, paddingBottom: 96 }}>
        <AppText variant="small" color="textMuted" style={{ marginBottom: 12 }}>
          {items.length} saved {items.length === 1 ? 'product' : 'products'}
        </AppText>
        {items.length >= 2 ? (
          <Button
            title={`Compare ${items.length > 4 ? 'first 4' : items.length} products`}
            icon="git-compare"
            variant="secondary"
            style={{ marginBottom: 16 }}
            onPress={() => openCompare(items.slice(0, 4).map((i) => i.row.product_key))}
          />
        ) : null}
        {items.map(({ row, section }) => (
          <SwipeableRow
            key={row.product_key}
            onDelete={() => removeFavorite(row.product_key, row.product_name)}
            deleteLabel="Remove from watchlist"
          >
            <ProductCard
              row={row}
              section={section}
              onPress={() => openProduct(row.product_key, row.rate_index)}
            />
          </SwipeableRow>
        ))}
        <View style={{ height: 8 }} />
      </ScreenScrollView>
      <UndoSnackbar snack={snack} onUndo={undo} />
    </Screen>
  );
}
