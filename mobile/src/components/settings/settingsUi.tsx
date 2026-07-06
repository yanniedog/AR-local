import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Switch, View } from 'react-native';

import { TOUCH_TARGET_MIN, TouchTarget } from '../TouchTarget';
import { AppText, Card, IconButton, Row } from '../ui';
import { useTheme } from '../../theme/ThemeProvider';

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={{ marginBottom: 18 }}>
      <AppText variant="small" weight="700" color="textMuted" style={{ marginBottom: 8, marginLeft: 4 }}>
        {title.toUpperCase()}
      </AppText>
      <Card style={{ gap: 4 }}>{children}</Card>
    </View>
  );
}

export function InterestOrderRow({
  title,
  canMoveUp,
  canMoveDown,
  canRemove,
  onMoveUp,
  onMoveDown,
  onRemove,
}: {
  title: string;
  canMoveUp: boolean;
  canMoveDown: boolean;
  canRemove: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
}) {
  return (
    <Row style={{ justifyContent: 'space-between', paddingVertical: 6 }}>
      <AppText variant="body" weight="600" style={{ flex: 1 }}>
        {title}
      </AppText>
      <Row gap={4}>
        <IconButton
          icon="chevron-up"
          onPress={onMoveUp}
          disabled={!canMoveUp}
          accessibilityLabel={`Move ${title} up`}
        />
        <IconButton
          icon="chevron-down"
          onPress={onMoveDown}
          disabled={!canMoveDown}
          accessibilityLabel={`Move ${title} down`}
        />
        <IconButton
          icon="close"
          onPress={onRemove}
          disabled={!canRemove}
          accessibilityLabel={`Remove ${title}`}
        />
      </Row>
    </Row>
  );
}

export function Label({ text }: { text: string }) {
  return (
    <AppText variant="small" color="textMuted" style={{ marginBottom: 10 }}>
      {text}
    </AppText>
  );
}

export function ToggleRow({
  icon,
  label,
  sub,
  value,
  onChange,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  sub?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  const theme = useTheme();
  return (
    <Row gap={12} style={{ minHeight: TOUCH_TARGET_MIN }}>
      <Ionicons name={icon} size={20} color={theme.colors.primary} />
      <View style={{ flex: 1 }}>
        <AppText variant="body" weight="600">
          {label}
        </AppText>
        {sub ? (
          <AppText variant="tiny" color="textFaint">
            {sub}
          </AppText>
        ) : null}
      </View>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ true: theme.colors.primary, false: theme.colors.border }}
      />
    </Row>
  );
}

export function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <Row style={{ justifyContent: 'space-between', paddingVertical: 5 }}>
      <AppText variant="small" color="textMuted">
        {label}
      </AppText>
      <AppText variant="small" weight="600">
        {value}
      </AppText>
    </Row>
  );
}
