"""Show the unified installation in the main desktop workflow on both OSes."""
import time
from auto_carrier import AutoClient, policy
from workflow import WorkflowError
from auto_carrier_view import registration_ready, status_view


class Adapter:
    install_block_code = 'unified_already_installed'

    def __init__(self, client):
        self.auto = AutoClient(client)

    def inspect(self):
        state = self.auto.action('status')
        variant = state['variant']
        self.auto.variant = variant
        family, board = policy.MODELS[variant]
        # The phone status operation verifies this exact model/OS policy and
        # every native/payload hash before it returns; no SIM identifiers leave it.
        from device_info import identify
        device = identify({'variant': variant, 'board_type': board, 'os_version': policy.OS_VERSION})
        device['hardware_tested'] = False
        alive = state.get('manager_alive') is True
        view = status_view(state)
        ready = view['ready']
        checks = [{'id': key, 'status': 'pass', 'code': code} for key, code in (
            ('model', 'device_identified'), ('os', 'os_3216_required'),
            ('root', 'root_qnx_arm32_required'), ('native', 'native_hashes_required'),
            ('installation', 'unified_payload_verified'))]
        checks.append({'id': 'carrier_selection', 'status': 'pass' if ready else 'wait',
                       'code': view['check_code']})
        return {'schema': 2, 'managed_adapter': 'unified_carriers', 'checked_at': int(time.time()),
                'device': device, 'checks': checks, 'status': state,
                'outcome': 'compatible' if ready else 'not_ready',
                'installation': {'state': 'busy' if alive else 'stopped',
                                 'payload_verified': True, 'enabled': state.get('enabled') is True},
                'can_install': False, 'can_update': False, 'can_start': False,
                'can_enable': not state.get('enabled') and not alive, 'can_restore': True,
                'automatic_carrier_selection': True,
                'normal_reboot_after_sim_change': True,
                'hardware_validation': 'unified_candidate_see_per_device_acceptance',
                'provider_lifecycle': 'retain_provider_until_normal_reboot'}

    def service(self, action):
        if action == 'status':
            return self.auto.action('status')
        if action in ('start', 'stop'):
            return self.action('disable' if action == 'stop' else action)
        raise WorkflowError('invalid_action')

    def action(self, action):
        if action == 'status':
            report = self.inspect()
            return {'preflight': report, 'status': report['status'], 'registered': registration_ready(report['status'])}
        if action not in ('start', 'enable', 'disable', 'stop'):
            raise WorkflowError(self.install_block_code)
        result = self.auto.action('disable' if action == 'stop' else action)
        result['automatic_carrier_selection'] = True
        return result
