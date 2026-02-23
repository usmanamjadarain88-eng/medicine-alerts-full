import { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Alert } from 'react-native';
import { useRouter } from 'expo-router';
import { setStoredUser } from '../lib/storage';
import { COLORS, ADMIN_ACCESS_CODE } from '../lib/constants';

export default function AdminSignUpScreen() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [adminCode, setAdminCode] = useState('');

  const handleRegister = async () => {
    const e = email.trim();
    const p = password.trim();
    const c = confirmPassword.trim();
    const code = adminCode.trim();
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
    if (code !== ADMIN_ACCESS_CODE) {
      Alert.alert('Access Denied', 'Invalid Admin Access Code.');
      return;
    }
    await setStoredUser({
      email: e,
      password: p,
      role: 'admin',
      pin_enabled: false,
    });
    router.replace('/pin-set');
  };

  return (
    <View style={styles.container}>
      <Text style={styles.logo}>Curax</Text>
      <Text style={styles.title}>Admin Registration</Text>
      <Text style={styles.subtext}>
        Only authenticated administrators can register. Please use your authorized email.
      </Text>
      <TextInput
        style={styles.input}
        placeholder="Email"
        placeholderTextColor={COLORS.textSecondary}
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        keyboardType="email-address"
      />
      <TextInput
        style={styles.input}
        placeholder="Password"
        placeholderTextColor={COLORS.textSecondary}
        value={password}
        onChangeText={setPassword}
        secureTextEntry
      />
      <TextInput
        style={styles.input}
        placeholder="Confirm Password"
        placeholderTextColor={COLORS.textSecondary}
        value={confirmPassword}
        onChangeText={setConfirmPassword}
        secureTextEntry
      />
      <TextInput
        style={styles.input}
        placeholder="Admin Access Code"
        placeholderTextColor={COLORS.textSecondary}
        value={adminCode}
        onChangeText={setAdminCode}
        secureTextEntry
        autoCapitalize="characters"
      />
      <TouchableOpacity style={styles.primaryButton} onPress={handleRegister} activeOpacity={0.8}>
        <Text style={styles.primaryButtonText}>Register as Admin</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.adminBg, padding: 24, paddingTop: 48 },
  logo: { fontSize: 28, fontWeight: '700', color: COLORS.adminAccent, marginBottom: 32 },
  title: { fontSize: 22, fontWeight: '700', color: COLORS.adminAccent, marginBottom: 8 },
  subtext: { fontSize: 14, color: COLORS.textSecondary, lineHeight: 20, marginBottom: 28 },
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
    backgroundColor: COLORS.adminAccent,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 16,
  },
  primaryButtonText: { fontSize: 17, fontWeight: '600', color: '#fff' },
});
