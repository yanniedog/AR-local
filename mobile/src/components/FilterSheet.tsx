import { Ionicons } from '@expo/vector-icons';
import React, { useMemo, useState } from 'react';
import { Modal, Pressable, ScrollView, View } from 'react-native';

import { distinctValues, type Filters } from '../data/selectors';
import { humanizeEnum } from '../data/format';
import type { RateRow, SectionKey } from '../types';
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
}: {
  visible: boolean;
  onClose: () => void;
  rows: RateRow[];
  section: SectionKey;
  filters: Filters;
  onApply: (f: Filters) => void;
}) {
  const theme = useTheme();
  const [draft, setDraft] = useState<Filters>(filters);

  // Resync draft whenever the sheet is (re)opened.
  React.useEffect(() => {
    if (visible) setDraft(filters);
  }, [visible, filters]);

  const groups = groupsFor(section);
  // Show every lender (50+ per section) — the sheet scrolls, so don't truncate.
  const providers = useMemo(() => distinctValues(rows, 'provider'), [rows]);

  const toggle = (key: keyof Filters, value: string) => {
    setDraft((d) => {
      const list = (d[key] as string[]) ?? [];
      const next = list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
      return { ...d, [key]: next };
    });
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: '#0006' }}>
        <View
          style={{
            backgroundColor: theme.colors.surface,
            borderTopLeftRadius: 22,
            borderTopRightRadius: 22,
            maxHeight: '85%',
            paddingBottom: 28,
          }}
        >
          <Row style={{ justifyContent: 'space-between', padding: 16 }}>
            <AppText variant="h3">Filters</AppText>
            <Pressable onPress={onClose} hitSlop={10}>
              <Ionicons name="close" size={24} color={theme.colors.text} />
            </Pressable>
          </Row>
          <Divider />
          <ScrollView contentContainerStyle={{ padding: 16, gap: 18 }}>
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
          <Row gap={12} style={{ padding: 16 }}>
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
    depositKinds: [],
    interestPayments: [],
    includeNonStandard: false,
  };
}
