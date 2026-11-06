"""Read-only, bounded resource measurements; no host configuration or secrets."""
import os
from pathlib import Path, PurePosixPath
import shutil


def read_small(path, limit=32768):
    try:
        with path.open('r', encoding='utf-8') as stream:
            text = stream.read(limit + 1)
        return text if len(text) <= limit else ''
    except (OSError, UnicodeError):
        return ''


def kb_fields(text, wanted):
    values = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].rstrip(':') in wanted and parts[1].isdigit() and parts[2] == 'kB':
            values[parts[0].rstrip(':')] = int(parts[1])
    return values


def cgroup_directory(proc_root, cgroup_root):
    text = read_small(proc_root / 'self/cgroup', 4096)
    for line in text.splitlines():
        if not line.startswith('0::'):
            continue
        group = PurePosixPath(line[3:])
        if not group.is_absolute() or '..' in group.parts:
            return None
        try:
            root = cgroup_root.resolve()
            target = root.joinpath(*group.parts[1:]).resolve()
            return target if target.is_relative_to(root) else None
        except (OSError, RuntimeError):
            return None
    return None


def number(text):
    value = text.strip()
    return int(value) if value.isdigit() else None


def network_stats(proc_root):
    text = read_small(proc_root / 'net/dev', 4096)
    rx_bytes, tx_bytes = 0, 0
    for line in text.splitlines():
        if ':' in line:
            iface, stats = line.split(':', 1)
            if iface.strip() != 'lo':
                parts = stats.split()
                if len(parts) >= 9 and parts[0].isdigit() and parts[8].isdigit():
                    rx_bytes += int(parts[0])
                    tx_bytes += int(parts[8])
    return rx_bytes, tx_bytes


def collect(workspace, proc_root=Path('/proc'), cgroup_root=Path('/sys/fs/cgroup')):
    mem = kb_fields(read_small(proc_root / 'meminfo'), {'MemTotal', 'MemAvailable'})
    status = kb_fields(read_small(proc_root / 'self/status'), {'VmRSS'})
    rx, tx = network_stats(proc_root)
    result = {'vm_memory_total_mib': round(mem['MemTotal'] / 1024, 1) if 'MemTotal' in mem else None,
              'vm_memory_available_mib': round(mem['MemAvailable'] / 1024, 1) if 'MemAvailable' in mem else None,
              'process_rss_mib': round(status['VmRSS'] / 1024, 1) if 'VmRSS' in status else None,
              'service_memory_current_mib': None, 'service_memory_limit_mib': None,
              'service_cpu_quota_cores': None, 'workspace_disk_total_gib': None,
              'workspace_disk_free_gib': None, 'load_averages_1_5_15': None,
              'network_egress_mib': round(tx / (1024 ** 2), 2) if tx else None,
              'network_ingress_mib': round(rx / (1024 ** 2), 2) if rx else None}
    group = cgroup_directory(proc_root, cgroup_root)
    if group is not None:
        current = number(read_small(group / 'memory.current', 128))
        limit = number(read_small(group / 'memory.max', 128))
        if current is not None: result['service_memory_current_mib'] = round(current / (1024 ** 2), 1)
        if limit is not None: result['service_memory_limit_mib'] = round(limit / (1024 ** 2), 1)
        parts = read_small(group / 'cpu.max', 128).split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit() and int(parts[1]) > 0:
            result['service_cpu_quota_cores'] = round(int(parts[0]) / int(parts[1]), 2)
    try:
        disk = shutil.disk_usage(workspace)
        result['workspace_disk_total_gib'] = round(disk.total / (1024 ** 3), 2)
        result['workspace_disk_free_gib'] = round(disk.free / (1024 ** 3), 2)
    except OSError:
        pass
    try:
        result['load_averages_1_5_15'] = [round(x, 2) for x in os.getloadavg()]
    except (AttributeError, OSError):
        pass
    return result
