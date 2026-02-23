import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert } from 'react-native';
import { useRouter } from 'expo-router';
import { getStoredUser, clearStoredUser, getLogs } from '../lib/storage';
import type { StoredUser, AlertLog } from '../lib/storage';
import { COLORS } from '../lib/constants';
import { LogsTable } from './components/LogsTable';
import { ReportsSummary } from './components/ReportsSummary';

export default function DashboardScreen() {
  const router = useRouter();
  const [user, setUser] = useState<StoredUser | null>(null);
  const [adminTab, setAdminTab] = useState<'Overview' | 'Logs' | 'Reports'>('Overview');
  const [logs, setLogs] = useState<AlertLog[]>([]);

  const loadUser = useCallback(async () => {
    const u = await getStoredUser();
    setUser(u);
  }, []);

  const loadLogs = useCallback(async () => {
    const list = await getLogs();
    setLogs(list);
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  useEffect(() => {
    if (user?.role === 'admin') {
      loadLogs();
    }
  }, [user?.role, loadLogs, adminTab]);

  const handleLogout = () => {
    Alert.alert('Logout', 'Clear local data and return to sign up?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Logout',
        style: 'destructive',
        onPress: async () => {
          await clearStoredUser();
          router.replace('/signup');
        },
      },
    ]);
  };

  if (!user) {
    return (
      <View style={styles.centered}>
        <Text style={styles.loading}>Loading...</Text>
      </View>
    );
  }

  const isAdmin = user.role === 'admin';

  return (
    <View style={[styles.container, isAdmin && styles.containerAdmin]}>
      <View style={styles.header}>
        <Text style={styles.logo}>Curax</Text>
        <Text style={styles.roleBadge}>{isAdmin ? 'Admin' : 'User'}</Text>
      </View>

      {isAdmin && (
        <View style={styles.tabBar}>
          <TouchableOpacity
            style={[styles.tab, adminTab === 'Overview' && styles.tabActive]}
            onPress={() => setAdminTab('Overview')}
          >
            <Text style={[styles.tabText, adminTab === 'Overview' && styles.tabTextActive]}>Overview</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tab, adminTab === 'Logs' && styles.tabActive]}
            onPress={() => setAdminTab('Logs')}
          >
            <Text style={[styles.tabText, adminTab === 'Logs' && styles.tabTextActive]}>Logs</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tab, adminTab === 'Reports' && styles.tabActive]}
            onPress={() => setAdminTab('Reports')}
          >
            <Text style={[styles.tabText, adminTab === 'Reports' && styles.tabTextActive]}>Reports</Text>
          </TouchableOpacity>
        </View>
      )}

      {isAdmin && adminTab === 'Logs' ? (
        <View style={styles.logsSection}>
          <Text style={styles.logsTitle}>Alert logs</Text>
          <Text style={styles.logsHint}>Each received alert appears as one row. Latest first.</Text>
          <LogsTable logs={logs} onRefresh={loadLogs} />
          <TouchableOpacity style={styles.logoutButton} onPress={handleLogout} activeOpacity={0.8}>
            <Text style={styles.logoutText}>Logout</Text>
          </TouchableOpacity>
        </View>
      ) : isAdmin && adminTab === 'Reports' ? (
        <View style={styles.logsSection}>
          <Text style={styles.logsTitle}>Reports</Text>
          <Text style={styles.logsHint}>Summary and adherence from alert logs.</Text>
          <ReportsSummary logs={logs} />
          <TouchableOpacity style={styles.logoutButton} onPress={handleLogout} activeOpacity={0.8}>
            <Text style={styles.logoutText}>Logout</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <>
          <View style={styles.card}>
            <Text style={styles.welcome}>
              {isAdmin ? 'Admin Dashboard' : 'User Dashboard'}
            </Text>
            <Text style={styles.email}>{user.email}</Text>
            <Text style={styles.hint}>
              {isAdmin
                ? 'Manage users and settings (no backend connected).'
                : 'View your medicine reminders (no backend connected).'}
            </Text>
          </View>

          <TouchableOpacity style={styles.logoutButton} onPress={handleLogout} activeOpacity={0.8}>
            <Text style={styles.logoutText}>Logout</Text>
          </TouchableOpacity>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
    paddingHorizontal: 24,
    paddingTop: 56,
  },
  containerAdmin: {
    backgroundColor: COLORS.adminBg,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: COLORS.background,
  },
  loading: {
    fontSize: 16,
    color: COLORS.textSecondary,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 32,
  },
  logo: {
    fontSize: 28,
    fontWeight: '700',
    color: COLORS.primary,
  },
  roleBadge: {
    fontSize: 12,
    fontWeight: '600',
    color: COLORS.textSecondary,
    backgroundColor: COLORS.border,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
  },
  card: {
    backgroundColor: COLORS.card,
    borderRadius: 12,
    padding: 20,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  welcome: {
    fontSize: 20,
    fontWeight: '700',
    color: COLORS.text,
    marginBottom: 6,
  },
  email: {
    fontSize: 14,
    color: COLORS.textSecondary,
    marginBottom: 12,
  },
  hint: {
    fontSize: 14,
    color: COLORS.textSecondary,
    lineHeight: 20,
  },
  tabBar: {
    flexDirection: 'row',
    marginBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
  },
  tab: {
    paddingVertical: 12,
    paddingHorizontal: 20,
    marginRight: 4,
  },
  tabActive: {
    borderBottomWidth: 2,
    borderBottomColor: COLORS.adminAccent,
  },
  tabText: {
    fontSize: 15,
    color: COLORS.textSecondary,
    fontWeight: '500',
  },
  tabTextActive: {
    color: COLORS.adminAccent,
  },
  logsSection: {
    flex: 1,
    minHeight: 360,
  },
  logsTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: COLORS.adminAccent,
    marginBottom: 4,
  },
  logsHint: {
    fontSize: 13,
    color: COLORS.textSecondary,
    marginBottom: 12,
  },
  logoutButton: {
    marginTop: 32,
    paddingVertical: 14,
    alignItems: 'center',
  },
  logoutText: {
    fontSize: 16,
    color: COLORS.error,
    fontWeight: '500',
  },
});
