import {
  BottomSheetBackdrop,
  BottomSheetModal,
  BottomSheetModalProvider,
  BottomSheetScrollView,
  type BottomSheetBackdropProps,
} from '@gorhom/bottom-sheet';
import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, View } from 'react-native';

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
  const sheetRef = useRef<BottomSheetModal>(null);
  const snapPoints = useMemo(() => ['50%', '85%'], []);
  const [draft, setDraft] = useState<Filters>(filters);

  useEffect(() => {
    if (visible) {
      setDraft(filters);
      sheetRef.current?.present();
      return;
    }
    sheetRef.current?.dismiss();
  }, [visible, filters]);

  const groups = groupsFor(section);
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

  const renderBackdrop = useCallback(
    (props: BottomSheetBackdropProps) => (
      <BottomSheetBackdrop {...props} disappearsOnIndex={-1} appearsOnIndex={0} opacity={0.55} pressBehavior="close" />
    ),
    [],
  );

  return (
    <BottomSheetModalProvider>
      <BottomSheetModal
        ref={sheetRef}
        snapPoints={snapPoints}
        enablePanDownToClose
        onDismiss={onClose}
        backdropComponent={renderBackdrop}
        handleIndicatorStyle={{
          width: 40,
          height: 4,
          backgroundColor: theme.colors.textFaint,
        }}
        backgroundStyle={{
          backgroundColor: theme.colors.surface,
          borderTopLeftRadius: 22,
          borderTopRightRadius: 22,
        }}
      >
        <Row style={{ justifyContent: 'space-between', paddingHorizontal: 16, paddingBottom: 8 }}>
          <AppText variant="h3">Filters</AppText>
          <Pressable onPress={onClose} hitSlop={10} accessibilityRole="button" accessibilityLabel="Close filters">
            <Ionicons name="close" size={24} color={theme.colors.text} />
          </Pressable>
        </Row>
        <Divider />
        <BottomSheetScrollView contentContainerStyle={{ padding: 16, gap: 18, paddingBottom: 12 }}>
          <View>
            <AppText variant="small" weight="700" style={{ marginBottom: 10 }}>
              Show
            </AppText>
            <Chip
              label="Include non-standard accounts"
              icon="options-outline"
              selected={draft.includeNonStandard}
              onPress={() => setDraft((d) => ({ ...d, includeNonStandard: !d.includeNonStandard }))}
            />
          </View>

          {groups.map((g) => {
            const options = distinctValues(rows, g.field).slice(0, 24);
            if (!options.length) return null;
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
        </BottomSheetScrollView>
        <Divider />
        <Row gap={12} style={{ padding: 16, paddingBottom: 28 }}>
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
      </BottomSheetModal>
    </BottomSheetModalProvider>
  );
}

function resetFilters() {
  return {
    providers: [],
    rateTypes: [],
    lvrTiers: [],
    repaymentTypes: [],
    depositKinds: [],
    interestPayments: [],
    accountFeatures: [],
    eligibilityCriteria: [],
    includeNonStandard: false,
  };
}
