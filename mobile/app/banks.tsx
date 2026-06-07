import { Ionicons } from '@expo/vector-icons';
import { FlashList } from '@shopify/flash-list';
import React, { useMemo, useState } from 'react';
import { Pressable, View } from 'react-native';

import { BankAvatar } from '../src/components/BankAvatar';
import { SearchBar } from '../src/components/controls';
import { EmptyState } from '../src/components/feedback';
import { AppText, Row } from '../src/components/ui';
import { SECTIONS } from '../src/constants';
import { formatRate } from '../src/data/format';
import { groupByProvider, type ProviderGroup } from '../src/data/selectors';
import { useStore } from '../src/data/store';
import { openBank } from '../src/lib/nav';
import type { SectionKey } from '../src/types';
import { useTheme } from '../src/theme/ThemeProvider';

export default function Banks() {
  const core = useStore((s) => s.core);
  const [query, setQuery] = useState('');

  const groups = useMemo(() => (core ? groupByProvider(core.sections) : []), [core]);
  const filtered = useMemo(
    () => groups.filter((g) => g.provider.toLowerCase().includes(query.toLowerCase())),
    [groups, query],
  );

  if (!core) return null;

  return (
    <View style={{ flex: 1 }}>
      <View style={{ padding: 16 }}>
        <SearchBar value={query} onChangeText={setQuery} placeholder="Search lenders" />
      </View>
      <FlashList
        data={filtered}
        keyExtractor={(g) => g.provider}
        estimatedItemSize={76}
        contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 32 }}
        renderItem={({ item }) => <BankRow group={item} />}
        ListEmptyComponent={<EmptyState title="No lenders found" />}
      />
    </View>
  );
}

function BankRow({ group }: { group: ProviderGroup }) {
  const theme = useTheme();
  const sections = Object.keys(group.bestBySection) as SectionKey[];
  return (
    <Pressable
      onPress={() => openBank(group.provider)}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingVertical: 12,
        paddingHorizontal: 14,
        backgroundColor: theme.colors.card,
        borderRadius: theme.radius.lg,
        borderWidth: 1,
        borderColor: theme.colors.border,
        marginBottom: 10,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <BankAvatar provider={group.provider} />
      <View style={{ flex: 1 }}>
        <AppText variant="body" weight="700" numberOfLines={1}>
          {group.provider}
        </AppText>
        <Row gap={8} style={{ marginTop: 4, flexWrap: 'wrap' }}>
          {sections.map((s) => {
            const best = group.bestBySection[s];
            if (!best) return null;
            return (
              <AppText key={s} variant="tiny" color="textMuted">
                {SECTIONS[s].title}: <AppText variant="tiny" weight="700">{formatRate(best.rate)}</AppText>
              </AppText>
            );
          })}
        </Row>
      </View>
      <Ionicons name="chevron-forward" size={18} color={theme.colors.textFaint} />
    </Pressable>
  );
}
