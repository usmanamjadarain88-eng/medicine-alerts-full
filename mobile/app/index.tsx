import { useEffect } from 'react';
import { useRouter } from 'expo-router';
import { getStoredUser } from '../lib/storage';
import { View, ActivityIndicator, StyleSheet } from 'react-native';
import { COLORS } from '../lib/constants';

export default function Index() {
  const router = useRouter();

  useEffect(() => {
    (async () => {
      const user = await getStoredUser();
      if (!user) {
        router.replace('/signup');
        return;
      }
      if (user.pin_enabled && user.pin_code) {
        router.replace('/pin-enter');
        return;
      }
      router.replace('/dashboard');
    })();
  }, []);

  return (
    <View style={styles.container}>
      <ActivityIndicator size="large" color={COLORS.primary} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: COLORS.background,
  },
});
