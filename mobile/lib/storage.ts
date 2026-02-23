import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEY = '@curax_user';
const LOGS_STORAGE_KEY = '@curax_logs';

export type Role = 'user' | 'admin';

export interface StoredUser {
  email: string;
  password: string;
  role: Role;
  pin_enabled: boolean;
  pin_code?: string;
}

export async function getStoredUser(): Promise<StoredUser | null> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as StoredUser;
    if (!data.email || !data.role) return null;
    return data;
  } catch {
    return null;
  }
}

export async function setStoredUser(user: StoredUser): Promise<void> {
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(user));
}

export async function clearStoredUser(): Promise<void> {
  await AsyncStorage.removeItem(STORAGE_KEY);
}

export async function updateStoredUser(updates: Partial<StoredUser>): Promise<void> {
  const current = await getStoredUser();
  if (!current) return;
  await setStoredUser({ ...current, ...updates });
}

// --- Logs (one entry per received alert) ---
export type LogStatus = 'Taken' | 'Missed' | 'Skipped';
export type LogSource = 'User' | 'System';

export interface AlertLog {
  id: string;
  dateTime: number; // ISO timestamp
  medicineName: string;
  dose: string;
  status: LogStatus;
  source: LogSource;
}

export async function getLogs(): Promise<AlertLog[]> {
  try {
    const raw = await AsyncStorage.getItem(LOGS_STORAGE_KEY);
    if (!raw) return [];
    const data = JSON.parse(raw) as AlertLog[];
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export async function addLog(entry: Omit<AlertLog, 'id'>): Promise<AlertLog> {
  const logs = await getLogs();
  const newLog: AlertLog = {
    ...entry,
    id: `log_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
  };
  logs.unshift(newLog);
  await AsyncStorage.setItem(LOGS_STORAGE_KEY, JSON.stringify(logs));
  return newLog;
}

/** Call when user marks a dose as Taken */
export function createTakenLog(medicineName: string, dose: string): Omit<AlertLog, 'id'> {
  return {
    dateTime: Date.now(),
    medicineName,
    dose,
    status: 'Taken',
    source: 'User',
  };
}

/** Call when scheduled time passes and dose was not marked (auto-logged) */
export function createMissedLog(medicineName: string, dose: string): Omit<AlertLog, 'id'> {
  return {
    dateTime: Date.now(),
    medicineName,
    dose,
    status: 'Missed',
    source: 'System',
  };
}

/** Call when user/system marks as Skipped */
export function createSkippedLog(medicineName: string, dose: string, source: LogSource): Omit<AlertLog, 'id'> {
  return {
    dateTime: Date.now(),
    medicineName,
    dose,
    status: 'Skipped',
    source,
  };
}
