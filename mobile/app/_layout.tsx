import { Stack } from 'expo-router';

export default function RootLayout() {
  return (
    <Stack screenOptions={{ headerShown: false, animation: 'fade' }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="signup" />
      <Stack.Screen name="admin-signup" />
      <Stack.Screen name="pin-enter" />
      <Stack.Screen name="pin-set" />
      <Stack.Screen name="dashboard" />
    </Stack>
  );
}
