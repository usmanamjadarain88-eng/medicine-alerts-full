import { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, KeyboardAvoidingView, Platform, Alert } from 'react-native';
import { useRouter } from 'expo-router';
import { setStoredUser } from '../lib/storage';
import { COLORS } from '../lib/constants';

export default function SignUpScreen() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const handleSignUp = async () => {
    const e = email.trim();
    const p = password.trim();
    const c = confirmPassword.trim();
    if (!e) {
      Alert.alert('Validation', 'Please enter your email.');
      return;
    }
    if (!p || p.length < 6) {
      Alert.alert('Validation', 'Password must be at least 6 characters.');
      return;
    }
    if (p !== c) {
      Alert.alert('Validation', 'Passwords do not match.');
      return;
    }
    await setStoredUser({
      email: e,
      password: p,
      role: 'user',
      pin_enabled: false,
    });
    router.replace('/dashboard');
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.content}>
        <Text style={styles.logo}>Curax</Text>

        <TextInput
          style={styles.input}
          placeholder="Email"
          placeholderTextColor={COLORS.textSecondary}
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          autoComplete="email"
        />
        <TextInput
          style={styles.input}
          placeholder="Password"
          placeholderTextColor={COLORS.textSecondary}
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoComplete="new-password"
        />
        <TextInput
          style={styles.input}
          placeholder="Confirm Password"
          placeholderTextColor={COLORS.textSecondary}
          value={confirmPassword}
          onChangeText={setConfirmPassword}
          secureTextEntry
          autoComplete="new-password"
        />

        <TouchableOpacity style={styles.primaryButton} onPress={handleSignUp} activeOpacity={0.8}>
          <Text style={styles.primaryButtonText}>Sign Up</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.textButton}
          onPress={() => router.push('/admin-signup')}
          activeOpacity={0.7}
        >
          <Text style={styles.textButtonLabel}>Sign Up as Admin</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  content: {
    maxWidth: 360,
    width: '100%',
    alignSelf: 'center',
  },
  logo: {
    fontSize: 28,
    fontWeight: '700',
    color: COLORS.primary,
    marginBottom: 40,
  },
  input: {
    height: 48,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 10,
    paddingHorizontal: 16,
    fontSize: 16,
    backgroundColor: COLORS.card,
    marginBottom: 14,
    color: COLORS.text,
  },
  primaryButton: {
    height: 50,
    borderRadius: 10,
    backgroundColor: COLORS.primary,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 10,
  },
  primaryButtonText: {
    fontSize: 17,
    fontWeight: '600',
    color: '#fff',
  },
  textButton: {
    marginTop: 20,
    paddingVertical: 12,
    alignItems: 'center',
  },
  textButtonLabel: {
    fontSize: 15,
    color: COLORS.primary,
    fontWeight: '500',
  },
});
