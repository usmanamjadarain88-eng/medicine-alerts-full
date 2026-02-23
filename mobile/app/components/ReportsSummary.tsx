import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import type { AlertLog } from '../lib/storage';
import { COLORS } from '../lib/constants';

export type ReportRange = '7' | '30' | 'all';

const RANGES: { key: ReportRange; label: string }[] = [
  { key: '7', label: 'Last 7 days' },
  { key: '30', label: 'Last 30 days' },
  { key: 'all', label: 'All time' },
];

function filterByRange(logs: AlertLog[], range: ReportRange): AlertLog[] {
  if (range === 'all') return logs;
  const now = Date.now();
  const ms = range === '7' ? 7 * 24 * 60 * 60 * 1000 : 30 * 24 * 60 * 60 * 1000;
  const cutoff = now - ms;
  return logs.filter((l) => l.dateTime >= cutoff);
}

interface ReportsSummaryProps {
  logs: AlertLog[];
}

export function ReportsSummary({ logs }: ReportsSummaryProps) {
  const [range, setRange] = useState<ReportRange>('all');

  const { filtered, taken, missed, skipped, total, adherencePct, byMedicine } = useMemo(() => {
    const filtered = filterByRange(logs, range);
    const taken = filtered.filter((l) => l.status === 'Taken').length;
    const missed = filtered.filter((l) => l.status === 'Missed').length;
    const skipped = filtered.filter((l) => l.status === 'Skipped').length;
    const total = filtered.length;
    const adherencePct = total > 0 ? Math.round((taken / total) * 100) : 0;

    const byMedicine: { name: string; taken: number; missed: number; skipped: number; total: number }[] = [];
    const map = new Map<string, { taken: number; missed: number; skipped: number }>();
    filtered.forEach((l) => {
      const key = l.medicineName || 'Unknown';
      const cur = map.get(key) ?? { taken: 0, missed: 0, skipped: 0 };
      if (l.status === 'Taken') cur.taken++;
      else if (l.status === 'Missed') cur.missed++;
      else cur.skipped++;
      map.set(key, cur);
    });
    map.forEach((v, name) => {
      byMedicine.push({
        name,
        taken: v.taken,
        missed: v.missed,
        skipped: v.skipped,
        total: v.taken + v.missed + v.skipped,
      });
    });
    byMedicine.sort((a, b) => b.total - a.total);

    return { filtered, taken, missed, skipped, total, adherencePct, byMedicine };
  }, [logs, range]);

  return (
    <View style={styles.wrapper}>
      <Text style={styles.sectionLabel}>Date range</Text>
      <View style={styles.rangeRow}>
        {RANGES.map((r) => (
          <TouchableOpacity
            key={r.key}
            style={[styles.rangeBtn, range === r.key && styles.rangeBtnActive]}
            onPress={() => setRange(r.key)}
          >
            <Text style={[styles.rangeBtnText, range === r.key && styles.rangeBtnTextActive]}>{r.label}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <Text style={styles.sectionLabel}>Summary</Text>
      <View style={styles.cardsRow}>
        <View style={styles.card}>
          <Text style={styles.cardValue}>{total}</Text>
          <Text style={styles.cardLabel}>Total alerts</Text>
        </View>
        <View style={[styles.card, styles.cardGreen]}>
          <Text style={styles.cardValue}>{taken}</Text>
          <Text style={styles.cardLabel}>Taken</Text>
        </View>
        <View style={[styles.card, styles.cardRed]}>
          <Text style={styles.cardValue}>{missed}</Text>
          <Text style={styles.cardLabel}>Missed</Text>
        </View>
        <View style={[styles.card, styles.cardOrange]}>
          <Text style={styles.cardValue}>{skipped}</Text>
          <Text style={styles.cardLabel}>Skipped</Text>
        </View>
      </View>

      <View style={styles.adherenceCard}>
        <Text style={styles.adherenceLabel}>Adherence rate</Text>
        <Text style={styles.adherenceValue}>{adherencePct}%</Text>
        <Text style={styles.adherenceHint}>Taken ÷ Total alerts in selected period</Text>
      </View>

      {byMedicine.length > 0 && (
        <>
          <Text style={styles.sectionLabel}>By medicine</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator style={styles.tableScroll}>
            <View style={styles.table}>
              <View style={[styles.row, styles.headerRow]}>
                <Text style={[styles.cell, styles.headerCell, styles.colName]}>Medicine</Text>
                <Text style={[styles.cell, styles.headerCell, styles.colNum]}>Taken</Text>
                <Text style={[styles.cell, styles.headerCell, styles.colNum]}>Missed</Text>
                <Text style={[styles.cell, styles.headerCell, styles.colNum]}>Skipped</Text>
                <Text style={[styles.cell, styles.headerCell, styles.colNum]}>Total</Text>
              </View>
              {byMedicine.map((m) => (
                <View key={m.name} style={styles.row}>
                  <Text style={[styles.cell, styles.colName]} numberOfLines={1}>{m.name}</Text>
                  <Text style={[styles.cell, styles.colNum, styles.numGreen]}>{m.taken}</Text>
                  <Text style={[styles.cell, styles.colNum, styles.numRed]}>{m.missed}</Text>
                  <Text style={[styles.cell, styles.colNum, styles.numOrange]}>{m.skipped}</Text>
                  <Text style={[styles.cell, styles.colNum]}>{m.total}</Text>
                </View>
              ))}
            </View>
          </ScrollView>
        </>
      )}

      {filtered.length === 0 && (
        <Text style={styles.empty}>No alerts in this period.</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    flex: 1,
  },
  sectionLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: COLORS.textSecondary,
    marginBottom: 8,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  rangeRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 20,
  },
  rangeBtn: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: COLORS.border,
  },
  rangeBtnActive: {
    backgroundColor: COLORS.adminAccent,
  },
  rangeBtnText: {
    fontSize: 13,
    color: COLORS.text,
    fontWeight: '500',
  },
  rangeBtnTextActive: {
    color: '#fff',
  },
  cardsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
    marginBottom: 16,
  },
  card: {
    minWidth: 72,
    padding: 12,
    borderRadius: 10,
    backgroundColor: COLORS.card,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  cardGreen: {
    borderColor: '#16a34a',
    backgroundColor: 'rgba(22, 163, 74, 0.08)',
  },
  cardRed: {
    borderColor: '#dc2626',
    backgroundColor: 'rgba(220, 38, 38, 0.08)',
  },
  cardOrange: {
    borderColor: '#ea580c',
    backgroundColor: 'rgba(234, 88, 12, 0.08)',
  },
  cardValue: {
    fontSize: 22,
    fontWeight: '700',
    color: COLORS.text,
  },
  cardLabel: {
    fontSize: 12,
    color: COLORS.textSecondary,
    marginTop: 2,
  },
  adherenceCard: {
    padding: 16,
    borderRadius: 10,
    backgroundColor: COLORS.card,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: 24,
  },
  adherenceLabel: {
    fontSize: 12,
    color: COLORS.textSecondary,
    marginBottom: 4,
  },
  adherenceValue: {
    fontSize: 28,
    fontWeight: '700',
    color: COLORS.adminAccent,
  },
  adherenceHint: {
    fontSize: 11,
    color: COLORS.textSecondary,
    marginTop: 4,
  },
  tableScroll: {
    maxHeight: 260,
  },
  table: {
    minWidth: 320,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 8,
    overflow: 'hidden',
    backgroundColor: COLORS.card,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
    paddingVertical: 10,
    paddingHorizontal: 10,
  },
  headerRow: {
    backgroundColor: COLORS.adminAccent,
  },
  headerCell: {
    fontWeight: '700',
    color: '#fff',
    fontSize: 12,
  },
  cell: {
    fontSize: 12,
    color: COLORS.text,
  },
  colName: {
    width: 140,
    marginRight: 8,
  },
  colNum: {
    width: 52,
    textAlign: 'center',
  },
  numGreen: { color: '#16a34a', fontWeight: '600' },
  numRed: { color: '#dc2626', fontWeight: '600' },
  numOrange: { color: '#ea580c', fontWeight: '600' },
  empty: {
    fontSize: 14,
    color: COLORS.textSecondary,
    textAlign: 'center',
    marginTop: 16,
  },
});
