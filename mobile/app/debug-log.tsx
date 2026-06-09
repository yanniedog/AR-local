import * as Application from 'expo-application';
import * as Clipboard from 'expo-clipboard';
import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, ScrollView, Share, View } from 'react-native';

import { Screen } from '../src/components/Screen';
import { AppText, Button, Card, Row } from '../src/components/ui';
import { debugLog, formatLogUploadBody, uploadLogsToPasteRs } from '../src/lib/debugLog';
import { useTheme } from '../src/theme/ThemeProvider';

export default function DebugLogScreen() {
  const theme = useTheme();
  const scrollRef = useRef<ScrollView>(null);
  const [text, setText] = useState(debugLog.getText());
  const [uploadUrl, setUploadUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState<'copy' | 'share' | 'upload' | null>(null);

  useEffect(() => {
    return debugLog.subscribe(() => setText(debugLog.getText()));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollToEnd({ animated: false });
  }, [text]);

  const onClear = useCallback(() => {
    Alert.alert('Clear debug log?', 'In-memory log buffer will be emptied.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Clear',
        style: 'destructive',
        onPress: () => {
          debugLog.clear();
          setUploadUrl(null);
        },
      },
    ]);
  }, []);

  const onCopy = useCallback(async () => {
    setBusy('copy');
    try {
      await Clipboard.setStringAsync(text);
      Alert.alert('Copied', `${debugLog.getEntries().length} lines copied.`);
    } catch (err) {
      Alert.alert('Copy failed', String((err as Error)?.message ?? err));
    } finally {
      setBusy(null);
    }
  }, [text]);

  const onShare = useCallback(async () => {
    setBusy('share');
    let path: string | null = null;
    try {
      const fileName = `ar-debug-log-${Date.now()}.txt`;
      path = `${FileSystem.cacheDirectory}${fileName}`;
      await FileSystem.writeAsStringAsync(path, text);
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(path, {
          mimeType: 'text/plain',
          dialogTitle: 'Share debug log',
          UTI: 'public.plain-text',
        });
      } else {
        await Share.share({ message: text, title: fileName });
      }
    } catch (err) {
      Alert.alert('Share failed', String((err as Error)?.message ?? err));
    } finally {
      if (path) {
        await FileSystem.deleteAsync(path, { idempotent: true }).catch(() => {});
      }
      setBusy(null);
    }
  }, [text]);

  const runUpload = useCallback(async () => {
    setBusy('upload');
    try {
      const body = formatLogUploadBody(text, {
        app: Application.nativeApplicationVersion ?? 'unknown',
        lines: String(debugLog.getEntries().length),
      });
      const { url, truncated } = await uploadLogsToPasteRs(body);
      setUploadUrl(url);
      Alert.alert(
        truncated ? 'Uploaded (truncated)' : 'Uploaded',
        truncated ? 'paste.rs accepted a partial upload (size limit).' : url,
      );
    } catch (err) {
      Alert.alert('Upload failed', String((err as Error)?.message ?? err));
    } finally {
      setBusy(null);
    }
  }, [text]);

  const onUpload = useCallback(() => {
    Alert.alert(
      'Upload to paste.rs?',
      'Creates a public paste anyone with the link can read. Only upload if you accept that risk.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Upload', style: 'destructive', onPress: () => void runUpload() },
      ],
    );
  }, [runUpload]);

  const onCopyUrl = useCallback(async () => {
    if (!uploadUrl) return;
    await Clipboard.setStringAsync(uploadUrl);
    Alert.alert('Copied', 'Paste URL copied.');
  }, [uploadUrl]);

  return (
    <Screen style={{ flex: 1 }}>
        <View style={{ padding: 16, paddingBottom: 8, gap: 12 }}>
          <AppText variant="tiny" color="textFaint">
            May include device/network info. Secrets are redacted; avoid sharing if sensitive.
          </AppText>
          <Row gap={8} style={{ flexWrap: 'wrap' }}>
            <Button title="Clear" icon="trash-outline" variant="ghost" onPress={onClear} />
            <Button
              title="Copy"
              icon="copy-outline"
              variant="secondary"
              loading={busy === 'copy'}
              onPress={() => void onCopy()}
            />
            <Button
              title="Share"
              icon="share-outline"
              variant="secondary"
              loading={busy === 'share'}
              onPress={() => void onShare()}
            />
            <Button
              title="Upload"
              icon="cloud-upload-outline"
              loading={busy === 'upload'}
              onPress={onUpload}
            />
          </Row>
          {uploadUrl ? (
            <Card style={{ gap: 8 }}>
              <AppText variant="tiny" color="textMuted">
                paste.rs
              </AppText>
              <AppText variant="small" selectable style={{ fontFamily: 'monospace' }}>
                {uploadUrl}
              </AppText>
              <Button title="Copy link" icon="link-outline" variant="ghost" onPress={() => void onCopyUrl()} />
            </Card>
          ) : null}
        </View>
        <ScrollView
          ref={scrollRef}
          style={{ flex: 1 }}
          contentContainerStyle={{
            paddingHorizontal: 16,
            paddingBottom: 32,
          }}
        >
          <View
            style={{
              backgroundColor: theme.dark ? theme.colors.surface : theme.colors.chip,
              borderRadius: theme.radius.md,
              borderWidth: 1,
              borderColor: theme.colors.border,
              padding: 12,
              minHeight: 200,
            }}
          >
            <AppText
              variant="tiny"
              selectable
              style={{
                fontFamily: 'monospace',
                lineHeight: 16,
                color: theme.colors.text,
              }}
            >
              {text || '(empty — use the app; logs appear here)'}
            </AppText>
          </View>
        </ScrollView>
      </Screen>
  );
}
