import React, { useCallback, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  TouchableOpacity,
  useWindowDimensions,
} from 'react-native';
import type { AlertLog } from '../lib/storage';
import { COLORS } from '../lib/constants';

const MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(' ');

function formatDate(ts: number): string {
  const d = new Date(ts);
  const day = d.getDate();
  const month = MONTHS[d.getMonth()];
  const year = d.getFullYear();
  return `${day.toString().padStart(2, '0')} ${month} ${year}`;
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  let h = d.getHours();
  const m = d.getMinutes();
  const am = h < 12;
  if (h === 0) h = 12;
  else if (h > 12) h -= 12;
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')} ${am ? 'AM' : 'PM'}`;
}

const STATUS_COLORS: Record<AlertLog['status'], string> = {
  Taken: '#16a34a',
  Missed: '#dc2626',
  Skipped: '#ea580c',
};

type SortKey = 'date' | 'medicineName';
type SortDir = 'asc' | 'desc';

const ROWS_PER_PAGE_OPTIONS = [10, 25, 50] as const;

interface LogsTableProps {
  logs: AlertLog[];
  onRefresh: () => void;
}

export function LogsTable({ logs, onRefresh }: LogsTableProps) {
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('date');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return logs;
    return logs.filter(
      (l) =>
        l.medicineName.toLowerCase().includes(q) ||
        l.dose.toLowerCase().includes(q) ||
        l.status.toLowerCase().includes(q) ||
        l.source.toLowerCase().includes(q) ||
        formatDate(l.dateTime).toLowerCase().includes(q) ||
        formatTime(l.dateTime).toLowerCase().includes(q)
    );
  }, [logs, search]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      if (sortKey === 'date') {
        const diff = a.dateTime - b.dateTime;
        return sortDir === 'asc' ? diff : -diff;
      }
      const na = a.medicineName.toLowerCase();
      const nb = b.medicineName.toLowerCase();
      const cmp = na.localeCompare(nb);
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / rowsPerPage));
  const currentPage = Math.min(page, totalPages - 1);
  const start = currentPage * rowsPerPage;
  const pageLogs = sorted.slice(start, start + rowsPerPage);

  const toggleSort = useCallback((key: SortKey) => {
    setSortKey(key);
    setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    setPage(0);
  }, []);

  const { width } = useWindowDimensions();
  const colWidth = width < 400 ? 72 : 88;
  const nameWidth = width < 400 ? 90 : 110;

  return (
    <View style={styles.wrapper}>
      <View style={styles.toolbar}>
        <TextInput
          style={styles.search}
          placeholder="Search logs..."
          placeholderTextColor={COLORS.textSecondary}
          value={search}
          onChangeText={(t) => {
            setSearch(t);
            setPage(0);
          }}
        />
        <View style={styles.sortRow}>
          <Text style={styles.sortLabel}>Sort: </Text>
          <TouchableOpacity
            style={[styles.sortBtn, sortKey === 'date' && styles.sortBtnActive]}
            onPress={() => toggleSort('date')}
          >
            <Text style={styles.sortBtnText}>Date {sortKey === 'date' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.sortBtn, sortKey === 'medicineName' && styles.sortBtnActive]}
            onPress={() => toggleSort('medicineName')}
          >
            <Text style={styles.sortBtnText}>Medicine {sortKey === 'medicineName' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</Text>
          </TouchableOpacity>
        </View>
        <View style={styles.paginationRow}>
          <Text style={styles.paginationLabel}>Rows: </Text>
          {ROWS_PER_PAGE_OPTIONS.map((n) => (
            <TouchableOpacity
              key={n}
              style={[styles.rowsBtn, rowsPerPage === n && styles.rowsBtnActive]}
              onPress={() => {
                setRowsPerPage(n);
                setPage(0);
              }}
            >
              <Text style={styles.rowsBtnText}>{n}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator style={styles.tableScroll}>
        <View style={styles.table}>
          <View style={[styles.row, styles.headerRow]}>
            <Text style={[styles.cell, styles.headerCell, { width: colWidth }]}>Date</Text>
            <Text style={[styles.cell, styles.headerCell, { width: colWidth - 8 }]}>Time</Text>
            <Text style={[styles.cell, styles.headerCell, { width: nameWidth }]}>Medicine Name</Text>
            <Text style={[styles.cell, styles.headerCell, { width: colWidth + 10 }]}>Dose</Text>
            <Text style={[styles.cell, styles.headerCell, { width: 76 }]}>Status</Text>
            <Text style={[styles.cell, styles.headerCell, { width: 60 }]}>Source</Text>
          </View>
          {pageLogs.length === 0 ? (
            <View style={styles.emptyRow}>
              <Text style={styles.emptyText}>No log entries</Text>
            </View>
          ) : (
            pageLogs.map((log) => (
              <View key={log.id} style={styles.row}>
                <Text style={[styles.cell, { width: colWidth }]} numberOfLines={1}>
                  {formatDate(log.dateTime)}
                </Text>
                <Text style={[styles.cell, { width: colWidth - 8 }]} numberOfLines={1}>
                  {formatTime(log.dateTime)}
                </Text>
                <Text style={[styles.cell, { width: nameWidth }]} numberOfLines={1}>
                  {log.medicineName}
                </Text>
                <Text style={[styles.cell, { width: colWidth + 10 }]} numberOfLines={1}>
                  {log.dose}
                </Text>
                <View style={[styles.statusBadge, { backgroundColor: STATUS_COLORS[log.status] }]}>
                  <Text style={styles.statusText}>{log.status}</Text>
                </View>
                <Text style={[styles.cell, { width: 60 }]} numberOfLines={1}>
                  {log.source}
                </Text>
              </View>
            ))
          )}
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Text style={styles.footerText}>
          {sorted.length} log(s) • Page {currentPage + 1} of {totalPages}
        </Text>
        <View style={styles.footerButtons}>
          <TouchableOpacity
            style={[styles.pageBtn, currentPage === 0 && styles.pageBtnDisabled]}
            disabled={currentPage === 0}
            onPress={() => setPage((p) => Math.max(0, p - 1))}
          >
            <Text style={styles.pageBtnText}>Prev</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.pageBtn, currentPage >= totalPages - 1 && styles.pageBtnDisabled]}
            disabled={currentPage >= totalPages - 1}
            onPress={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
          >
            <Text style={styles.pageBtnText}>Next</Text>
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    flex: 1,
    minHeight: 320,
  },
  toolbar: {
    marginBottom: 12,
  },
  search: {
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    color: COLORS.text,
    backgroundColor: COLORS.card,
    marginBottom: 10,
  },
  sortRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    marginBottom: 8,
  },
  sortLabel: {
    fontSize: 12,
    color: COLORS.textSecondary,
    marginRight: 6,
  },
  sortBtn: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: COLORS.border,
    marginRight: 6,
  },
  sortBtnActive: {
    backgroundColor: COLORS.adminAccent,
  },
  sortBtnText: {
    fontSize: 12,
    color: COLORS.text,
    fontWeight: '500',
  },
  paginationRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  paginationLabel: {
    fontSize: 12,
    color: COLORS.textSecondary,
    marginRight: 6,
  },
  rowsBtn: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: COLORS.border,
    marginRight: 6,
  },
  rowsBtnActive: {
    backgroundColor: COLORS.adminAccent,
  },
  rowsBtnText: {
    fontSize: 12,
    color: COLORS.text,
    fontWeight: '500',
  },
  tableScroll: {
    flexGrow: 0,
    maxHeight: 340,
  },
  table: {
    minWidth: 520,
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
    paddingHorizontal: 8,
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
    marginRight: 4,
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    width: 76,
    alignItems: 'center',
  },
  statusText: {
    fontSize: 11,
    fontWeight: '600',
    color: '#fff',
  },
  emptyRow: {
    padding: 24,
    alignItems: 'center',
  },
  emptyText: {
    fontSize: 14,
    color: COLORS.textSecondary,
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 12,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
  },
  footerText: {
    fontSize: 12,
    color: COLORS.textSecondary,
  },
  footerButtons: {
    flexDirection: 'row',
    gap: 8,
  },
  pageBtn: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 6,
    backgroundColor: COLORS.adminAccent,
  },
  pageBtnDisabled: {
    opacity: 0.5,
  },
  pageBtnText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#fff',
  },
});
