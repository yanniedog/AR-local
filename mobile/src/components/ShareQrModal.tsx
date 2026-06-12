import React, { useEffect, useState } from 'react';
import { Modal, Pressable, Share, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

import { APK_MANIFEST_URL, APK_RELEASE_TAG, REPO } from '../config';
import { fetchApkManifest } from '../lib/appUpdateLogic';
import { logSwallowedError } from '../lib/degradationLog';
import { useTheme } from '../theme/ThemeProvider';
import { AppText, Button } from './ui';

const RELEASE_PAGE_URL = `https://github.com/${REPO}/releases/tag/${APK_RELEASE_TAG}`;

/**
 * Share dialog with a scannable QR for the latest Android APK — point a friend's
 * camera at the screen instead of typing a URL. Prefers the direct APK
 * download_url from the rolling manifest; falls back to the release page.
 */
export function ShareQrModal({
  visible,
  onClose,
  shareMessage,
}: {
  visible: boolean;
  onClose: () => void;
  shareMessage: string | null;
}) {
  const theme = useTheme();
  const [apkUrl, setApkUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!visible || apkUrl) return;
    let alive = true;
    fetchApkManifest(APK_MANIFEST_URL)
      .then((m) => {
        if (alive) setApkUrl(m.download_url);
      })
      .catch((err) => logSwallowedError('shareQr.apkManifest', err));
    return () => {
      alive = false;
    };
  }, [visible, apkUrl]);

  const qrValue = apkUrl ?? RELEASE_PAGE_URL;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <Pressable
          onPress={onClose}
          accessibilityLabel="Dismiss share dialog"
          style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)' }}
        />
        <View
          style={{
            width: '100%',
            maxWidth: 360,
            backgroundColor: theme.colors.surface,
            borderRadius: theme.radius.lg,
            borderWidth: 1,
            borderColor: theme.colors.border,
            padding: 20,
            alignItems: 'center',
          }}
        >
          <AppText variant="h3" style={{ marginBottom: 4 }}>
            Share AustralianRates
          </AppText>
          <AppText variant="small" color="textMuted" style={{ marginBottom: 16, textAlign: 'center' }}>
            Scan with a phone camera to {apkUrl ? 'download the latest Android APK' : 'open the latest release'}.
          </AppText>
          <View style={{ padding: 12, backgroundColor: '#fff', borderRadius: theme.radius.md }}>
            <QRCode value={qrValue} size={208} />
          </View>
          <View style={{ alignSelf: 'stretch', marginTop: 20, gap: 10 }}>
            {shareMessage ? (
              <Button
                title="Share link instead"
                icon="share-social-outline"
                variant="secondary"
                onPress={() => {
                  void Share.share({ message: shareMessage });
                }}
              />
            ) : null}
            <Button title="Done" variant="ghost" onPress={onClose} />
          </View>
        </View>
      </View>
    </Modal>
  );
}
