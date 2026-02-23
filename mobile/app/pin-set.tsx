import { useState, useRef } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Alert } from 'react-native';
import { useRouter } from 'expo-router';
import { getStoredUser, updateStoredUser } from '../lib/storage';
import { COLORS } from '../lib/constants';

const PIN_LENGTH = 4;

export default function PinSetScreen() {
  const router = useRouter();
  const inputRef = useRef<TextInput>(null);
  const [step, setStep] = useState<'enter' | 'confirm'>('enter');
  const [pin, setPin] = useState('');
  const [confirmPin, setConfirmPin] = useState('');

  const handleSave = async () => {
    if (step === 'enter') {
      if (pin.length !== PIN_LENGTH) {
        Alert.alert('PIN', 'Please enter 4 digits.');
        return;
      }
      setStep('confirm');
      setConfirmPin('');
      return;
    }
    if (confirmPin !== pin) {
      Alert.alert('PIN', 'PINs do not match. Try again.');
      setConfirmPin('');
      return;
    }
    const user = await getStoredUser();
    if (user) {
      await updateStoredUser({ pin_enabled: true, pin_code: pin });
    }
    router.replace('/dashboard');
  };

  const handleSkip = () => {
    router.replace('/dashboard');
  };

  const displayPin = step === 'enter' ? pin : confirmPin;
  const isComplete = displayPin.length === PIN_LENGTH;

  return (
    <View style={styles.container}>
      <Text style={styles.logo}>Curax</Text>
      <Text style={styles.title}>
        {step === 'enter' ? 'Set PIN' : 'Confirm PIN'}
      </Text>
      <Text style={styles.subtext}>
        {step === 'enter'
          ? 'Enter a 4-digit PIN to lock the app (optional).'
          : 'Enter the same PIN again.'}
      </Text>

      <TextInput
        ref={inputRef}
        style={styles.hiddenInput}
        value={displayPin}
        onChangeText={step === 'enter' ? setPin : setConfirmPin}
        keyboardType="number-pad"
        maxLength={PIN_LENGTH}
        secureTextEntry
      />

      <TouchableOpacity style={styles.dotsWrap} onPress={() => inputRef.current?.focus()} activeOpacity={1}>
      <View style={styles.dots}>
        {Array.from({ length: PIN_LENGTH }).map((_, i) => (
          <View
            key={i}
            style={[styles.dot, i < displayPin.length && styles.dotFilled]}
          />
        ))}
      </View>
      </TouchableOpacity>

      <TouchableOpacity
        style={[styles.primaryButton, !isComplete && styles.primaryButtonDisabled]}
        onPress={handleSave}
        disabled={!isComplete}
        activeOpacity={0.8}
      >
        <Text style={styles.primaryButtonText}>
          {step === 'confirm' ? 'Save PIN' : 'Continue'}
        </Text>
      </TouchableOpacity>

      <TouchableOpacity style={styles.skipButton} onPress={handleSkip} activeOpacity={0.7}>
        <Text style={styles.skipButtonText}>Skip for now</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
    paddingHorizontal: 24,
    paddingTop: 80,
  },
  logo: {
    fontSize: 28,
    fontWeight: '700',
    color: COLORS.primary,
    marginBottom: 48,
  },
  title: {
    fontSize: 20,
    fontWeight: '600',
    color: COLORS.text,
    marginBottom: 6,
  },
  subtext: {
    fontSize: 14,
    color: COLORS.textSecondary,
    marginBottom: 24,
  },
  hiddenInput: {
    position: 'absolute',
    opacity: 0,
    height: 0,
    width: 0,
  },
  dotsWrap: { marginBottom: 32 },
  dots: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 16,
  },
  dot: {
    width: 14,
    height: 14,
    borderRadius: 7,
    borderWidth: 2,
    borderColor: COLORS.border,
  },
  dotFilled: {
    backgroundColor: COLORS.primary,
    borderColor: COLORS.primary,
  },
  primaryButton: {
    height: 50,
    borderRadius: 10,
    backgroundColor: COLORS.primary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  primaryButtonDisabled: {
    opacity: 0.5,
  },
  primaryButtonText: {
    fontSize: 17,
    fontWeight: '600',
    color: '#fff',
  },
  skipButton: {
    marginTop: 20,
    paddingVertical: 12,
    alignItems: 'center',
  },
  skipButtonText: {
    fontSize: 15,
    color: COLORS.textSecondary,
  },
});
