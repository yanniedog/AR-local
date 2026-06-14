import { Ionicons } from '@expo/vector-icons';
import React, { useEffect, useMemo, useState } from 'react';
import { Modal, Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { distinctProviders, distinctValues, type Filters } from '../data/selectors';
import { distinctEligibilityCriteria } from '../data/eligibility';
import { distinctAccountFeatures } from '../data/features';
import { humanizeEnum } from '../data/format';
import type { ProductDetail, RateRow, SectionKey } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { AppText, Button, Chip, Divider, Row } from './ui';

interface Group {
  title: string;
  field: keyof RateRow;
  key: keyof Filters;
}

function groupsFor(section: SectionKey): Group[] {
  if (section === 'Mortgage') {
    return [
      { title: 'Purpose', field: 'loan_purpose', key: 'loanPurposes' },
      { title: 'Rate type', field: 'rate_type', key: 'rateTypes' },
      { title: 'Repayment', field: 'ribbon_repayment_type', key: 'repaymentTypes' },
      { title: 'LVR tier', field: 'lvr_tier', key: 'lvrTiers' },
    ];
  }
  if (section === 'TD') {
    return [{ title: 'Interest paid', field: 'interest_payment', key: 'interestPayments' }];
  }
  return [{ title: 'Account type', field: 'ribbon_deposit_kind', key: 'depositKinds' }];
}

// Plain RN Modal sheet: @gorhom/bottom-sheet modals silently failed to present
// under Reanimated 4, leaving the filter button dead.
export function FilterSheet({
  visible,
  onClose,
  rows,
  section,
  filters,
  onApply,
  detailsProducts,
}: {
  visible: boolean;
  onClose: () => void;
  rows: RateRow[];
  section: SectionKey;
  filters: Filters;
  onApply: (f: Filters) => void;
  detailsProducts?: Record<string, ProductDetail> | null;
}) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const [draft, setDraft] = useState<Filters>(filters);

  useEffect(() => {
    if (visible) setDraft(filters);
  }, [visible, filters]);

  const groups = groupsFor(section);
  // Facet option lists depend only on the (scoped) rows, never on the draft
  // selection — memoize them so toggling a chip doesn't re-scan every row for
  // every filter group (the open-sheet lag).
  const groupOptions = useMemo(
    () =>
      groups
        .map((g) => ({ g, options: distinctValues(rows, g.field).slice(0, 24) }))
        .filter(({ options }) => options.length > 0),
    [rows, section], // eslint-disable-line react-hooks/exhaustive-deps -- groups is derived from section
  );
  const providers = useMemo(() => distinctProviders(rows), [rows]);
  const accountFeatures = useMemo(
    () => distinctAccountFeatures(rows, detailsProducts).slice(0, 24),
    [rows, detailsProducts],
  );
  const eligibilityCriteria = useMemo(
    () => distinctEligibilityCriteria(rows, detailsProducts).slice(0, 24),
    [rows, detailsProducts],
  );

  const toggle = (key: keyof Filters, value: string) => {
    setDraft((d) => {
      const list = (d[key] as string[]) ?? [];
      const next = list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
      return { ...d, [key]: next };
    });
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, justifyContent: 'flex-end' }}>
        <Pressable
          onPress={onClose}
          accessibilityLabel="Dismiss filters"
          style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.55)' }}
        />
        <View
          style={{
            maxHeight: '85%',
            backgroundColor: theme.colors.surface,
            borderTopLeftRadius: 22,
            borderTopRightRadius: 22,
            paddingTop: 8,
          }}
        >
          <View
            style={{
              alignSelf: 'center',
              width: 40,
              height: 4,
              borderRadius: 2,
              backgroundColor: theme.colors.textFaint,
              marginBottom: 8,
            }}
          />
          <Row style={{ justifyContent: 'space-between', paddingHorizontal: 16, paddingBottom: 8 }}>
            <AppText variant="h3">Filters</AppText>
            <Pressable onPress={onClose} hitSlop={10} accessibilityRole="button" accessibilityLabel="Close filters">
              <Ionicons name="close" size={24} color={theme.colors.text} />
            </Pressable>
          </Row>
          <Divider />
          <ScrollView contentContainerStyle={{ padding: 16, gap: 18, paddingBottom: 12 }}>
            {groupOptions.map(({ g, options }) => {
              return (
                <View key={g.key}>
                  <AppText variant="small" weight="700" style={{ marginBottom: 10 }}>
                    {g.title}
                  </AppText>
                  <Row gap={8} style={{ flexWrap: 'wrap' }}>
                    {options.map((o) => (
                      <Chip
                        key={o}
                        label={humanizeEnum(o)}
                        selected={(draft[g.key] as string[]).includes(o)}
                        onPress={() => toggle(g.key, o)}
                      />
                    ))}
                  </Row>
                </View>
              );
            })}

            {accountFeatures.length ? (
              <View>
                <AppText variant="small" weight="700" style={{ marginBottom: 10 }}>
                  Account features
                </AppText>
                <Row gap={8} style={{ flexWrap: 'wrap' }}>
                  {accountFeatures.map((f) => (
                    <Chip
                      key={f}
                      label={humanizeEnum(f)}
                      selected={draft.accountFeatures.includes(f)}
                      onPress={() => toggle('accountFeatures', f)}
                    />
                  ))}
                </Row>
              </View>
            ) : null}

            {eligibilityCriteria.length ? (
              <View>
                <AppText variant="small" weight="700" style={{ marginBottom: 10 }}>
                  Eligibility
                </AppText>
                <Row gap={8} style={{ flexWrap: 'wrap' }}>
                  {eligibilityCriteria.map((c) => (
                    <Chip
                      key={c}
                      label={humanizeEnum(c)}
                      selected={draft.eligibilityCriteria.includes(c)}
                      onPress={() => toggle('eligibilityCriteria', c)}
                    />
                  ))}
                </Row>
              </View>
            ) : null}

            <View>
              <AppText variant="small" weight="700" style={{ marginBottom: 10 }}>
                Lenders
              </AppText>
              <Row gap={8} style={{ flexWrap: 'wrap' }}>
                {providers.map((p) => (
                  <Chip
                    key={p}
                    label={p}
                    selected={draft.providers.includes(p)}
                    onPress={() => toggle('providers', p)}
                  />
                ))}
              </Row>
            </View>
          </ScrollView>
          <Divider />
          <Row gap={12} style={{ padding: 16, paddingBottom: Math.max(insets.bottom, 12) + 12 }}>
            <Button
              title="Reset"
              variant="ghost"
              style={{ flex: 1 }}
              onPress={() => setDraft({ ...filters, ...resetFilters() })}
            />
            <Button
              title="Apply"
              style={{ flex: 2 }}
              onPress={() => {
                onApply(draft);
                onClose();
              }}
            />
          </Row>
        </View>
      </View>
    </Modal>
  );
}

function resetFilters() {
  return {
    providers: [],
    rateTypes: [],
    lvrTiers: [],
    repaymentTypes: [],
    loanPurposes: [],
    depositKinds: [],
    interestPayments: [],
    accountFeatures: [],
    eligibilityCriteria: [],
  };
}
