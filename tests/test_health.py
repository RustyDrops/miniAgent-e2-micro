import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from miniagent import health, tools
from miniagent.agent import role_schemas


class HealthTests(unittest.TestCase):
    def test_collects_selected_vm_and_service_metrics(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            root = Path(directory)
            proc, groups = root / 'proc', root / 'cgroup'
            (proc / 'self').mkdir(parents=True)
            group = groups / 'system.slice' / 'miniagent.service'
            group.mkdir(parents=True)
            (proc / 'meminfo').write_text('MemTotal: 1048576 kB\nMemAvailable: 524288 kB\n', encoding='utf-8')
            (proc / 'self/status').write_text('Name: private-canary\nVmRSS: 10240 kB\n', encoding='utf-8')
            (proc / 'self/cgroup').write_text('0::/system.slice/miniagent.service\n', encoding='utf-8')
            (proc / 'net').mkdir(parents=True, exist_ok=True)
            (proc / 'net/dev').write_text('Inter-|   Receive                                                |  Transmit\n face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n  eth0: 10485760       0    0    0    0     0          0         0  5242880       0    0    0    0     0       0          0\n', encoding='utf-8')
            (group / 'memory.current').write_text('104857600', encoding='utf-8')
            (group / 'memory.max').write_text('419430400', encoding='utf-8')
            (group / 'cpu.max').write_text('25000 100000', encoding='utf-8')
            disk = SimpleNamespace(total=30 * 1024**3, free=20 * 1024**3)
            with patch('miniagent.health.shutil.disk_usage', return_value=disk), patch('miniagent.health.os.getloadavg', return_value=(0.1, 0.2, 0.3), create=True):
                result = health.collect(root, proc, groups)
            self.assertEqual(result['vm_memory_total_mib'], 1024)
            self.assertEqual(result['vm_memory_available_mib'], 512)
            self.assertEqual(result['process_rss_mib'], 10)
            self.assertEqual(result['service_memory_current_mib'], 100)
            self.assertEqual(result['service_memory_limit_mib'], 400)
            self.assertEqual(result['service_cpu_quota_cores'], 0.25)
            self.assertEqual(result['workspace_disk_free_gib'], 20)
            self.assertEqual(result['load_averages_1_5_15'], [0.1, 0.2, 0.3])
            self.assertEqual(result['network_ingress_mib'], 10.0)
            self.assertEqual(result['network_egress_mib'], 5.0)
            self.assertNotIn('private-canary', json.dumps(result))

    def test_invalid_cgroup_path_and_missing_files_are_safe(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            root = Path(directory)
            (root / 'proc/self').mkdir(parents=True)
            (root / 'proc/self/cgroup').write_text('0::/../../escape\n', encoding='utf-8')
            self.assertIsNone(health.cgroup_directory(root / 'proc', root / 'cgroup'))
            result = health.collect(root, root / 'proc', root / 'cgroup')
            self.assertIsNone(result['service_memory_limit_mib'])
            self.assertIsNone(result['vm_memory_total_mib'])

    def test_health_tool_is_available_to_specialists(self):
        for role in ('researcher', 'builder', 'reviewer'):
            self.assertIn('system_health', [x['function']['name'] for x in role_schemas(role, tools.SCHEMAS)])
        with patch('miniagent.health.collect', return_value={'vm_memory_available_mib': 100}):
            self.assertEqual(json.loads(tools.handle('system_health', {}))['vm_memory_available_mib'], 100)


if __name__ == '__main__': unittest.main()
