import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Modal, Pressable, View } from 'react-native';

import { useStore } from '../data/store';
import { proGateCopy, type ProGateIntent, RATE_INTELLIGENCE_PRO } from '../lib/proAccess';
import { useTheme } from '../theme/ThemeProvider';
import { AppText, Button, Card, Row } from './ui';

export function ProPaywall({
  visible,
  intent,
  onClose,
  onUpgraded,
}: {
  visible: boolean;
  intent: ProGateIntent;
  onClose: () => void;
  onUpgraded?: () => void;
}) {
  const theme = useTheme();
  const setPref = useStore((s) => s.setPref);
  const copy = proGateCopy(intent);

  const onUpgrade = () => {
    setPref('rateIntelligencePro', true);
    onUpgraded?.();
    onClose();
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable
        style={{
          flex: 1,
          backgroundColor: 'rgba(0,0,0,0.55)',
          justifyContent: 'flex-end',
        }}
        onPress={onClose}
      >
        <Pressable onPress={(e) => e.stopPropagation()}>
          <Card
            style={{
              margin: 12,
              marginBottom: 24,
              borderTopLeftRadius: theme.radius.lg,
              borderTopRightRadius: theme.radius.lg,
              gap: 12,
            }}
          >
            <Row gap={10}>
              <View
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: theme.radius.md,
                  backgroundColor: theme.colors.primaryMuted,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Ionicons name="sparkles" size={22} color={theme.colors.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <AppText variant="h3">{copy.title}</AppText>
                <AppText variant="tiny" color="textFaint">
                  {RATE_INTELLIGENCE_PRO}
                </AppText>
              </View>
            </Row>

            <AppText variant="small" color="textMuted" style={{ lineHeight: 20 }}>
              {copy.body}
            </AppText>

            {copy.bullets.map((line) => (
              <Row key={line} gap={8} style={{ alignItems: 'flex-start' }}>
                <Ionicons name="checkmark-circle" size={18} color={theme.colors.success} style={{ marginTop: 1 }} />
                <AppText variant="small" style={{ flex: 1 }}>
                  {line}
                </AppText>
              </Row>
            ))}

            <Button title="Upgrade to Pro" icon="sparkles" onPress={onUpgrade} />
            <Button title="Not now" variant="ghost" onPress={onClose} />

            {__DEV__ ? (
              <AppText variant="tiny" color="textFaint" style={{ textAlign: 'center', lineHeight: 16 }}>
                Dev stub: Upgrade sets a local Pro flag (no store billing yet).
              </AppText>
            ) : null}
          </Card>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
