import os
import shutil
import datetime
from tkinter import messagebox

def backup_db(db_path='curax_alerts.db', backup_dir='backups'):
    if not os.path.exists(db_path):
        return False
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f'curax_alerts_{timestamp}.bak')
    shutil.copy2(db_path, backup_path)
    return backup_path

def restore_db(backup_dir='backups', db_path='curax_alerts.db', max_age_hours=24):
    if not os.path.exists(backup_dir):
        messagebox.showerror('Restore Failed', 'No backup directory found.')
        return False
    backups = [f for f in os.listdir(backup_dir) if f.startswith('curax_alerts_') and f.endswith('.bak')]
    if not backups:
        messagebox.showerror('Restore Failed', 'No backup files found.')
        return False
    backups.sort(reverse=True)
    for backup in backups:
        backup_path = os.path.join(backup_dir, backup)
        mtime = os.path.getmtime(backup_path)
        age_hours = (datetime.datetime.now().timestamp() - mtime) / 3600
        if age_hours <= max_age_hours:
            shutil.copy2(backup_path, db_path)
            messagebox.showinfo('Restore Success', f'Database restored from backup: {backup}')
            return True
    messagebox.showerror('Restore Failed', f'No backup within {max_age_hours} hours found.')
    return False
