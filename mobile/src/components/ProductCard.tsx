import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable, View } from 'react-native';

import { SECTIONS } from '../constants';
import {
  formatBalanceRange,
  formatRate,
  formatTerm,
  humanizeEnum,
  isNonStandard,
} from '../data/format';
import { useStore } from '../data/store';
import { rateValueLabel } from '../lib/a11ySummaries';
import { rateQualifier } from '../lib/rateQualifier';
import type { RateRow, SectionKey } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { BankAvatar } from './BankAvatar';
import { androidRipple, AppText, Row } from './ui';

function chips(row: RateRow, section: SectionKey): string[] {
  const out: string[] = [];
  if (section === 'Mortgage') {
    if (row.ribbon_rate_structure) out.push(humanizeEnum(row.ribbon_rate_structure));
    const term = formatTerm(row);
    if (term) out.push(term);
    if (row.ribbon_repayment_type ?? row.repayment_type)
      out.push(humanizeEnum(row.ribbon_repayment_type ?? row.repayment_type));
    if (row.lvr_tier) out.push(humanizeEnum(row.lvr_tier));
  } else if (section === 'TD') {
    const term = formatTerm(row);
    if (term) out.push(term);
    const bal = formatBalanceRange(row.balance_min, row.balance_max);
    if (bal) out.push(bal);
  } else {
    // Bonus / introductory deposit kinds are surfaced as a distinct warning
    // badge (see ProductCard), so don't also repeat them as a neutral chip.
    const kind = row.ribbon_deposit_kind?.toLowerCase();
    if (row.ribbon_deposit_kind && kind !== 'bonus' && kind !== 'introductory') {
      out.push(humanizeEnum(row.ribbon_deposit_kind));
    }
    const bal = formatBalanceRange(row.balance_min, row.balance_max);
    if (bal) out.push(bal);
  }
  return out.slice(0, 3);
}

export function ProductCard({
  row,
  section,
  onPress,
  selectMode,
  selected,
}: {
  row: RateRow;
  section: SectionKey;
  onPress?: () => void;
  selectMode?: boolean;
  selected?: boolean;
}) {
  const theme = useTheme();
  const favorite = useStore((s) => s.favorites.includes(row.product_key));
  const toggleFavorite = useStore((s) => s.toggleFavorite);
  const tags = chips(row, section);
  const nonStandard = isNonStandard(row);
  const qualifier = rateQualifier(row, section);
  const lowerIsBetter = SECTIONS[section].lowerIsBetter;
  const rateLabel = rateValueLabel(section);
  const rateText = formatRate(row.rate);
  const cardA11yLabel = `${row.product_name}, ${row.provider}, ${rateLabel} ${rateText}${
    row.comparison_rate ? `, comparison ${formatRate(row.comparison_rate)}` : ''
  }${qualifier.conditional ? `, ${qualifier.label}, conditions apply` : ''}`;

  return (
    // Card container is a plain View; the nav target and the favorite star are
    // SEPARATE press targets so tapping the star never also opens the product.
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingVertical: 12,
        paddingHorizontal: 14,
        backgroundColor: selected ? theme.colors.primaryMuted : theme.colors.card,
        borderRadius: theme.radius.lg,
        borderWidth: 1,
        borderColor: selected ? theme.colors.primary : theme.colors.border,
        marginBottom: 10,
      }}
    >
      <Pressable
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel={cardA11yLabel}
        android_ripple={androidRipple(theme.colors.primaryMuted)}
        style={({ pressed }) => ({
          flex: 1,
          flexDirection: 'row',
          alignItems: 'center',
          gap: 12,
          borderRadius: theme.radius.md,
          overflow: 'hidden',
          opacity: pressed ? 0.85 : 1,
        })}
      >
        {selectMode ? (
          <Ionicons
            name={selected ? 'checkbox' : 'square-outline'}
            size={24}
            color={selected ? theme.colors.primary : theme.colors.textFaint}
          />
        ) : (
          <BankAvatar provider={row.provider} />
        )}

        <View style={{ flex: 1 }}>
        <AppText variant="body" weight="700" numberOfLines={1}>
          {row.product_name}
        </AppText>
        <AppText variant="small" color="textMuted" numberOfLines={1}>
          {row.provider}
        </AppText>
        {tags.length || qualifier.conditional || nonStandard ? (
          <Row gap={6} style={{ flexWrap: 'wrap', marginTop: 6 }}>
            {tags.map((t, i) => (
              <View
                key={`${t}-${i}`}
                style={{
                  paddingHorizontal: 7,
                  paddingVertical: 2,
                  borderRadius: theme.radius.sm,
                  backgroundColor: theme.colors.chip,
                }}
              >
                <AppText variant="tiny" color="chipText">
                  {t}
                </AppText>
              </View>
            ))}
            {qualifier.conditional ? (
              <View
                style={{
                  paddingHorizontal: 7,
                  paddingVertical: 2,
                  borderRadius: theme.radius.sm,
                  borderWidth: 1,
                  borderColor: theme.colors.warning,
                }}
              >
                <AppText variant="tiny" style={{ color: theme.colors.warning }} weight="700">
                  {qualifier.shortLabel}
                </AppText>
              </View>
            ) : null}
            {nonStandard ? (
              <View
                style={{
                  paddingHorizontal: 7,
                  paddingVertical: 2,
                  borderRadius: theme.radius.sm,
                  backgroundColor: theme.colors.chip,
                }}
              >
                <AppText variant="tiny" style={{ color: theme.colors.warning }} weight="700">
                  Non-standard
                </AppText>
              </View>
            ) : null}
          </Row>
        ) : null}
      </View>

        <View style={{ alignItems: 'flex-end', minWidth: 76 }}>
          <AppText variant="tiny" color="textFaint">
            {rateLabel}
          </AppText>
          <AppText
            variant="rate"
            style={{ color: lowerIsBetter ? theme.colors.success : theme.colors.primary }}
          >
            {rateText}
          </AppText>
          {row.comparison_rate ? (
            <AppText variant="tiny" color="textFaint">
              {formatRate(row.comparison_rate)} cmp
            </AppText>
          ) : null}
        </View>
      </Pressable>

      {!selectMode ? (
        <Pressable
          onPress={() => toggleFavorite(row.product_key)}
          hitSlop={10}
          accessibilityRole="button"
          accessibilityLabel={favorite ? 'Remove from watchlist' : 'Add to watchlist'}
          accessibilityState={{ selected: favorite }}
          android_ripple={androidRipple(theme.colors.primaryMuted, true)}
          style={{
            minWidth: 48,
            minHeight: 48,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: theme.radius.sm,
            overflow: 'hidden',
          }}
        >
          <Ionicons
            name={favorite ? 'star' : 'star-outline'}
            size={20}
            color={favorite ? theme.colors.warning : theme.colors.textFaint}
          />
        </Pressable>
      ) : null}
    </View>
  );
}
